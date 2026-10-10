"""Bake the landing-page heightmap from real elevation data.

Downloads Terrarium tiles (Mapzen Terrain Tiles, AWS Open Data:
https://registry.opendata.aws/terrain-tiles/) around Mandi town on the Beas,
decodes metres, and writes a small little-endian uint16 grid plus metadata for
the 3D hero. Run once; the output is committed so the page makes no tile
requests:

    uv run --with httpx --with pillow python scripts/build_hero_dem.py
"""

from __future__ import annotations

import io
import json
import math
import struct
from pathlib import Path

import httpx
from PIL import Image

TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
CENTER = (31.708, 76.932)  # Mandi town, Beas river
ZOOM = 11
SPAN = 3  # tiles per side
SIZE = 192  # output grid per side
OUT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "hero"


def tile_xy(lat: float, lon: float, z: int) -> tuple[int, int]:
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def tile_bounds(x: int, y: int, z: int) -> tuple[float, float, float, float]:
    n = 2**z
    west = x / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return west, south, (x + 1) / n * 360.0 - 180.0, north


def main() -> None:
    cx, cy = tile_xy(*CENTER, ZOOM)
    x0, y0 = cx - SPAN // 2, cy - SPAN // 2
    mosaic = Image.new("RGB", (256 * SPAN, 256 * SPAN))
    with httpx.Client(timeout=30) as client:
        for dy in range(SPAN):
            for dx in range(SPAN):
                resp = client.get(TILE_URL.format(z=ZOOM, x=x0 + dx, y=y0 + dy))
                resp.raise_for_status()
                mosaic.paste(Image.open(io.BytesIO(resp.content)).convert("RGB"), (256 * dx, 256 * dy))

    px = mosaic.load()
    width = mosaic.size[0]
    metres = [[0.0] * width for _ in range(width)]
    for j in range(width):
        for i in range(width):
            r, g, b = px[i, j]
            metres[j][i] = r * 256 + g + b / 256 - 32768

    # Box-average down to SIZE x SIZE.
    step = width / SIZE
    grid: list[int] = []
    for j in range(SIZE):
        for i in range(SIZE):
            ys = range(int(j * step), int((j + 1) * step))
            xs = range(int(i * step), int((i + 1) * step))
            vals = [metres[y][x] for y in ys for x in xs]
            grid.append(max(0, round(sum(vals) / len(vals))))

    west, _, _, north = tile_bounds(x0, y0, ZOOM)
    _, south, east, _ = tile_bounds(x0 + SPAN - 1, y0 + SPAN - 1, ZOOM)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "mandi-dem.bin").write_bytes(struct.pack(f"<{len(grid)}H", *grid))
    meta = {
        "size": SIZE,
        "min_m": min(grid),
        "max_m": max(grid),
        "bbox": [round(west, 5), round(south, 5), round(east, 5), round(north, 5)],
        "width_km": round((east - west) * 111.32 * math.cos(math.radians(CENTER[0])), 2),
        "source": "Mapzen Terrain Tiles on AWS Open Data (terrarium, z11)",
        "attribution": "https://github.com/tilezen/joerd/blob/master/docs/attribution.md",
    }
    (OUT / "mandi-dem.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
