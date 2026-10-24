// The hardware explainer: a narrated 3D film of how Pukaar's devices and the warning loop will work at Pandoh.
//
//   node video/hardware/render.mjs                 narrate, render, mix, write the outputs and the stills
//   node video/hardware/render.mjs --preview 3,40  only those seconds, as JPEGs in the work dir (for checking)
//   node video/hardware/render.mjs --stills        only the stills (PNG) and stills.md
//   node video/hardware/render.mjs --plan          only the narration and the timeline
//   node video/hardware/render.mjs --audio         only the sound mix (mix.wav in the work dir)
//
// Same approach as the pitch compositor (video/lib/compose.mjs): narration first (Amazon Polly, neural Kajal, cached
// with word marks so captions change on the spoken word), scene lengths from the audio, then video/hardware/scene.html
// renders every frame as a pure function of t and headless Chromium screenshots it into ffmpeg. Nothing depends on
// GPU speed. Work files live in ~/.cache/pukaar-video/hardware (never /tmp, which is RAM); frames are piped, never
// written to disk. Outputs go to ~/Downloads (HW_OUT to change). Env: HW_CHROME, HW_GL=swiftshader, HW_WORKERS.
import { spawn, spawnSync, execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { existsSync, mkdirSync, readFileSync, writeFileSync, createReadStream, statSync, rmSync } from "node:fs";
import { dirname, extname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { SCENES, STILLS, VOICE } from "./story.mjs";

const HOME = process.env.HOME;
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const WORK = process.env.HW_WORK ?? join(HOME, ".cache/pukaar-video/hardware");
const OUTDIR = process.env.HW_OUT ?? join(HOME, "Downloads");
const STILLDIR = join(OUTDIR, "pukaar-hardware-stills");
const PY = process.env.PYTHON ?? `${HOME}/.pyenv/versions/3.10.13/bin/python3`;
const CHROME = process.env.HW_CHROME ?? `${HOME}/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome`;
const FPS = 30;
const W = 1920, H = 1080;
const log = (...a) => console.log("[hardware]", ...a);

// frontend/node_modules: in this checkout, or in the main checkout when this is a git worktree
function nodeModules() {
  const here = join(ROOT, "frontend/node_modules");
  if (existsSync(join(here, "three"))) return here;
  const common = execFileSync("git", ["-C", ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir"], { encoding: "utf8" }).trim();
  const main = join(dirname(common), "frontend/node_modules");
  if (existsSync(join(main, "three"))) return main;
  throw new Error("frontend/node_modules not found: run npm ci in frontend/");
}
const NM = nodeModules();
const { chromium } = createRequire(join(NM, "..", "package.json"))("playwright");

const ff = (args) => {
  const r = spawnSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", ...args], { encoding: "utf8", maxBuffer: 64 << 20 });
  if (r.status !== 0) throw new Error(`ffmpeg ${args.join(" ")}\n${r.stderr}`);
};
const duration = (p) => Number(execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p], { encoding: "utf8" }).trim());
const mb = (p) => `${(statSync(p).size / 1e6).toFixed(1)} MB`;

// ------------------------------------------------------------------------------------------ narration (Polly)
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const parts = (s) => s.split("|").map((x) => x.trim().replace(/\s+/g, " "));

/** One line: mp3 and word marks from Polly (cached by the SSML), a 24 kHz wav for the mix, and each chunk's start. */
function synth(line) {
  const hi = line.lang === "hi";
  const say = parts(line.say ?? line.text);
  const shown = parts(line.text);
  if (say.length !== shown.length) throw new Error(`"|" count differs between text and say: ${line.text}`);
  const pre = `<speak><prosody rate="${hi ? VOICE.hiRate : VOICE.enRate}">`;
  const body = say.map(esc).join(" ");
  const ssml = `${pre}${body}</prosody></speak>`;
  // byte offset of each chunk in the SSML (Polly's marks count UTF-8 bytes)
  const offs = [];
  let acc = Buffer.byteLength(pre);
  for (const p of say) { offs.push(acc); acc += Buffer.byteLength(esc(p)) + 1; }
  const lang = hi ? "hi-IN" : "en-IN";
  const key = createHash("sha1").update(JSON.stringify([VOICE, lang, ssml])).digest("hex").slice(0, 16);
  const dir = join(WORK, "tts");
  mkdirSync(dir, { recursive: true });
  const mp3 = join(dir, `${key}.mp3`), marks = join(dir, `${key}.marks`), wav = join(dir, `${key}.wav`);
  const base = ["polly", "synthesize-speech", "--engine", VOICE.engine, "--voice-id", VOICE.id, "--language-code", lang, "--text-type", "ssml", "--text", ssml];
  if (!existsSync(mp3)) execFileSync("aws", [...base, "--output-format", "mp3", "--sample-rate", "24000", mp3], { stdio: "ignore" });
  if (!existsSync(marks)) execFileSync("aws", [...base, "--output-format", "json", marks, "--speech-mark-types", "word"], { stdio: "ignore" });
  if (!existsSync(wav)) ff(["-i", mp3, "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", wav]);
  const words = readFileSync(marks, "utf8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l));
  const dur = duration(wav);
  const starts = offs.map((o, k) => {
    if (k === 0) return 0;
    const w = words.find((x) => x.start >= o - 1);
    return w ? w.time / 1000 : (k / say.length) * dur;
  });
  return { path: wav, dur, chunks: shown.map((text, k) => ({ text, start: starts[k] })), words };
}

function timeline() {
  let t0 = 0;
  const gapAfter = { "?": 0.7, ".": 0.55, ":": 0.45, ",": 0.4, "।": 0.6, "”": 0.55 };
  return SCENES.map((s) => {
    let t = s.lead ?? 0.5;
    const lines = s.lines.map((l, i) => {
      if (i > 0) t += s.gap ?? gapAfter[s.lines[i - 1].text.trim().slice(-1)] ?? 0.5;
      t += l.pre ?? 0;
      const take = synth(l);
      const start = t;
      t += take.dur;
      return { start, end: t, text: l.text, lang: l.lang ?? "en", path: take.path, chunks: take.chunks.map((c) => ({ text: c.text, start: start + c.start })) };
    });
    const dur = Math.max(s.minDur ?? 0, t + (s.tail ?? 0.6));
    const out = { id: s.id, chapter: s.chapter ?? null, n: s.n ?? null, start: t0, dur, lines };
    t0 += dur;
    return out;
  });
}

/** Caption cues on the global clock: each chunk until the next one, or until shortly after its line ends. */
function captions(tls) {
  const cues = [];
  for (const s of tls)
    for (const l of s.lines)
      l.chunks.forEach((c, k) => {
        const next = l.chunks[k + 1];
        cues.push({ from: s.start + c.start - 0.06, to: s.start + (next ? next.start - 0.04 : l.end + 0.7), text: c.text, hi: l.lang === "hi" });
      });
  for (let k = 0; k + 1 < cues.length; k++) {
    const gap = cues[k + 1].from - cues[k].to;
    cues[k].to = gap < 1.0 ? cues[k + 1].from - 0.02 : Math.min(cues[k].to, cues[k + 1].from - 0.02);
  }
  return cues;
}

function srtText(cues) {
  const ts = (s) => {
    const ms = Math.max(0, Math.round(s * 1000));
    const p = (n, w = 2) => String(n).padStart(w, "0");
    return `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)},${p(ms % 1000, 3)}`;
  };
  return cues.map((c, i) => `${i + 1}\n${ts(c.from)} --> ${ts(c.to)}\n${c.text}\n`).join("\n");
}

// ------------------------------------------------------------------------------------------ the page
function serve() {
  const types = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json", ".woff2": "font/woff2" };
  const threeDir = join(NM, "three");
  const srv = createServer((req, res) => {
    const u = decodeURIComponent(new URL(req.url, "http://x").pathname);
    const p = u.startsWith("/three/") ? join(threeDir, u.slice(7)) : join(ROOT, u);
    const okRoot = p.startsWith(ROOT) || p.startsWith(threeDir);
    if (!okRoot || !existsSync(p) || statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "content-type": types[extname(p)] ?? "application/octet-stream" });
    createReadStream(p).pipe(res);
  });
  return new Promise((r) => srv.listen(0, "127.0.0.1", () => r(srv)));
}

const glArgs = () =>
  process.env.HW_GL === "swiftshader"
    ? ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
    : ["--use-angle=vulkan", "--enable-gpu", "--ignore-gpu-blocklist"];

async function openPage(browser, base, data) {
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  await ctx.addInitScript((d) => (window.__DATA = d), data);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => log(`page error: ${e.message.slice(0, 300)}`));
  page.on("console", (m) => { if (m.type() === "error") log(`console: ${m.text().slice(0, 300)}`); });
  await page.goto(`${base}/video/hardware/scene.html`);
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 120_000 });
  await page.evaluate(() => document.fonts.ready);
  const cdp = await ctx.newCDPSession(page);
  return { ctx, page, cdp };
}

async function renderRange(browser, base, data, a, b, out) {
  const { ctx, page, cdp } = await openPage(browser, base, data);
  const enc = spawn("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "mjpeg", "-i", "-",
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "15", "-pix_fmt", "yuv420p", "-r", String(FPS), out], { stdio: ["pipe", "inherit", "inherit"] });
  const t0 = Date.now();
  for (let i = a; i < b; i++) {
    await page.evaluate((t) => window.__render(t), i / FPS);
    const { data: jpg } = await cdp.send("Page.captureScreenshot", { format: "jpeg", quality: 94 });
    if (!enc.stdin.write(Buffer.from(jpg, "base64"))) await new Promise((r) => enc.stdin.once("drain", r));
    if ((i - a) % 450 === 0) log(`  ${out.split("/").pop()}: frame ${i - a}/${b - a} (${((Date.now() - t0) / 1000).toFixed(0)} s)`);
  }
  enc.stdin.end();
  await new Promise((r) => enc.on("close", r));
  await ctx.close();
}

function stillTime(tls, sceneId, where) {
  const s = tls.find((x) => x.id === sceneId);
  if (!s) throw new Error(`no scene ${sceneId}`);
  let t;
  const m = /^L(\d+)\+([\d.]+)$/.exec(where);
  if (m) t = s.lines[Number(m[1])].start + Number(m[2]);
  else if (where.startsWith("end-")) t = s.dur - Number(where.slice(4));
  else t = Number(where);
  return s.start + Math.min(t, s.dur - 0.05);
}

// ------------------------------------------------------------------------------------------ sound
function sound(tls, total) {
  const sfxDir = join(WORK, "sfx");
  if (!existsSync(join(sfxDir, "rain.wav"))) execFileSync(PY, [join(ROOT, "video/narration/sfx.py"), sfxDir], { stdio: "inherit" });
  if (!existsSync(join(sfxDir, "siren_c1.wav"))) execFileSync(PY, [join(ROOT, "video/hardware/siren.py"), sfxDir], { stdio: "inherit" });
  const bed = join(WORK, `bed-${Math.ceil(total)}.wav`);
  if (!existsSync(bed)) execFileSync(PY, [join(ROOT, "video/narration/music.py"), String(Math.ceil(total)), bed, "11"], { stdio: "inherit" });
  const S = (id) => tls.find((s) => s.id === id);
  const at = (id, i, dt = 0) => S(id).start + S(id).lines[i].start + dt;
  const plan = { duration: total, clips: [], sfx: [], target_lufs: -14, music: { path: bed, speech_lufs: -31, gap_db: 5, fade_in: 2, fade_out: 3.5 } };
  for (const s of tls) for (const l of s.lines) plan.clips.push({ path: l.path, t: s.start + l.start, gain_db: l.lang === "hi" ? 0.5 : 0 });
  const fx = (name, t, gain = -14, dur = null, fade = null) => plan.sfx.push({ path: join(sfxDir, `${name}.wav`), t, gain_db: gain, dur, fade });
  // the river, always there, quietly
  for (let t = 0; t < total; t += 28) fx("river", t, -31, 30, 1.5);
  // rain from the rain scene to the move scene, layered in 58 s pieces that cross-fade
  const r0 = S("rain").start + 0.5, r1 = S("move").start + S("move").dur * 0.6;
  for (let t = r0; t < r1; t += 56) fx("rain", t, t === r0 ? -27 : -24, Math.min(60, r1 - t + 2), 2.5);
  fx("thunder_a", S("rain").start + 2.0, -22);
  fx("thunder_b", S("outage").start + 0.6, -19);
  // the seesaw ticks
  [0.4, 1.6, 2.6].forEach((d) => fx("tick", at("dev-rain", 0, 3.2 + d), -22));
  for (let k = 0; k < 9; k++) fx("tick", at("rain", 0, 2.4 + k * (1.2 - k * 0.09)), -23);
  // sirens: the device intro, the alert, the autonomy
  fx("siren_w1", at("dev-siren", 0, 1.8), -27, 3.4, 0.4);
  fx("tap", at("dev-box", 0, 3.6), -16);
  fx("siren_c1", at("hear", 4, 0.1), -25, 6.5, 0.8);
  fx("siren_c1", at("outage", 2, 3.5), -24, 7.5, 0.8);
  // phones: a chime as they light, taps as people confirm
  fx("chime", at("hear", 0, 0.6), -18);
  fx("tap", at("hear", 2, 0.9), -15);
  fx("tap", at("approve", 1, 0.3), -16);
  fx("whoosh_short", S("flow").start + 0.2, -22);
  fx("swell", S("real").start + 0.3, -24);
  const p = join(WORK, "mix-plan.json");
  writeFileSync(p, JSON.stringify(plan, null, 1));
  const wav = join(WORK, "mix.wav");
  const r = spawnSync(PY, [join(ROOT, "video/narration/mix.py"), p, wav], { encoding: "utf8" });
  if (r.status !== 0) throw new Error(`mix.py failed\n${r.stderr}`);
  log(`  mix: ${r.stdout.trim()}`);
  return wav;
}

// ------------------------------------------------------------------------------------------ main
const args = process.argv.slice(2);
const flag = (n) => args.includes(n);
const val = (n) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : null; };

mkdirSync(WORK, { recursive: true });
log("narration (Polly, cached)");
const tls = timeline();
const total = tls.reduce((a, s) => a + s.dur, 0);
const cues = captions(tls);
for (const s of tls) log(`  ${s.id.padEnd(10)} ${s.start.toFixed(1).padStart(6)} s  +${s.dur.toFixed(1)} s`);
log(`total ${total.toFixed(1)} s`);
const data = {
  total,
  scenes: tls.map((s) => ({ id: s.id, chapter: s.chapter, n: s.n, start: s.start, dur: s.dur, lines: s.lines.map((l) => ({ start: l.start, end: l.end, chunks: l.chunks })) })),
  captions: cues,
};
writeFileSync(join(WORK, "data.json"), JSON.stringify(data, null, 1));
if (flag("--plan")) process.exit(0);
if (flag("--audio")) {
  log(`audio: ${sound(tls, total)}`);
  process.exit(0);
}

const srv = await serve();
const base = `http://127.0.0.1:${srv.address().port}`;
const browser = await chromium.launch({ executablePath: CHROME, args: glArgs() });
log(`chromium pid ${browser.process?.()?.pid ?? "?"}`);
try {
  if (val("--preview")) {
    const dir = join(WORK, "preview");
    mkdirSync(dir, { recursive: true });
    const { ctx, page } = await openPage(browser, base, data);
    log(`page: ${await page.evaluate(() => JSON.stringify(window.__dbg ?? null))}`);
    // --clean: no chapter heading or caption (the "not to scale" badge stays), PNG, for slides
    const clean = flag("--clean") || flag("--bare");
    if (clean) await page.addStyleTag({ content: "#chapter, #cap { display: none !important; }" });
    // --bare: also no 3D labels or leader lines (a slide background with its own text on top)
    if (flag("--bare")) await page.addStyleTag({ content: ".tag, #lines { display: none !important; }" });
    for (const x of val("--preview").split(",")) {
      const t = /^[a-z]/.test(x) ? stillTime(tls, ...x.split("@")) : Number(x);
      await page.evaluate((v) => window.__render(v), t);
      const name = `p-${x.replace(/[^\w.+-]/g, "_")}`;
      await page.screenshot(clean ? { path: join(dir, `${name}.png`), type: "png" } : { path: join(dir, `${name}.jpg`), type: "jpeg", quality: 85 });
    }
    await ctx.close();
    log(`previews in ${dir}`);
  } else {
    // stills for the deck
    mkdirSync(STILLDIR, { recursive: true });
    {
      const { ctx, page } = await openPage(browser, base, data);
      const md = ["# Pukaar hardware explainer: stills", "", "1920×1080 PNG frames from `pukaar-hardware-explainer.mp4`, rendered by `video/hardware/render.mjs`.", "The valley is an illustrative model of the Pandoh stretch of the Beas, not to scale. The hardware is designed and simulated, untested in the field.", ""];
      for (const [name, id, where, desc] of STILLS) {
        const t = stillTime(tls, id, where);
        await page.evaluate((v) => window.__render(v), t);
        await page.screenshot({ path: join(STILLDIR, `${name}.png`), type: "png" });
        md.push(`- **${name}.png** (${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}): ${desc}${/[.?!]$/.test(desc) ? "" : "."}`);
      }
      writeFileSync(join(STILLDIR, "stills.md"), md.join("\n") + "\n");
      await ctx.close();
      log(`${STILLS.length} stills in ${STILLDIR}`);
    }
    if (!flag("--stills")) {
      const N = Math.ceil(total * FPS);
      const P = Number(process.env.HW_WORKERS ?? 2);
      const partsList = [];
      const jobs = [];
      for (let k = 0; k < P; k++) {
        const a = Math.floor((N * k) / P), b = Math.floor((N * (k + 1)) / P);
        const out = join(WORK, `part-${k}.mp4`);
        partsList.push(out);
        jobs.push(renderRange(browser, base, data, a, b, out));
      }
      log(`render ${N} frames, ${P} workers`);
      const t0 = Date.now();
      await Promise.all(jobs);
      log(`  rendered in ${((Date.now() - t0) / 60000).toFixed(1)} min`);
      writeFileSync(join(WORK, "parts.txt"), partsList.map((p) => `file '${p}'`).join("\n"));
      const picture = join(WORK, "picture.mp4");
      ff(["-f", "concat", "-safe", "0", "-i", join(WORK, "parts.txt"), "-c", "copy", picture]);
      for (const p of partsList) rmSync(p, { force: true });
      const wav = sound(tls, total);
      mkdirSync(OUTDIR, { recursive: true });
      const mp4 = join(OUTDIR, "pukaar-hardware-explainer.mp4");
      // the parts are a near-lossless intermediate; the outputs are encoded once from it
      ff(["-i", picture, "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-shortest", "-movflags", "+faststart", mp4]);
      const small = join(OUTDIR, "pukaar-hardware-explainer-small.mp4");
      ff(["-i", picture, "-i", wav, "-map", "0:v", "-map", "1:a", "-vf", "scale=1280:720:flags=lanczos", "-c:v", "libx264", "-preset", "slow", "-crf", "27", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-shortest", "-movflags", "+faststart", small]);
      writeFileSync(join(OUTDIR, "pukaar-hardware-explainer.srt"), srtText(cues));
      log(`${mp4} ${mb(mp4)}; ${small} ${mb(small)}; ${total.toFixed(1)} s`);
    }
  }
} finally {
  await browser.close();
  srv.close();
}
