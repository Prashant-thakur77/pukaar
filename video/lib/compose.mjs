// The pitch video's compositor driver (video/pitch.mjs, video/pitch.html):
//   1. captures   real pages of the live site, as timed screenshots (video/.out/pitch/captures/<id>/), reused unless
//                 --only names the scene
//   2. layers     every scene's layers on the global clock, captions, chapters
//   3. frames     video/pitch.html renders each frame (a pure function of t); several pages in parallel pipe JPEGs to ffmpeg
//   4. sound      narration + the real Polly MP3 + sound effects (narration/sfx.py) + the score (narration/score.py),
//                 mixed by narration/mix.py to -14 LUFS
//   5. outputs    docs/media/pukaar-pitch.mp4, .srt, -poster.jpg, -credits.md
import { spawn, spawnSync, execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { existsSync, mkdirSync, readFileSync, writeFileSync, createReadStream, statSync, rmSync } from "node:fs";
import { extname, join } from "node:path";
import { ROOT, CHROME, chromium, log, srt, wrap2, ff, mb } from "./engine.mjs";

const PY = process.env.PYTHON ?? `${process.env.HOME}/.pyenv/versions/3.10.13/bin/python3`;
const OUT = join(ROOT, "video/.out/pitch");
const FPS = 30;

function serve() {
  const types = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".jpg": "image/jpeg", ".png": "image/png", ".woff2": "font/woff2", ".json": "application/json", ".svg": "image/svg+xml" };
  const srv = createServer((req, res) => {
    const p = join(ROOT, decodeURIComponent(new URL(req.url, "http://x").pathname));
    if (!p.startsWith(ROOT) || !existsSync(p) || statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "content-type": types[extname(p)] ?? "application/octet-stream", "cache-control": "max-age=3600" });
    createReadStream(p).pipe(res);
  });
  return new Promise((r) => srv.listen(0, "127.0.0.1", () => r(srv)));
}

// ------------------------------------------------------------------------------------------ captures
async function capture(browser, id, spec, env) {
  const dir = join(OUT, "captures", id);
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  const vw = spec.vw ?? 1600, vh = spec.vh ?? 900, dsf = spec.dsf ?? 1.5;
  const ctx = await browser.newContext({ viewport: { width: vw, height: vh }, deviceScaleFactor: dsf, colorScheme: "light", timezoneId: "Asia/Kolkata" });
  await ctx.addInitScript(() => { try { localStorage.setItem("pukaar.lang", "en"); } catch {} });
  if (!spec.allowOsm) await ctx.route(/tile\.openstreetmap\.org/, (r) => r.abort());
  const page = await ctx.newPage();
  const frames = [];
  const marks = {};
  const shot = async (t) => {
    const f = `${String(frames.length).padStart(3, "0")}.jpg`;
    await page.screenshot({ path: join(dir, f), type: "jpeg", quality: 90 });
    frames.push([t, f]);
  };
  const mark = async (name, loc) => {
    const r = await loc.first().boundingBox().catch(() => null);
    if (r) marks[name] = [r.x, r.y, r.width, r.height];
  };
  await spec.run({ page, shot, mark, env, url: env.facts.liveUrl, sleep: (ms) => page.waitForTimeout(ms) });
  await ctx.close();
  const u = new URL(env.facts.liveUrl + (spec.path ?? "/"));
  const meta = { vw, vh, dsf, frames, marks, host: u.host, path: spec.path ?? "/" };
  writeFileSync(join(dir, "meta.json"), JSON.stringify(meta, null, 1));
  log(`  capture ${id}: ${frames.length} frames`);
  return meta;
}

// ------------------------------------------------------------------------------------------ render
async function renderRange(browser, base, data, a, b, out) {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  await ctx.addInitScript((d) => (window.__DATA = d), data);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => log(`  page error: ${e.message.slice(0, 200)}`));
  await page.goto(`${base}/video/pitch.html`);
  await page.waitForFunction(() => window.__init && window.__render, null, { timeout: 60_000 });
  await page.evaluate(() => window.__init());
  const cdp = await ctx.newCDPSession(page);
  const enc = spawn("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "mjpeg", "-i", "-",
    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", String(FPS), out], { stdio: ["pipe", "inherit", "inherit"] });
  for (let i = a; i < b; i++) {
    await page.evaluate((t) => window.__render(t), i / FPS);
    const { data: jpg } = await cdp.send("Page.captureScreenshot", { format: "jpeg", quality: 92 });
    if (!enc.stdin.write(Buffer.from(jpg, "base64"))) await new Promise((r) => enc.stdin.once("drain", r));
    if ((i - a) % 600 === 0) log(`    frames ${i}/${b}`);
  }
  enc.stdin.end();
  await new Promise((r) => enc.on("close", r));
  await ctx.close();
}

// ------------------------------------------------------------------------------------------ the whole job
export async function compose({ browser, scenes, tls, facts, live, work, media, only, words, total }) {
  const def = await import("../pitch.mjs");
  const scenesMod = await import("../pitch-scenes.mjs");
  mkdirSync(join(OUT, "captures"), { recursive: true });
  const env = { facts, live };

  // 1. captures (a fresh browser with GPU for the 3D pages)
  const capBrowser = await chromium.launch({ executablePath: CHROME, args: ["--use-angle=vulkan", "--enable-gpu", "--ignore-gpu-blocklist"] });
  const captures = {};
  for (const [id, spec] of Object.entries(scenesMod.CAPTURES)) {
    const metaPath = join(OUT, "captures", id, "meta.json");
    const want = !existsSync(metaPath) || (only && only.has(id));
    let meta = null;
    if (want) {
      for (let k = 0; k < 3 && !meta; k++) {
        try { meta = await capture(capBrowser, id, spec, env); } catch (e) { log(`  capture ${id} failed: ${e.message.split("\n")[0]}`); }
      }
      if (!meta) throw new Error(`capture ${id} failed`);
    } else meta = JSON.parse(readFileSync(metaPath, "utf8"));
    captures[id] = meta;
  }
  await capBrowser.close();
  env.captures = captures;
  // the live CAP 1.2 feed, as the terminal shows it (lightly coloured XML)
  const xml = execFileSync("curl", ["-s", "-m", "20", `${facts.apiUrl}/cap/alerts.atom`], { encoding: "utf8" });
  const e = (x) => x.replace(/&/g, "&amp;").replace(/</g, "&lt;");
  env.cap = xml.split("\n").filter((l) => l.trim()).map((l) => e(l.replace(/\s+$/, "").slice(0, 110))
    .replace(/(&lt;\/?)([\w:]+)/g, '$1<span class="k">$2</span>').replace(/(&gt;)([^&<]+)(&lt;)/g, '$1<span class="v">$2</span>$3'));

  // 2. layers on the global clock
  const all = [];
  const sfx = [];
  const flashes = [];
  scenes.forEach((s, i) => {
    const tl = tls[i];
    const at = (li, dt = 0) => tl.lines[li].start + dt;
    const ch = (li, k, dt = 0) => tl.lines[li].chunks[k].start + dt;
    const end = (li, dt = 0) => tl.lines[li].end + dt;
    const ctx = { tl, dur: tl.dur, at, ch, end, f: facts, live, captures, env };
    const spec = scenesMod.layersFor(s.id, ctx);
    for (const L of spec.layers ?? []) all.push({ ...L, from: tl.start + (L.from ?? 0), to: tl.start + (L.to ?? tl.dur) });
    for (const x of spec.sfx ?? []) sfx.push({ ...x, t: tl.start + x.t });
    for (const x of spec.flashes ?? []) flashes.push({ ...x, t: tl.start + x.t });
  });
  const captions = [];
  let key = 0;
  tls.forEach((tl, i) => {
    const chunks = tl.lines.flatMap((l) => l.chunks.map((c, k) => ({ ...c, end: k + 1 < l.chunks.length ? null : l.end })));
    chunks.forEach((c, k) => {
      const from = tl.start + c.start - 0.08;
      const next = chunks[k + 1];
      const to = next ? Math.min(tl.start + next.start - 0.1, tl.start + (c.end ?? next.start) + 0.6) : tl.start + Math.min(tl.dur, (c.end ?? tl.dur) + 0.7);
      captions.push({ from, to: Math.max(to, from + 0.5), text: c.text, lines: wrap2(c.text), key: key++ });
    });
  });
  // a caption holds until the next one when the gap is short, so it never blinks out between chunks
  for (let k = 0; k + 1 < captions.length; k++) {
    const gap = captions[k + 1].from - captions[k].to;
    captions[k].to = gap < 1.2 ? captions[k + 1].from - 0.02 : Math.min(captions[k].to, captions[k + 1].from - 0.02);
  }
  const chapters = [];
  let n = 0;
  scenes.forEach((s, i) => { if (s.chapter) chapters.push({ from: tls[i].start, label: s.chapter, n: ++n }); });
  const T = tls.reduce((a, t) => a + t.dur, 0);
  const startOf = (id) => tls[scenes.findIndex((s) => s.id === id)].start;
  const data = {
    total: T,
    layers: all,
    captions,
    chapters,
    chrome: [[startOf("scale"), startOf("close")]],
    lightRanges: scenesMod.lightRanges?.(startOf) ?? [],
    flashes,
    media: JSON.parse(readFileSync(join(OUT, "media.json"), "utf8")),
    captures,
  };
  writeFileSync(join(work, "compose-data.json"), JSON.stringify(data));

  // 3. frames, in parallel (PITCH_STILLS=t1,t2 renders only those times to stills, for checking)
  const srv = await serve();
  if (process.env.PITCH_STILLS) {
    const sb = await chromium.launch({ executablePath: CHROME, args: ["--use-angle=vulkan", "--enable-gpu", "--ignore-gpu-blocklist"] });
    const ctx = await sb.newContext({ viewport: { width: 1920, height: 1080 } });
    await ctx.addInitScript((d) => (window.__DATA = d), data);
    const page = await ctx.newPage();
    page.on("pageerror", (e) => log(`  page error: ${e.message.slice(0, 300)}`));
    await page.goto(`http://127.0.0.1:${srv.address().port}/video/pitch.html`);
    await page.waitForFunction(() => window.__init && window.__render, null, { timeout: 60_000 });
    await page.evaluate(() => window.__init());
    for (const t of process.env.PITCH_STILLS.split(",").map(Number)) {
      await page.evaluate((x) => window.__render(x), t);
      await page.screenshot({ path: join(work, `still-${t.toFixed(1)}.jpg`), type: "jpeg", quality: 80 });
    }
    await sb.close();
    srv.close();
    return log("stills written");
  }
  const base = `http://127.0.0.1:${srv.address().port}`;
  let picture = join(work, "picture.mp4");
  if (process.env.PITCH_AUDIO_ONLY) { srv.close(); } else {
  const rb = await chromium.launch({ executablePath: CHROME, args: ["--use-angle=vulkan", "--enable-gpu", "--ignore-gpu-blocklist", "--disable-web-security"] });
  const N = Math.ceil(T * FPS);
  const P = Number(process.env.PITCH_WORKERS ?? 3);
  const parts = [];
  const jobs = [];
  for (let k = 0; k < P; k++) {
    const a = Math.floor((N * k) / P), b = Math.floor((N * (k + 1)) / P);
    const out = join(work, `part-${k}.mp4`);
    parts.push(out);
    jobs.push(renderRange(rb, base, data, a, b, out));
  }
  log(`render ${N} frames with ${P} workers`);
  const t0 = Date.now();
  await Promise.all(jobs);
  log(`  rendered in ${((Date.now() - t0) / 1000).toFixed(0)} s`);
  await rb.close();
  srv.close();
  writeFileSync(join(work, "parts.txt"), parts.map((p) => `file '${p}'`).join("\n"));
  ff(["-f", "concat", "-safe", "0", "-i", join(work, "parts.txt"), "-c", "copy", picture]);
  }

  // 4. sound
  const sfxDir = join(OUT, "sfx");
  if (!existsSync(join(sfxDir, "rain.wav"))) execFileSync(PY, [join(ROOT, "video/narration/sfx.py"), sfxDir], { stdio: "inherit" });
  const cues = { duration: T, ...scenesMod.score(startOf, T, tls, scenes) };
  const bed = join(work, "score.wav");
  writeFileSync(join(work, "score-cues.json"), JSON.stringify(cues, null, 1));
  execFileSync(PY, [join(ROOT, "video/narration/score.py"), join(work, "score-cues.json"), bed], { stdio: "inherit" });
  const plan = { duration: T, clips: [], sfx: [], target_lufs: -14, music: { path: bed, speech_lufs: -29, gap_db: 6, fade_in: 0.5, fade_out: 3 } };
  for (const tl of tls) for (const l of tl.lines) plan.clips.push({ path: l.take.path, t: tl.start + l.start });
  const vi = scenes.findIndex((s) => s.id === "voice");
  const pollyAt = tls[vi].start + tls[vi].lines[0].end + 0.35;
  // the real Polly alert: in the clear for the voice scene, then ducked under the Telegram narration, then out
  const clear = tls[vi].start + tls[vi].dur - pollyAt;
  plan.clips.push({ path: live.voice, t: pollyAt, gain_db: -1, env: [[0, 0], [clear - 0.2, 0], [clear + 0.3, -15], [live.voiceDur, -15]] });
  for (const x of sfx) plan.sfx.push({ path: join(sfxDir, `${x.name}.wav`), t: x.t, gain_db: x.gain ?? -12, dur: x.dur ?? null, fade: x.fade ?? null });
  writeFileSync(join(work, "mix-plan.json"), JSON.stringify(plan, null, 1));
  const wav = join(work, "mix.wav");
  const r = spawnSync(PY, [join(ROOT, "video/narration/mix.py"), join(work, "mix-plan.json"), wav], { encoding: "utf8" });
  if (r.status !== 0) throw new Error(`mix.py failed\n${r.stderr}`);
  log(`  ${r.stdout.trim()}`);

  if (process.env.PITCH_AUDIO_ONLY) return log(`audio only: ${wav}`);
  // 5. outputs
  const mp4 = join(media, "pukaar-pitch.mp4");
  ff(["-i", picture, "-i", wav, "-map", "0:v", "-map", "1:a", "-af", "alimiter=limit=0.82:attack=5:release=60:level=disabled",
    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-shortest", "-movflags", "+faststart", mp4]);
  writeFileSync(join(media, "pukaar-pitch.srt"), srt(tls).text);
  ff(["-ss", String(scenesMod.posterAt(startOf)), "-i", picture, "-frames:v", "1", "-q:v", "2", join(media, "pukaar-pitch-poster.jpg")]);
  writeFileSync(join(media, "pukaar-pitch-credits.md"), scenesMod.creditsMd({ facts, chapters, T }));
  log(`pukaar-pitch.mp4 ${mb(mp4)}, ${T.toFixed(1)} s, ${words} words`);
}
