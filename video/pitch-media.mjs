#!/usr/bin/env node
// Prepares the pitch video's media (video/pitch-media.json) into video/.out/pitch/:
//   stills -> media/<name>.jpg (EXIF-rotated, at most 2880 px wide, optional auto-contrast for hazy shots)
//   clips  -> frames/<name>/00001.jpg ... (the chosen window, 1920x1080 at 30 fps, so the compositor can step them)
// Sources are looked up in --src <dir> (or $PUKAAR_MEDIA_SRC), then video/.out/footage/ for "@footage/..." items,
// then downloaded from the item's direct url; Sentinel-2 crops are rebuilt with video/sat_crop.py if missing.
//   node video/pitch-media.mjs [--src dir] [--force]
import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { ROOT, log } from "./lib/engine.mjs";

const arg = (k) => {
  const i = process.argv.indexOf(k);
  return i > 0 ? process.argv[i + 1] : null;
};
const SRC = arg("--src") ?? process.env.PUKAAR_MEDIA_SRC ?? null;
const FORCE = process.argv.includes("--force");
const OUT = join(ROOT, "video/.out/pitch");
const DL = join(OUT, "src");
const PY = process.env.PYTHON ?? `${process.env.HOME}/.pyenv/versions/3.10.13/bin/python3`;
for (const d of ["media", "frames", "src"]) mkdirSync(join(OUT, d), { recursive: true });

const items = JSON.parse(readFileSync(join(ROOT, "video/pitch-media.json"), "utf8")).items;

function source(it) {
  if (it.src.startsWith("@footage/")) {
    const p = join(ROOT, "video/.out/footage", it.src.slice(9));
    if (!existsSync(p)) throw new Error(`${p} missing: run node video/footage.mjs`);
    return p;
  }
  for (const dir of [SRC, DL].filter(Boolean)) if (existsSync(join(dir, it.src))) return join(dir, it.src);
  const out = join(DL, it.src);
  if (it.s2) {
    log(`  ${it.name}: Sentinel-2 crop ${it.s2.scene}`);
    execFileSync("uv", ["run", "--with", "rasterio", "--with", "numpy", "--with", "pillow", "--with", "pystac-client",
      "python", join(ROOT, "video/sat_crop.py"), "get", ...it.s2.bbox.map(String), it.s2.scene, out],
    { stdio: "inherit", env: { ...process.env, AWS_NO_SIGN_REQUEST: "YES" } });
    return out;
  }
  log(`  ${it.name}: downloading ${it.url}`);
  execFileSync("curl", ["-sSfL", "-A", "Mozilla/5.0 (pukaar video prep)", "-o", out, it.url], { stdio: "inherit" });
  return out;
}

const PIL = `
import sys, json
from PIL import Image, ImageOps
src, out, opts = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
if opts.get("crop"):
    x0, y0, x1, y1 = opts["crop"]; w, h = im.size
    im = im.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
if opts.get("autocontrast"):
    im = ImageOps.autocontrast(im, cutoff=0.6)
if im.width > 2880:
    im = im.resize((2880, round(im.height * 2880 / im.width)), Image.LANCZOS)
im.save(out, quality=92)
print(im.size[0], im.size[1])
`;

const meta = {};
for (const it of items) {
  const src = source(it);
  if (it.type === "still") {
    const out = join(OUT, "media", `${it.name}.jpg`);
    const r = spawnSync(PY, ["-c", PIL, src, out, JSON.stringify({ crop: it.crop, autocontrast: it.autocontrast })], {
      encoding: "utf8",
    });
    if (r.status !== 0) throw new Error(r.stderr);
    const [w, h] = r.stdout.trim().split(" ").map(Number);
    meta[it.name] = { type: "still", w, h };
    log(`  still ${it.name} ${w}x${h}`);
    continue;
  }
  const dir = join(OUT, "frames", it.name);
  const n0 = existsSync(dir) ? readdirSync(dir).filter((f) => f.endsWith(".jpg")).length : 0;
  if (n0 > 0 && !FORCE) {
    meta[it.name] = { type: "clip", frames: n0 };
    continue;
  }
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  // cover 1920x1080 (a zoom crops further, y picks the band), slowed if asked, 30 fps
  const z = it.zoom ?? 1;
  const W2 = Math.round((1920 * z) / 2) * 2,
    H2 = Math.round((1080 * z) / 2) * 2;
  const vf = [
    it.slow ? `setpts=${it.slow}*PTS` : null,
    `scale=${W2}:${H2}:force_original_aspect_ratio=increase:flags=lanczos`,
    `crop=${W2}:${H2}`,
    `crop=1920:1080:(iw-1920)/2:(ih-1080)*${it.y ?? 0.5}`,
    "fps=30",
  ].filter(Boolean);
  execFileSync("ffmpeg", ["-v", "error", "-y", "-ss", String(it.from ?? 0), "-t", String(it.dur), "-i", src,
    "-vf", vf.join(","), "-q:v", "3", join(dir, "%05d.jpg")]);
  const n = readdirSync(dir).filter((f) => f.endsWith(".jpg")).length;
  meta[it.name] = { type: "clip", frames: n };
  log(`  clip ${it.name}: ${n} frames`);
}
writeFileSync(join(OUT, "media.json"), JSON.stringify(meta, null, 1));
log(`media ready in video/.out/pitch (${Object.keys(meta).length} items)`);
