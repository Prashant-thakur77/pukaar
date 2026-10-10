#!/usr/bin/env node
// A ~35 s trailer cut from the rendered demo (run `node video/record.mjs demo` first): the hook with its voice, a
// montage of the strongest live moments (caption-free scene pictures, a whoosh on each cut, the real Polly alert
// under its shot), then the end card with its line. Everything on screen is the demo's own footage.
//   node video/trailer.mjs   ->  docs/media/pukaar-trailer.mp4
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { ROOT, ff, log, mb } from "./lib/engine.mjs";

const WORK = join(ROOT, "video/.out/demo");
const DEMO = join(ROOT, "docs/media/pukaar-demo.mp4");
const OUT = join(ROOT, "docs/media/pukaar-trailer.mp4");
const tls = JSON.parse(readFileSync(join(WORK, "timeline.json"), "utf8"));
const T = Object.fromEntries(tls.map((t) => [t.id, t]));
const need = (id) => {
  if (!T[id]) throw new Error(`demo has no scene "${id}"`);
  return T[id];
};

// [scene, start inside the scene, length, audio from the demo? ] — times inside each scene's own clock
const heard = need("heard");
const polly = heard.audio?.[0]?.t ?? 2.6;
const CUTS = [
  { id: "hook", from: 0, len: need("hook").dur, audio: true },
  { id: "story", from: need("story").lines[3].start - 0.3, len: 3.2 },
  { id: "live", from: 2.2, len: 2.8 },
  { id: "approve", from: need("approve").dur - 3.2, len: 3.0 },
  { id: "heard", from: polly - 0.2, len: 4.6, audio: true },
  { id: "arch", from: need("arch").lines[4].start, len: 3.6 },
  { id: "proof", from: need("proof").lines[1].start + 1.0, len: 2.6 },
  { id: "close", from: 0, len: need("close").dur, audio: true },
];

const inputs = [];
const parts = [];
let t = 0;
const audioParts = [];
CUTS.forEach((c, i) => {
  const s = T[c.id];
  // pictures: the narrated demo (with its caption bar) for voiced cuts; the clean scene segment otherwise
  const seg = join(WORK, "seg", `${String(tls.indexOf(s)).padStart(2, "0")}-${c.id}.mp4`);
  const src = c.audio ? DEMO : seg;
  const from = c.audio ? s.start + c.from : c.from;
  inputs.push("-ss", from.toFixed(3), "-t", c.len.toFixed(3), "-i", src);
  parts.push(`[${i}:v]fps=30,scale=1920:1080,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v${i}]`);
  if (c.audio) {
    parts.push(`[${i}:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS,afade=t=in:d=0.08,afade=t=out:st=${(c.len - 0.12).toFixed(3)}:d=0.12,adelay=${Math.round(t * 1000)}|${Math.round(t * 1000)}[a${i}]`);
    audioParts.push(`[a${i}]`);
  }
  c.at = t;
  t += c.len;
});
const total = t;
const n = CUTS.length;
// music: the demo's own bed (synthesised, CC0), louder here with no voice to sit under
const bed = join(ROOT, "video/.out/music", (await import("node:fs")).readdirSync(join(ROOT, "video/.out/music")).find((f) => f.startsWith("bed-")));
inputs.push("-i", bed);
parts.push(`[${n}:a]atrim=0:${total.toFixed(3)},asetpts=PTS-STARTPTS,aformat=channel_layouts=stereo,volume=0.55,afade=t=in:d=1.5,afade=t=out:st=${(total - 2.5).toFixed(3)}:d=2.5[bed]`);
// a short whoosh (pink noise through a swept band-pass) on every montage cut, 10 dB under the voice
const cutsAt = CUTS.slice(1).map((c) => c.at);
inputs.push("-f", "lavfi", "-t", "0.5", "-i", "anoisesrc=color=pink:d=0.5:a=0.6");
parts.push(`[${n + 1}:a]bandpass=f=1400:w=1800,afade=t=in:d=0.18:curve=qsin,afade=t=out:st=0.2:d=0.3:curve=qsin,volume=0.35,aformat=channel_layouts=stereo,asplit=${cutsAt.length}${cutsAt.map((_, k) => `[w${k}]`).join("")}`);
cutsAt.forEach((at, k) => {
  const d = Math.max(0, Math.round((at - 0.25) * 1000));
  parts.push(`[w${k}]adelay=${d}|${d}[wd${k}]`);
});
parts.push(`${CUTS.map((_, i) => `[v${i}]`).join("")}concat=n=${n}:v=1:a=0[v]`);
parts.push(`[bed]${audioParts.join("")}${cutsAt.map((_, k) => `[wd${k}]`).join("")}amix=inputs=${1 + audioParts.length + cutsAt.length}:normalize=0:duration=first,loudnorm=I=-14:TP=-1.5:LRA=11,alimiter=limit=0.79:level=disabled[a]`);
ff([...inputs, "-filter_complex", parts.join(";"), "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "slow", "-crf", "20",
  "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", "-t", total.toFixed(3), OUT]);
log(`pukaar-trailer.mp4  ${total.toFixed(1)} s  ${mb(OUT)}`);
