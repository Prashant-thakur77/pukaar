#!/usr/bin/env node
// Downloads the stock footage the demo video uses (video/footage.json) into video/.out/footage/<name>.mp4,
// from each clip's Pexels download link, as a browser on pexels.com would (the site sits behind a bot check). The
// clips are free to use under the Pexels License (https://www.pexels.com/license/). The files are not committed.
//   node video/footage.mjs [--force] [name ...]
// Per clip in footage.json: name, page (Pexels video page URL), use (a note), and optionally
//   from  seconds into the source to start at (default 0)
//   zoom  extra crop-in factor, >= 1 (default 1)
//   y     vertical crop position when zoomed or cropping to 16:9, 0 = top .. 1 = bottom (default 0.5)
// Output: 1920x1080, 30 fps, H.264, no audio, at most 20 s; plus <name>.url with the resolved download URL.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const ROOT = "/home/prashant/projects/Pukaar";
const { chromium } = await import(join(ROOT, "frontend/node_modules/playwright/index.mjs"));
const CHROME = "/home/prashant/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome";
const clips = JSON.parse(readFileSync(join(ROOT, "video/footage.json"), "utf8")).clips;
const OUT = join(ROOT, "video/.out/footage");
mkdirSync(OUT, { recursive: true });
const args = process.argv.slice(2);
const force = args.includes("--force");
const only = new Set(args.filter((a) => !a.startsWith("--")));

const browser = await chromium.launch({
  executablePath: CHROME,
  args: ["--disable-blink-features=AutomationControlled"],
});
const ctx = await browser.newContext({
  userAgent:
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
  locale: "en-US",
  acceptDownloads: true,
});
await ctx.addInitScript(() => Object.defineProperty(navigator, "webdriver", { get: () => undefined }));
const page = await ctx.newPage();
for (const c of clips) {
  if (only.size && !only.has(c.name)) continue;
  const dest = join(OUT, `${c.name}.mp4`);
  if (existsSync(dest) && !force) continue;
  const id = c.page.match(/-(\d+)\/?$/)[1];
  const raw = `${dest}.src`;
  // the bot check or the CDN drops a download now and then: try each clip up to three times
  let dl;
  for (let attempt = 1; ; attempt++) {
    try {
      await page.goto(c.page, { waitUntil: "domcontentloaded" });
      for (let i = 0; i < 10 && /moment/i.test(await page.title()); i++) await page.waitForTimeout(2500);
      [dl] = await Promise.all([
        page.waitForEvent("download", { timeout: 120_000 }),
        page.evaluate((u) => {
          const a = document.createElement("a");
          a.href = u;
          document.body.appendChild(a);
          a.click();
        }, `https://www.pexels.com/download/video/${id}/`),
      ]);
      await dl.saveAs(raw);
      break;
    } catch (e) {
      if (attempt >= 3) throw e;
      console.log(`footage: ${c.name}: attempt ${attempt} failed (${e.message.split("\n")[0]}), retrying`);
    }
  }
  // 1080p, 30 fps, H.264, no audio: what the segment builder expects
  const zoom = Math.max(1, c.zoom ?? 1);
  const y = Math.min(1, Math.max(0, c.y ?? 0.5));
  const vf = [
    `scale=${Math.round(1920 * zoom)}:${Math.round(1080 * zoom)}:force_original_aspect_ratio=increase`,
    `crop=1920:1080:(iw-1920)/2:(ih-1080)*${y}`,
    "fps=30",
  ].join(",");
  const r = spawnSync("ffmpeg", [
    "-v", "error", "-y",
    ...(c.from ? ["-ss", String(c.from)] : []),
    "-i", raw,
    "-t", "20",
    "-vf", vf,
    "-an",
    "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
    dest,
  ]);
  if (r.status !== 0) throw new Error(`ffmpeg ${c.name}: ${r.stderr}`);
  spawnSync("rm", ["-f", raw]);
  console.log(`footage: ${c.name} <- ${c.page} (${dl.url().split("?")[0]})`);
  writeFileSync(join(OUT, `${c.name}.url`), dl.url() + "\n");
}
await browser.close();
