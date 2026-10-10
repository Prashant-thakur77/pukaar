#!/usr/bin/env node
// Renders Pukaar's videos from their scene lists (adapted from the pipeline built for Strike):
//
//   node video/record.mjs demo      # video/demo.mjs    -> docs/media/pukaar-demo.mp4 (+ silent cut, .srt, poster)
//   node video/record.mjs trailer   # video/trailer.mjs -> docs/media/pukaar-trailer.mp4
//
// Options: --only a,b (re-record only these scenes), --plan (narrate and print the timing only), --preview (with
// --only: just those scenes, into video/.out/preview.mp4).
//
// Needs: the frontend's node_modules (Playwright, three), ffmpeg, and Python 3.10 with chatterbox-tts,
// faster-whisper, pyloudnorm, librosa and soundfile. Numbers are read at render time from data/, README.md, the live
// API and the AWS account (video/lib/facts.mjs); a missing number fails the render.
import { readFileSync } from "node:fs";
import {
  ROOT,
  captionReport,
  captionStates,
  chromium,
  CHROME,
  concatList,
  copyFileSync,
  existsSync,
  ff,
  finalVideo,
  join,
  log,
  mb,
  mixAudio,
  mkdirSync,
  mux,
  narrate,
  recordScene,
  renderCaptions,
  rmSync,
  segment,
  srt,
  timeline,
  timingHash,
  wrap2,
  writeFileSync,
} from "./lib/engine.mjs";
import { pukaarFacts } from "./lib/facts.mjs";

const KIND = process.argv[2];
if (!["demo", "trailer"].includes(KIND)) {
  console.error("usage: node video/record.mjs demo|trailer [--only a,b] [--plan] [--preview]");
  process.exit(2);
}
const arg = (k) => {
  const i = process.argv.indexOf(k);
  return i > 0 ? (process.argv[i + 1] ?? true) : null;
};
const ONLY = arg("--only") ? new Set(String(arg("--only")).split(",")) : null;
const PLAN = process.argv.includes("--plan");
const LIVE_SIGN = false;
const PREVIEW = process.argv.includes("--preview"); // with --only: record and assemble just those scenes, into video/.out
const WORK = join(ROOT, "video", ".out", KIND);
const MEDIA = join(ROOT, "docs", "media");
mkdirSync(WORK, { recursive: true });

/** The narrator: voice-ref-bright.wav is Chatterbox's own built-in voice read at exaggeration 0.8 (synthetic, no real
 *  person), used as the reference at exaggeration 0.7 and cfg_weight 0.3 (chosen and measured for Strike, 3 Oct 2026). */
export const SETTINGS = {
  voice: join(ROOT, "video/narration/voice-ref-bright.wav"),
  exaggeration: 0.7,
  cfg_weight: 0.3,
  temperature: 0.7,
  seeds: [11, 23, 37],
  min_score: 0.93,
  min_cands: 2,
  cache: join(ROOT, "video/.out/tts"),
  asr_model: "small.en",
  target_cps: 19,
  max_cps: 22,
};

const mmss = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
/** docs/submission/<kind>-script.md, written from the same scene list and timeline as the video. */
function scriptDoc(doc, scenes, tls, total, words, intro = null) {
  const dur = intro?.duration ?? 0;
  const at = intro?.at ?? 0; // where the intro sits on the body's timeline (after the scene intro.after)
  const off = (t) => (t >= at - 1e-6 ? t + dur : t);
  const chapters = scenes
    .map((s, i) => (s.chapter ? `${mmss(off(tls[i].start))} ${s.chapter}` : null))
    .filter(Boolean);
  if (intro) {
    const k = chapters.findIndex((c) => {
      const [m, sec] = c.split(" ")[0].split(":").map(Number);
      return m * 60 + sec > at;
    });
    chapters.splice(k < 0 ? chapters.length : k, 0, `${mmss(at)} ${intro.title}`);
  }
  const parts = [
    doc.head({
      total: total + dur,
      narration: total,
      words,
      wpm: Math.round((words / total) * 60),
      mmss,
      chapters,
      intro,
    }),
  ];
  const introPart = () => {
    parts.push(`## ${mmss(at)} to ${mmss(at + dur)} · ${intro.title}`);
    if (intro.screen) parts.push(`Screen: ${intro.screen}`);
    parts.push(`> ${intro.text}`);
  };
  if (intro && at === 0) introPart();
  scenes.forEach((s, i) => {
    const tl = tls[i];
    if (intro && at > 0 && Math.abs(tl.start - at) < 1e-6) introPart();
    parts.push(`## ${mmss(off(tl.start))} to ${mmss(off(tl.start) + tl.dur)} · ${s.title ?? s.tag}`);
    if (s.screen) parts.push(`Screen: ${s.screen}`);
    parts.push(tl.lines.map((l) => `> ${l.text.replace(/\s*\|\s*/g, " ")}`).join("\n>\n"));
  });
  if (doc.tail) parts.push(doc.tail);
  return parts.join("\n\n") + "\n";
}

async function main() {
  const def = await import(`./${KIND}.mjs`);
  const facts = await pukaarFacts(ROOT);
  log("facts", JSON.stringify(facts).slice(0, 600));
  const browser = await chromium.launch({
    executablePath: CHROME,
    args: ["--use-angle=vulkan", "--enable-gpu", "--ignore-gpu-blocklist", "--autoplay-policy=no-user-gesture-required"],
  });
  const env = { facts };
  const live = def.probe ? await def.probe(browser, facts) : {};
  if (Object.keys(live).length) log("live", JSON.stringify(live));
  let scenes = def.scenes(facts, live);

  // a video can override the voice settings (the demo reads a little faster than the pitch)
  const narr = narrate(scenes, WORK, { ...SETTINGS, ...(def.tts ?? {}) });
  const tls = timeline(scenes, narr, def.timing ?? {});
  const total = tls.reduce((a, t) => a + t.dur, 0);
  const words = (s) => s.replace(/\|/g, " ").split(/\s+/).filter(Boolean).length;
  let nw = 0;
  for (const tl of tls) {
    const w = tl.lines.reduce((a, l) => a + words(l.text), 0);
    nw += w;
    log(
      `${tl.id.padEnd(11)} ${tl.start.toFixed(1).padStart(6)} +${tl.dur.toFixed(1).padStart(5)} s  ${w} words, ${((w / tl.dur) * 60).toFixed(0)} wpm`,
    );
  }
  log(`total ${total.toFixed(1)} s, ${nw} words, ${((nw / total) * 60).toFixed(0)} wpm`);
  for (const b of captionReport(tls)) log(`caption: ${b}`);
  for (const tl of tls)
    for (const l of tl.lines)
      if (l.take.score < 0.9) log(`low Whisper score ${l.take.score}: "${l.text}" heard "${l.take.asr}"`);
  writeFileSync(join(WORK, "timeline.json"), JSON.stringify(tls, null, 1));
  if (PLAN) return browser.close();
  if (PREVIEW) {
    if (!ONLY) throw new Error("--preview needs --only");
    const keep = scenes.map((s, i) => [s, tls[i]]).filter(([s]) => ONLY.has(s.id));
    scenes = keep.map(([s]) => s);
    let t = 0;
    tls.length = 0;
    for (const [, tl] of keep) {
      tls.push({ ...tl, start: t });
      t += tl.dur;
    }
  }

  // ---------------------------------------------------------------- record
  const srcs = [];
  for (const [i, s] of scenes.entries()) {
    const tl = tls[i];
    if (s.kind === "slide") {
      srcs.push({ image: await def.slideImage(browser, s, WORK) });
      continue;
    }
    if (s.kind === "footage") {
      // stock footage, cut on the narration: shot [name, line, chunk] starts on that caption chunk
      srcs.push({
        shots: s.shots.map(([name, li, k]) => ({
          name,
          at: li === 0 && k === 0 ? 0 : tl.lines[li].chunks[k].start - 0.1,
        })),
      });
      continue;
    }
    if (s.kind === "clip" && !LIVE_SIGN) {
      srcs.push({ path: join(ROOT, s.clip), start: 0, speed: s.clipSpeed ?? 1 });
      continue;
    }
    const metaPath = join(WORK, "raw", s.id, "meta.json");
    const reuse =
      ONLY &&
      !ONLY.has(s.id) &&
      existsSync(metaPath) &&
      JSON.parse(readFileSync(metaPath, "utf8")).hash === timingHash(tl);
    if (reuse) {
      srcs.push(JSON.parse(readFileSync(metaPath, "utf8")));
      continue;
    }
    if (ONLY && !ONLY.has(s.id)) log(`  ${s.id}: no reusable recording (timing changed), recording it`);
    // live pages (and the public RPC) fail now and then: try a scene up to three times, never the live signature
    let meta;
    for (let attempt = 1; ; attempt++) {
      try {
        meta = await recordScene(
          browser,
          { kind: "page", ...s, kind: s.kind === "clip" ? "page" : s.kind },
          tl,
          WORK,
          env,
        );
        break;
      } catch (e) {
        if (s.kind === "clip" || attempt >= 3) throw e;
        log(`  ${s.id}: attempt ${attempt} failed (${e.message.split("\n")[0]}), retrying`);
      }
    }
    srcs.push(meta);
  }

  // ---------------------------------------------------------------- assemble
  log("assemble");
  const seg = join(WORK, "seg");
  rmSync(seg, { recursive: true, force: true });
  mkdirSync(seg, { recursive: true });
  const files = scenes.map((s, i) => {
    const out = join(seg, `${String(i).padStart(2, "0")}-${s.id}.mp4`);
    segment(s, tls[i], srcs[i], out);
    return out;
  });
  concatList(files, join(seg, "list.txt"));
  const joined = join(WORK, "joined.mp4");
  ff(["-f", "concat", "-safe", "0", "-i", join(seg, "list.txt"), "-c", "copy", joined]);
  const states = captionStates(scenes, tls);
  await renderCaptions(browser, states, join(WORK, "captions"));
  await browser.close();

  const total2 = tls.reduce((a, t) => a + t.dur, 0);
  const out = PREVIEW
    ? {
        narrated: "../../video/.out/preview.mp4",
        srt: "../../video/.out/preview.srt",
        poster: "../../video/.out/preview.png",
      }
    : def.outputs;
  const picture = join(WORK, "picture.mp4");
  finalVideo(joined, states, WORK, picture, def.crf ?? 23);
  const wav = mixAudio(tls, total2, WORK, def.music ?? null);
  // a video may open with a recorded intro (the pitch: the founder's own clip, video/founder.mjs)
  const intro = def.intro && !PREVIEW ? await def.intro() : null;
  if (intro) {
    // after a scene (intro.after), or at the very start
    const k = intro.after ? scenes.findIndex((x) => x.id === intro.after) : -1;
    if (intro.after && k < 0) throw new Error(`intro.after: no scene "${intro.after}"`);
    intro.at = k < 0 ? 0 : tls[k].start + tls[k].dur;
    const body = join(WORK, "body.mp4");
    mux(picture, wav, body);
    prependIntro(intro, body, join(MEDIA, out.narrated));
    log(
      `  ${intro.path.replace(ROOT + "/", "")} (${intro.duration.toFixed(1)} s) inserted at ${intro.at.toFixed(1)} s`,
    );
  } else mux(picture, wav, join(MEDIA, out.narrated));
  if (out.silent) copyFileSync(picture, join(MEDIA, out.silent));
  const s = srt(tls);
  writeFileSync(
    join(MEDIA, out.srt),
    intro
      ? srtText([
          ...s.cues.filter((c) => c.from < intro.at),
          ...shiftCues(intro.cues, intro.at),
          ...shiftCues(
            s.cues.filter((c) => c.from >= intro.at),
            intro.duration,
          ),
        ])
      : s.text,
  );
  writeFileSync(
    join(WORK, "script.txt"),
    tls.map((t) => t.lines.map((l) => l.text.replace(/\s*\|\s*/g, " ")).join(" ")).join("\n\n") + "\n",
  );
  if (out.transcript) copyFileSync(join(WORK, "script.txt"), join(MEDIA, out.transcript));
  // poster: a clean frame (no captions) of the chosen scene
  const pi = Math.max(
    0,
    scenes.findIndex((x) => x.id === def.poster.scene),
  );
  ff([
    "-ss",
    String(PREVIEW ? 1 : (def.poster.at ?? tls[pi].dur / 2)),
    "-i",
    files[pi],
    "-frames:v",
    "1",
    join(MEDIA, out.poster),
  ]);
  if (out.gif) {
    const pal = join(WORK, "palette.png");
    const src = join(MEDIA, out.silent);
    const gf = "fps=10,scale=960:-1:flags=lanczos";
    // 12 s from the start of def.gifScene (the opening by default)
    const gi = def.gifScene ? scenes.findIndex((x) => x.id === def.gifScene) : 0;
    const gs = String(Math.max(0, gi >= 0 ? tls[gi].start + 0.5 : 0));
    ff(["-ss", gs, "-t", "12", "-i", src, "-vf", `${gf},palettegen=max_colors=128:stats_mode=diff`, pal]);
    ff([
      "-ss",
      gs,
      "-t",
      "12",
      "-i",
      src,
      "-i",
      pal,
      "-lavfi",
      `${gf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle`,
      join(MEDIA, out.gif),
    ]);
  }
  if (PREVIEW) return log(`preview: video/.out/preview.mp4, ${total2.toFixed(1)} s`);
  if (def.scriptDoc)
    writeFileSync(join(ROOT, def.scriptDoc.path), scriptDoc(def.scriptDoc, scenes, tls, total, nw, intro));
  writeFileSync(
    join(WORK, "report.json"),
    JSON.stringify(
      {
        total,
        words: nw,
        wpm: (nw / total) * 60,
        scenes: tls.map((t) => ({ id: t.id, start: t.start, dur: t.dur })),
      },
      null,
      1,
    ),
  );
  for (const k of Object.values(out)) if (existsSync(join(MEDIA, k))) log(`${k}  ${mb(join(MEDIA, k))}`);
  log(
    `duration ${(total + (intro?.duration ?? 0)).toFixed(1)} s${intro ? ` (intro ${intro.duration.toFixed(1)} s)` : ""}, ${nw} words, ${((nw / total) * 60).toFixed(0)} wpm`,
  );
}

/** The rendered body with the intro's first `duration` seconds inserted at `intro.at` (0: at the start); the body's
 *  audio fades out into the intro and back in after it (its music bed would otherwise stop and start abruptly). One
 *  encode, 30 fps, AAC 48 kHz stereo, a -2 dB limiter so the joined, re-encoded audio stays under -1.5 dBTP. */
function prependIntro(intro, body, out) {
  const at = intro.at ?? 0;
  const v = (i, trim) => `[${i}:v]${trim}fps=30,scale=1920:1080,setsar=1,format=yuv420p`;
  const a = (i, trim) => `[${i}:a]${trim}aresample=48000,aformat=channel_layouts=stereo`;
  const parts = [`${v(0, "")}[vi]`, `${a(0, "")}[ai]`];
  const order = [];
  if (at > 0) {
    parts.push(`${v(1, `trim=end=${at.toFixed(3)},setpts=PTS-STARTPTS,`)}[vh]`);
    parts.push(
      `${a(1, `atrim=end=${at.toFixed(3)},asetpts=PTS-STARTPTS,`)},afade=t=out:st=${(at - 0.25).toFixed(3)}:d=0.25[ah]`,
    );
    order.push("[vh][ah]");
  }
  order.push("[vi][ai]");
  parts.push(`${v(1, `trim=start=${at.toFixed(3)},setpts=PTS-STARTPTS,`)}[vb]`);
  parts.push(
    `${a(1, `atrim=start=${at.toFixed(3)},asetpts=PTS-STARTPTS,`)}${at > 0 ? ",afade=t=in:d=0.6" : ""}[ab]`,
  );
  order.push("[vb][ab]");
  parts.push(
    `${order.join("")}concat=n=${order.length}:v=1:a=1[v][ac]`,
    `[ac]alimiter=limit=0.79:attack=5:release=60:level=disabled[a]`,
  );
  ff([
    "-t",
    intro.duration.toFixed(3),
    "-i",
    intro.path,
    "-i",
    body,
    "-filter_complex",
    parts.join(";"),
    "-map",
    "[v]",
    "-map",
    "[a]",
    "-c:v",
    "libx264",
    "-preset",
    "slow",
    "-crf",
    "20",
    "-profile:v",
    "high",
    "-pix_fmt",
    "yuv420p",
    "-c:a",
    "aac",
    "-b:a",
    "160k",
    "-movflags",
    "+faststart",
    out,
  ]);
}

const shiftCues = (cues, by) => cues.map((c) => ({ ...c, from: c.from + by, to: c.to + by }));
function srtText(cues) {
  const ts = (s) => {
    const ms = Math.max(0, Math.round(s * 1000));
    const p = (n, w = 2) => String(n).padStart(w, "0");
    return `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)},${p(ms % 1000, 3)}`;
  };
  return cues
    .map((c, i) => `${i + 1}\n${ts(c.from)} --> ${ts(c.to)}\n${wrap2(c.text).join("\n")}\n`)
    .join("\n");
}

main().then(
  () => process.exit(0),
  (e) => {
    console.error(e);
    process.exit(1);
  },
);
