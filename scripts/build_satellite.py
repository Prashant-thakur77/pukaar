"""Bake a before/after satellite view of the July 2023 Beas flood.

Searches Sentinel-2 L2A on Element 84 Earth Search (STAC over the AWS Open
Data bucket `sentinel-cogs`: https://registry.opendata.aws/sentinel-2-l2a-cogs/),
measures cloud inside our own crop from each scene's scene-classification
layer (the whole-tile cloud figure says little about one valley), picks the
clearest June 2023 scene as "before", and as "after" both the first look
after the 9-11 July flood that is mostly clear and the first fully clear
look, then reads only the crop around Mandi town and Pandoh dam from the
cloud-optimised GeoTIFFs over HTTP range requests (one internal tile per
request, retried; raw crops are cached in ~/.cache/pukaar-satellite).

Writes, under frontend/public/satellite/2023/, per scene date:
  <date>.jpg                   true colour (B04/B03/B02, 10 m), 1600 px wide, <= 250 KB
  <date>-water.png             MNDWI water mask (B03 vs B11) in river blue,
                               with cloud drawn as a grey veil (unknown, not dry)
and scenes.json: scene ids, dates, cloud cover, bounds, markers, water area,
every candidate considered, source and licence.

Run once; the output is committed so the page makes no imagery requests:

    AWS_NO_SIGN_REQUEST=YES uv run --with rasterio --with numpy --with pillow \
        --with pystac-client python scripts/build_satellite.py

Nothing is invented: if no usable pair exists the JSON says `available: false`
with the reason, and the page shows that instead of a slider.
"""

from __future__ import annotations

import io
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from PIL import Image, ImageDraw, ImageFont
from pystac_client import Client
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window
from rasterio.windows import from_bounds as from_bounds_window

STAC = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"
# Crop: the Beas from the head of Pandoh reservoir, past the dam, down to Mandi town.
WEST, SOUTH, EAST, NORTH = 76.89, 31.61, 77.15, 31.75
WIDTH = 1600  # output pixels across (about 15 m a pixel)
BEFORE = ("2023-06-01", "2023-06-30")  # pre-monsoon, before the flood
AFTER = ("2023-07-10", "2023-09-30")  # the flood peaked on 9-11 July 2023
MAX_CLOUD_PCT = 10.0  # cloud allowed inside the crop for a scene to count as clear
FIRST_LOOK_CLOUD_PCT = 25.0  # cloud allowed for the first look after the flood
FLOOD_PEAK = date(2023, 7, 11)
JPEG_BUDGET = 250_000  # bytes
SCL_CLOUD = (3, 8, 9, 10)  # cloud shadow, cloud medium, cloud high, thin cirrus
SCL_NODATA = (0,)
REFL_MAX = 0.2  # reflectance mapped to white in true colour (same for every date)
GAMMA = 1 / 1.6
RIVER_BLUE = (47, 125, 246)  # --river-grad end stop in theme.css
CLOUD_GREY = (226, 232, 240)
OUT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "satellite" / "2023"
THUMB = Path(__file__).resolve().parents[1] / "docs" / "charts" / "satellite-beas-2023.jpg"
VILLAGES = Path(__file__).resolve().parents[1] / "data" / "villages.json"
# Landmarks that are not villages. Pandoh dam: Bhakra Beas Management Board's
# diversion dam on the Beas: the west end of the reservoir in the 3 June 2023 scene (31.6715 N, 77.0662 E).
LANDMARKS = [
    {"id": "pandoh-dam", "name": "Pandoh dam", "name_hi": "पंडोह बाँध", "lat": 31.6715, "lon": 77.0662, "kind": "dam"},
    {"id": "mandi", "name": "Mandi town", "name_hi": "मंडी शहर", "lat": 31.7087, "lon": 76.9320, "kind": "town"},
]

os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("VSI_CACHE", "FALSE")
os.environ.setdefault("GDAL_CACHEMAX", "1024")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "6")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "900")  # whole transfer; slow links need long
os.environ.setdefault("GDAL_HTTP_LOW_SPEED_TIME", "60")  # but give up on a stalled one
os.environ.setdefault("GDAL_HTTP_LOW_SPEED_LIMIT", "512")
os.environ.setdefault("GDAL_HTTP_CONNECTTIMEOUT", "20")
OVERVIEW: int | None = None  # full resolution; previews may set 0 (20 m)


def grid(width: int) -> tuple[int, int, object]:
    km_x = (EAST - WEST) * 111.32 * math.cos(math.radians((SOUTH + NORTH) / 2))
    km_y = (NORTH - SOUTH) * 110.57
    height = round(width * km_y / km_x)
    return width, height, from_bounds(WEST, SOUTH, EAST, NORTH, width, height)


_cache: dict[tuple[str, int, Resampling, int | None], np.ndarray] = {}
CACHE = Path(os.environ.get("PUKAAR_SAT_CACHE", Path.home() / ".cache" / "pukaar-satellite"))
WORKERS = 1  # GDAL's HTTP reader dropped tiles when several threads read one file at once


def source_window(href: str, overview: int | None) -> tuple[np.ndarray, Affine, CRS]:
    """The crop in the file's own grid, one internal tile per request with retries, cached on disk."""
    box = "_".join(f"{v:.3f}" for v in (WEST, SOUTH, EAST, NORTH))
    tag = href.split("/sentinel-s2-l2a-cogs/")[-1].replace("/", "_") + f".{box}.ov{overview}.npz"
    path = CACHE / tag
    if path.exists():
        z = np.load(path)
        return z["a"], Affine(*z["transform"].tolist()), CRS.from_wkt(str(z["crs"]))
    opts = {} if overview is None else {"overview_level": overview}
    with rasterio.open(href, **opts) as src:
        left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, WEST, SOUTH, EAST, NORTH)
        f = from_bounds_window(left, bottom, right, top, src.transform)
        c0, r0 = math.floor(f.col_off) - 2, math.floor(f.row_off) - 2
        c1, r1 = math.ceil(f.col_off + f.width) + 2, math.ceil(f.row_off + f.height) + 2
        crs, wtransform = src.crs, src.window_transform(Window(c0, r0, c1 - c0, r1 - r0))
        bh, bw = src.block_shapes[0]
    out = np.zeros((r1 - r0, c1 - c0), dtype="uint16")
    # Pieces aligned to the file's internal tiles, so no tile is fetched twice.
    pieces = [
        (max(r, r0), min(r + bh, r1), max(c, c0), min(c + bw, c1))
        for r in range(r0 // bh * bh, r1, bh)
        for c in range(c0 // bw * bw, c1, bw)
    ]

    def fetch(p: tuple[int, int, int, int]) -> None:
        ra, rb, ca, cb = p
        for attempt in range(10):
            try:
                # A fresh query string per attempt sidesteps any failed range GDAL has cached for this URL.
                with rasterio.open(href if attempt == 0 else f"{href}?attempt={attempt}", **opts) as src:
                    win = Window(ca, ra, cb - ca, rb - ra)
                    out[ra - r0 : rb - r0, ca - c0 : cb - c0] = src.read(1, window=win)
                return
            except rasterio.errors.RasterioIOError as e:
                print(f"    retry {attempt + 1} {href.rsplit('/', 1)[-1]} at {ra},{ca}: {str(e.__cause__ or e)[:80]}", file=sys.stderr)
                time.sleep(3 + attempt * 3)
        raise RuntimeError(f"could not read {href} at {ra},{ca}")

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(fetch, pieces))
    CACHE.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, a=out, transform=np.array(tuple(wtransform)[:6]), crs=np.array(crs.to_wkt()))
    return out, wtransform, crs


def read(href: str, width: int, resampling: Resampling, overview: int | None = None) -> np.ndarray:
    """One band resampled onto a lat/lon grid over the crop; only the crop travels."""
    key = (href, width, resampling, overview)
    if key in _cache:
        return _cache[key]
    w, h, transform = grid(width)
    arr, src_transform, src_crs = source_window(href, overview)
    dst = np.zeros((h, w), dtype=arr.dtype)
    reproject(
        arr, dst, src_transform=src_transform, src_crs=src_crs, src_nodata=0,
        dst_transform=transform, dst_crs="EPSG:4326", dst_nodata=0, resampling=resampling,
    )
    _cache[key] = dst
    return dst


def scale_offset(item, key: str) -> tuple[float, float]:
    bands = item.assets[key].extra_fields.get("raster:bands") or [{}]
    offset = float(bands[0].get("offset", 0.0))
    # Earth Search has already removed the processing-baseline-04 BOA offset from these COGs
    # when this flag is set; applying it again gives negative reflectance (checked on 23 July 2023).
    if item.properties.get("earthsearch:boa_offset_applied"):
        offset = 0.0
    return float(bands[0].get("scale", 1e-4)), offset


def reflectance(item, key: str, width: int, resampling=Resampling.bilinear) -> np.ndarray:
    dn = read(item.assets[key].href, width, resampling, OVERVIEW).astype("float32")
    s, o = scale_offset(item, key)
    out = dn * s + o
    out[dn == 0] = np.nan  # 0 is nodata in L2A
    return out


def crop_cloud(item) -> tuple[float, float]:
    """(cloud %, nodata %) inside the crop, from the 20 m scene classification."""
    # A coarse overview (80 m) is plenty for a percentage and spares the download.
    scl = read(item.assets["scl"].href, 300, Resampling.nearest, overview=1)
    n = scl.size
    nodata = float(np.isin(scl, SCL_NODATA).sum()) / n * 100
    valid = n - np.isin(scl, SCL_NODATA).sum()
    cloud = float(np.isin(scl, SCL_CLOUD).sum()) / max(valid, 1) * 100
    return round(cloud, 2), round(nodata, 2)


def inside(x: float, y: float, ring: list) -> bool:
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def covers(geometry: dict) -> bool:
    """True if all four crop corners fall inside the scene footprint (GeoJSON Polygon or MultiPolygon)."""
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    corners = [(WEST, SOUTH), (WEST, NORTH), (EAST, SOUTH), (EAST, NORTH)]
    return all(any(inside(x, y, [tuple(p[:2]) for p in poly[0]]) for poly in polys) for x, y in corners)


def candidates(client: Client, window: tuple[str, str]) -> list[dict]:
    items = client.search(
        collections=[COLLECTION],
        bbox=[WEST, SOUTH, EAST, NORTH],
        datetime=f"{window[0]}/{window[1]}",
        query={"eo:cloud_cover": {"lt": 95}},
        max_items=200,
    ).items()
    out = []
    for it in sorted(items, key=lambda i: i.datetime):
        if not covers(it.geometry):
            continue  # the crop is not wholly inside this tile's data footprint
        cloud, nodata = crop_cloud(it)
        row = {"item": it, "cloud": cloud, "nodata": nodata}
        print(f"  {it.id}  tile cloud {it.properties.get('eo:cloud_cover', 0):6.2f}%  "
              f"crop cloud {cloud:6.2f}%  crop nodata {nodata:5.2f}%", file=sys.stderr)
        out.append(row)
    # One crop must lie wholly inside the tile; a partial tile is not a picture.
    return [c for c in out if c["nodata"] < 0.5]


def true_colour(item) -> tuple[Image.Image, np.ndarray]:
    rgb = np.stack([reflectance(item, k, WIDTH) for k in ("red", "green", "blue")], axis=-1)
    valid = ~np.isnan(rgb).any(axis=-1)
    x = np.clip(np.nan_to_num(rgb) / REFL_MAX, 0, 1) ** GAMMA
    return Image.fromarray((x * 255).round().astype("uint8"), "RGB"), valid


def water(item) -> tuple[Image.Image, dict]:
    green = reflectance(item, "green", WIDTH)
    swir = reflectance(item, "swir16", WIDTH)
    with np.errstate(invalid="ignore", divide="ignore"):
        mndwi = (green - swir) / (green + swir)
    scl = read(item.assets["scl"].href, WIDTH, Resampling.nearest, OVERVIEW)
    cloud = np.isin(scl, SCL_CLOUD)
    is_water = (mndwi > 0.0) & ~cloud & ~np.isnan(mndwi)
    h, w = mndwi.shape
    rgba = np.zeros((h, w, 4), dtype="uint8")
    rgba[cloud] = (*CLOUD_GREY, 150)
    rgba[is_water] = (*RIVER_BLUE, 235)
    px_km2 = ((EAST - WEST) * 111.32 * math.cos(math.radians((SOUTH + NORTH) / 2)) / w) * ((NORTH - SOUTH) * 110.57 / h)
    return Image.fromarray(rgba, "RGBA"), {"water": is_water, "cloud": cloud, "px_km2": px_km2}


def save_jpeg(img: Image.Image, path: Path) -> int:
    for q in (86, 82, 78, 74, 70, 66, 62, 58):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
        if buf.tell() <= JPEG_BUDGET:
            break
    path.write_bytes(buf.getvalue())
    return buf.tell()


def save_png(img: Image.Image, path: Path) -> int:
    # A 4-colour palette (clear, cloud veil, water) keeps the overlay tiny.
    img.quantize(colors=4, method=Image.Quantize.FASTOCTREE).save(path, optimize=True)
    return path.stat().st_size


def markers(w: int, h: int) -> list[dict]:
    villages = json.loads(VILLAGES.read_text(encoding="utf-8"))["villages"]
    pts = LANDMARKS + [
        {"id": v["id"], "name": v["name"], "name_hi": v["name_hi"], "lat": v["lat"], "lon": v["lon"], "kind": "village"}
        for v in villages
    ]
    out = []
    for p in pts:
        if WEST <= p["lon"] <= EAST and SOUTH <= p["lat"] <= NORTH:
            out.append({**p, "x": round((p["lon"] - WEST) / (EAST - WEST), 4), "y": round((NORTH - p["lat"]) / (NORTH - SOUTH), 4)})
    return out




def describe(c: dict, role: str, sizes: dict) -> dict:
    it = c["item"]
    day = it.properties["datetime"][:10]
    out = {
        "role": role,
        "scene_id": it.id,
        "datetime": it.properties["datetime"],
        "date": day,
        "platform": it.properties.get("platform"),
        "tile_cloud_pct": round(float(it.properties.get("eo:cloud_cover", 0)), 2),
        "crop_cloud_pct": c["cloud"],
        "true_colour": f"{day}.jpg",
        "water": f"{day}-water.png",
        "bytes": sizes,
        "stac": f"{STAC}/collections/{COLLECTION}/items/{it.id}",
    }
    if role == "after":
        out["days_after_peak"] = (date.fromisoformat(day) - FLOOD_PEAK).days
    return out


def pick_afters(after_c: list[dict]) -> list[dict]:
    """The first look after the flood (some cloud allowed) and the first clear look, earliest first."""
    first_look = next((c for c in after_c if c["cloud"] <= FIRST_LOOK_CLOUD_PCT), None)
    first_clear = next((c for c in after_c if c["cloud"] <= MAX_CLOUD_PCT), None)
    picks = [c for c in (first_look, first_clear) if c is not None]
    if not picks and after_c:
        picks = [min(after_c, key=lambda c: c["cloud"])]
    unique = {c["item"].id: c for c in picks}
    return sorted(unique.values(), key=lambda c: c["item"].datetime)


def thumbnail(before: Image.Image, after: Image.Image, d0: str, d1: str) -> None:
    """A split-view still for the README: before on the left half, after on the right."""
    w = 900
    h = round(before.height * w / before.width)
    a, b = before.resize((w, h), Image.LANCZOS), after.resize((w, h), Image.LANCZOS)
    out = a.copy()
    out.paste(b.crop((w // 2, 0, w, h)), (w // 2, 0))
    draw = ImageDraw.Draw(out)
    draw.rectangle((w // 2 - 1, 0, w // 2 + 1, h), fill="white")
    font = ImageFont.load_default(size=20)
    for text, x, anchor in ((f"Before: {d0}", 12, "la"), (f"After: {d1}", w - 12, "ra")):
        box = draw.textbbox((x, 12), text, font=font, anchor=anchor)
        draw.rounded_rectangle((box[0] - 8, box[1] - 5, box[2] + 8, box[3] + 5), radius=8, fill=(6, 17, 31))
        draw.text((x, 12), text, fill="white", font=font, anchor=anchor)
    THUMB.parent.mkdir(parents=True, exist_ok=True)
    out.save(THUMB, "JPEG", quality=80, optimize=True, progressive=True)


def unavailable(base: dict, reason: str, considered: dict) -> None:
    (OUT / "scenes.json").write_text(
        json.dumps({**base, "available": False, "reason": reason, "considered": considered}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(reason, file=sys.stderr)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    w, h, _ = grid(WIDTH)
    base = {
        "event": "Beas flood, 9-11 July 2023 (Mandi district, Himachal Pradesh)",
        "flood_peak": FLOOD_PEAK.isoformat(),
        "bounds": [WEST, SOUTH, EAST, NORTH],
        "size": [w, h],
        "pixel_m": round((EAST - WEST) * 111320 * math.cos(math.radians((SOUTH + NORTH) / 2)) / w, 1),
        "source": "Sentinel-2 L2A cloud-optimised GeoTIFFs, AWS Open Data (s3://sentinel-cogs), found via Element 84 Earth Search",
        "licence": "Contains modified Copernicus Sentinel data 2023",
        "licence_url": "https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice",
        "method": {
            "true_colour": f"B04/B03/B02 surface reflectance at 10 m, 0 to {REFL_MAX} stretched with gamma {round(GAMMA, 2)}, the same stretch for every date",
            "water": "MNDWI = (B03 - B11) / (B03 + B11) > 0; B11 is 20 m, resampled bilinear; cloud, cloud shadow and cirrus from the L2A scene classification drawn grey (unknown, not dry)",
            "crop_cloud": "share of the crop classed cloud (medium, high), cloud shadow or thin cirrus in the L2A scene classification layer",
            "selection": (
                f"before: the clearest scene {BEFORE[0]} to {BEFORE[1]} (earliest on a tie); after: the first scene from {AFTER[0]} with at most "
                f"{FIRST_LOOK_CLOUD_PCT}% cloud over the crop (first look) and the first with at most {MAX_CLOUD_PCT}% (first clear look), up to {AFTER[1]}"
            ),
        },
        "markers": markers(w, h),
        "built": date.today().isoformat(),
    }
    client = Client.open(STAC, timeout=(20, 120))
    print("before candidates:", file=sys.stderr)
    before_c = candidates(client, BEFORE)
    print("after candidates:", file=sys.stderr)
    after_c = candidates(client, AFTER)
    considered = {
        role: [{"scene_id": c["item"].id, "tile_cloud_pct": round(float(c["item"].properties.get("eo:cloud_cover", 0)), 2), "crop_cloud_pct": c["cloud"]} for c in cs]
        for role, cs in (("before", before_c), ("after", after_c))
    }
    if not before_c or not after_c:
        return unavailable(base, "no Sentinel-2 L2A scene fully covers the crop in the " + ("before" if not before_c else "after") + " window", considered)
    before = min(before_c, key=lambda c: c["cloud"])
    afters = pick_afters(after_c)
    worst = max([before] + afters, key=lambda c: c["cloud"])
    if worst["cloud"] > 40:
        return unavailable(base, f"monsoon cloud: the clearest usable scene still has {worst['cloud']}% cloud over the crop ({worst['item'].id})", considered)

    scenes = []
    masks = {}
    pictures = {}
    for role, c in [("before", before)] + [("after", a) for a in afters]:
        it = c["item"]
        day = it.properties["datetime"][:10]
        print(f"reading {role}: {it.id}", file=sys.stderr)
        img, _ = true_colour(it)
        size_jpg = save_jpeg(img, OUT / f"{day}.jpg")
        overlay, m = water(it)
        size_png = save_png(overlay, OUT / f"{day}-water.png")
        masks[it.id] = m
        pictures[day] = img
        scenes.append(describe(c, role, {"jpg": size_jpg, "png": size_png}))

    # Water area against the before scene, only where both dates are clear, so cloud cannot pass for dry land.
    b = masks[before["item"].id]
    for s in scenes[1:]:
        a = masks[s["scene_id"]]
        both_clear = ~b["cloud"] & ~a["cloud"]
        s["water_area"] = {
            "compared_km2": round(float(both_clear.sum()) * b["px_km2"], 1),
            "before_km2": round(float((b["water"] & both_clear).sum()) * b["px_km2"], 2),
            "after_km2": round(float((a["water"] & both_clear).sum()) * b["px_km2"], 2),
        }
    first = scenes[1]["date"]
    thumbnail(pictures[scenes[0]["date"]], pictures[first], scenes[0]["date"], first)
    meta = {**base, "available": True, "scenes": scenes, "considered": considered}
    (OUT / "scenes.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(scenes, indent=2))


if __name__ == "__main__":
    main()
