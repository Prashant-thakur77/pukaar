// The pitch video's pictures and sound, scene by scene (the narration is in video/pitch.mjs). Every layer's times are
// seconds into its scene; at(i) is when line i starts, ch(i, k) when its caption chunk k starts, end(i) when it ends.
// Every number on screen has its source line; SOURCES feeds the credits file.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { ROOT } from "./lib/engine.mjs";

const pw = () => readFileSync(join(ROOT, ".env.demo.local"), "utf8").match(/^PUKAAR_DEMO_PASSWORD=(.+)$/m)[1].trim().replace(/^["']|["']$/g, "");
async function signIn({ page, url }) {
  await page.goto(url + "/login");
  await page.locator('input[autocomplete="username"]').fill("officer1");
  await page.locator('input[type="password"]').fill(pw());
  await page.locator('form button[type="submit"]').click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
}
const settle = async (page, ms = 2500) => { await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {}); await page.waitForTimeout(ms); };
const scrollTo = (page, sel, off = 120) => page.locator(sel).first().evaluate((el, o) => window.scrollTo(0, el.getBoundingClientRect().top + scrollY - o), off);

/** Real pages of the live site, as timed screenshots (no staging needed). */
export const CAPTURES = {
  live: { path: "/live", allowOsm: true, async run({ page, url, shot, sleep }) {
    await page.goto(url + "/live"); await settle(page, 12000);
    await shot(0);
    await page.evaluate(() => window.scrollTo(0, 560)); await sleep(2500); await shot(1.6);
  } },
  sensors: { path: "/sensors", async run({ page, url, shot }) {
    await page.goto(url + "/sensors"); await settle(page, 3000);
    await page.getByText(/^Gauge to/).first().evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + scrollY - 160)).catch(() => page.evaluate(() => window.scrollTo(0, 900)));
    await page.waitForTimeout(3500); await shot(0);
  } },
  story: { path: "/", async run({ page, url, shot }) {
    await page.goto(url + "/"); await page.locator(".story-step").first().waitFor({ timeout: 60_000 }); await settle(page, 3000);
    const steps = page.locator(".story-step");
    for (let i = 0; i < 4; i++) {
      await steps.nth(i).evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + scrollY - innerHeight * 0.3));
      await page.waitForTimeout(1600); await shot(i * 1.4);
    }
  } },
  agents: { path: "/agents", async run({ page, url, shot, mark }) {
    await page.goto(url + "/agents"); await settle(page, 3500);
    await shot(0); await mark("chips", page.getByText(/Pending model access/));
  } },
  // staged by video/live.mjs: Gohar's critical alert is pending; the officer approves it for real (Step Functions)
  console: { path: "/console", async run(c) {
    const { page, url, shot, mark } = c;
    await signIn(c);
    await page.goto(url + "/console#approvals"); await page.locator(".pending-card").first().waitFor({ timeout: 60_000 });
    const more = page.getByRole("button", { name: /^Show \d+ more$/ });
    if (await more.count()) await more.first().click();
    const card = page.locator(".pending-card", { hasText: "Gohar" }).first();
    await card.waitFor({ timeout: 30_000 });
    await card.evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + scrollY - 90));
    await page.waitForTimeout(1500);
    await shot(0); await mark("card", card);
    await card.locator(".btn-approve").click();
    await page.locator("dialog[open] .btn-accent").waitFor({ timeout: 8000 });
    await page.waitForTimeout(500); await shot(2.3); await mark("dialog", page.locator("dialog[open]"));
    await page.locator("dialog[open] .btn-accent").click();
    await page.waitForTimeout(2500); await shot(3.4);
  } },
  village: { path: "/village/gohar", async run({ page, url, shot, mark }) {
    await page.goto(url + "/village/gohar"); await page.locator(".alert-card").first().waitFor({ timeout: 60_000 }); await settle(page, 2500);
    await scrollTo(page, ".alert-card", 140); await page.waitForTimeout(900); await shot(0); await mark("card", page.locator(".alert-card"));
    const tog = page.locator(".alert-card").first().locator("button[aria-expanded]");
    await tog.click().catch(() => {}); await page.locator(".tte").waitFor({ timeout: 20_000 }).catch(() => {});
    await page.waitForTimeout(1500); await scrollTo(page, ".tte", 200).catch(() => {}); await page.waitForTimeout(900);
    await shot(10); await mark("tte", page.locator(".tte"));
  } },
  safe: { path: "/village/pandoh", async run({ page, url, shot, mark }) {
    await page.goto(url + "/village/pandoh"); await settle(page, 4000);
    await scrollTo(page, ".wtg-top", 260).catch(() => {}); await page.waitForTimeout(3500); await shot(0); await mark("wtg", page.locator(".wtg-top"));
  } },
  report: { path: "/report", vw: 398, vh: 848, dsf: 2, async run({ page, url, shot }) {
    await page.goto(url + "/report"); await settle(page, 3000); await shot(0);
  } },
  audit: { path: "/audit", async run(c) {
    await signIn(c); await c.page.goto(c.url + "/audit"); await c.page.locator(".data-table tbody tr").first().waitFor({ timeout: 60_000 }); await settle(c.page, 1500);
    await c.page.evaluate(() => window.scrollTo(0, 380)); await c.page.waitForTimeout(800); await c.shot(0);
    await c.mark("deny", c.page.locator(".data-table tbody tr.row-deny"));
  } },
  impact: { path: "/impact", async run({ page, url, shot }) {
    await page.goto(url + "/impact"); await settle(page, 3000);
    await scrollTo(page, ".sat-band", 40).catch(() => {}); await page.waitForTimeout(3000); await shot(0);
  } },
};

const TAG_TL = { left: "56px", top: "96px" };
const credit = (s) => s;

export function layersFor(id, c) {
  const { at, ch, end, dur, f } = c;
  const S = (o) => o;
  switch (id) {
    case "night": return {
      layers: [
        { type: "bg", style: "black", fadeIn: 0 },
        { type: "clip", name: "storm", from: 3.0, to: at(1) + 0.3, grade: { b: 0.45, c: 1.15, s: 0.6 }, tint: "rgba(6,17,31,.35)", kb: { s: [1.05, 1.15] }, tag: "Illustrative footage" },
        { type: "clip", name: "night", from: at(1), to: dur, grade: { b: 0.8, c: 1.1, s: 0.7 }, kb: { s: [1.08, 1.02] }, tag: "Illustrative footage" },
        { type: "rain", from: 0, to: dur, intensity: 0.9 },
        { type: "text", cls: "eyebrow", html: "Mandi district · Himachal Pradesh", from: 0.5, to: 3.1, x: 150, y: 430, size: 26, anim: "rise", fadeOut: 0.5 },
        { type: "text", html: "The night of *30 June 2025*", from: 0.8, to: 3.1, x: 150, y: 480, size: 96, stagger: 0.12, fadeOut: 0.5 },
        { type: "cut", outlet: "ANI · The News Mill", date: "30 Jun 2025, 9:48 am", text: "Red alert issued in Mandi district of Himachal Pradesh, Beas river flooded after heavy rainfall", from: at(1) + 0.1, to: ch(1, 1) + 0.2, x: 360, y: 300, w: 1150, rot: -2.5, seed: 3 },
        { type: "text", html: "स्याठी · *Syathi*", from: ch(1, 1), to: dur, x: 150, y: 420, size: 120, stagger: 0.2 },
      ],
      sfx: [
        { name: "rain", t: 0, gain: -14, dur: 60, fade: 2.5 },
        { name: "thunder_a", t: 1.1, gain: -6 },
        { name: "thunder_b", t: at(1) - 1.2, gain: -9 },
        { name: "paper_slam", t: at(1) + 0.1, gain: -9 },
      ],
      flashes: [{ t: 1.15, d: 0.5, a: 0.55 }, { t: 1.5, d: 0.3, a: 0.3 }, { t: at(1) - 1.15, d: 0.4, a: 0.35 }],
    };
    case "dog": return {
      layers: [
        { type: "bg", style: "black", fadeIn: 0 },
        { type: "clip", name: "roof-rain", from: 0, to: at(3), grade: { b: 0.5, c: 1.1, s: 0.55 }, tint: "rgba(6,17,31,.3)", kb: { s: [1.04, 1.14], p: [[0.5, 0.5], [0.55, 0.45]] }, tag: "Illustrative footage" },
        { type: "rain", from: 0, to: at(3), intensity: 0.6, seed: 5 },
        { type: "text", html: "It was a *dog*, barking.", from: at(0), to: at(2), x: 150, y: 420, size: 120, stagger: 0.13 },
        { type: "stat", value: 60, suffix: "+", label: "people from *20 households* got out\nbefore the slope came down", source: "The Tribune · 9 Jul 2025", from: at(2), to: at(3), x: 150, y: 250, w: 760, size: 230 },
        { type: "cut", outlet: "The Tribune", date: "9 Jul 2025", text: "Pet dog emerges saviour in Mandi village, saves 60 lives amid monsoon fury", from: ch(2, 1), to: at(3), x: 900, y: 560, w: 900, rot: 2.5, seed: 9 },
        { type: "quote", text: "Can we trust a dog to warn us next time? We need proper early warning systems…", who: "Mohan, a villager of Syathi", source: "quoted in The Tribune · 9 Jul 2025", from: at(3) - 0.1, to: dur, x: 200, y: 250, w: 1520, size: 74, span: 2.6 },
      ],
      sfx: [{ name: "paper_slam", t: ch(2, 1), gain: -9 }, { name: "hit", t: at(2), gain: -16 }],
    };
    case "scale": return {
      layers: [
        { type: "clip", name: "rain-shaft", from: 0, to: at(2) + 0.2, grade: { b: 0.62, c: 1.1, s: 0.8 }, kb: { s: [1.02, 1.1] } },
        { type: "text", html: "This is not *one village.*", from: at(0), to: at(1), x: 150, y: 430, size: 120, stagger: 0.1 },
        { type: "stat", value: 169, label: "floods a year: the world's *most frequent* disaster", source: "EM-DAT (CRED), 2005–2024 average", from: at(1), to: at(2), x: 150, y: 330, w: 1300, size: 220 },
        { type: "clip", name: "monsoon-globe", from: at(2), to: dur, grade: { b: 0.55, s: 0.9 }, kb: { s: [1.15, 1.25], p: [[0.4, 0.45], [0.38, 0.45]] }, vignette: true },
        { type: "stat", value: 1.81, decimals: 2, suffix: " billion", label: "people live within reach of\na *1-in-100-year* flood", source: "Rentschler et al., Nature Communications 2022", from: ch(2, 0), to: dur, x: 110, y: 270, w: 900, size: 170 },
        { type: "stat", value: 390, suffix: " million", label: "of them in *India*", source: "same study", from: ch(2, 1), to: dur, x: 1080, y: 520, w: 760, size: 150 },
      ],
      sfx: [{ name: "whoosh", t: at(0) - 0.4, gain: -16 }, { name: "hit", t: ch(2, 0), gain: -18 }],
    };
    case "himalaya": return {
      layers: [
        { type: "bg", style: "deep" },
        { type: "still", name: "flood-mark", from: 0, to: at(1) + 0.2, kb: { s: [1.0, 1.18], p: [[0.4, 0.5], [0.12, 0.55]] }, grade: { b: 0.7, c: 1.1, s: 0.85 }, tag: "<b>Real</b> · Mandi: the Beas flood mark, 9 July 2023", credit: "Photo: Madhrakangri · CC BY 4.0" },
        { type: "stat", value: 500, suffix: "+", label: "lives lost: *Himachal Pradesh*, monsoon 2023", source: "Govt of Himachal Pradesh, Post-Disaster Needs Assessment 2023", from: ch(0, 1) - 0.2, to: at(1), x: 1040, y: 300, w: 820, size: 200 },
        { type: "still", name: "rudraprayag", from: at(1), to: at(2) + 0.2, kb: { s: [1.06, 1.16] }, grade: { b: 0.62, c: 1.1, s: 0.85 }, tag: "<b>Real</b> · Rudraprayag, Uttarakhand, 23 June 2013", credit: "Photo: PIB, Govt of India · GODL-India" },
        { type: "stat", value: 6054, label: "dead or never found: *Uttarakhand*, June 2013\n(580 dead, 5,474 missing)", source: "Ministry of Home Affairs, Rajya Sabha, 7 Aug 2013", from: ch(1, 1) - 0.2, to: at(2), x: 120, y: 330, w: 1100, size: 200 },
        { type: "bg", style: "deep", from: at(2), to: at(3) + 0.3 },
        { type: "sat", before: "sat-teesta-before", after: "sat-teesta-after", dates: ["14 May 2023", "15 Nov 2023"], place: "Teesta-III dam, Chungthang, Sikkim", credit: "Contains modified Copernicus Sentinel data 2023", from: at(2), to: at(3) + 0.3, x: 150, y: 120, w: 720, h: 708, wipe: [0.5, 2.6] },
        { type: "stat", value: 55, text: "55 dead · 74 missing", count: false, label: "a glacial lake burst in the night:\n*Sikkim*, 4 October 2023", source: "Sattar et al., Science 2025", from: ch(2, 1) - 0.3, to: at(3), x: 990, y: 330, w: 860, size: 96 },
        { type: "bg", style: "deep", from: at(3), to: dur },
        { type: "sat", before: "esa-before", after: "esa-after", dates: ["24 Aug 2026", "26 Aug 2026"], place: "Glacier collapse and flood, Rasuwa, Nepal (false colour)", credit: "ESA: Copernicus Sentinel-2 (CC BY-SA 3.0 IGO) · Landsat-9 (CC BY 4.0)", from: at(3), to: dur, x: 150, y: 100, w: 600, h: 712, wipe: [0.6, 2.8] },
        { type: "stat", value: 1451, label: "dead and *5,745 missing*:\nNepal, 26 August 2026", source: "NDRRMA SitRep 20 · as of 21 Sep 2026", from: ch(3, 2) - 0.2, to: dur, x: 920, y: 330, w: 900, size: 200 },
      ],
      sfx: [{ name: "whoosh_short", t: at(1) - 0.2, gain: -15 }, { name: "whoosh_short", t: at(2) - 0.2, gain: -15 }, { name: "whoosh_short", t: at(3) - 0.2, gain: -15 }, { name: "river", t: 0, gain: -24, dur: 20, fade: 2 }],
    };
    case "fail": return {
      layers: [
        { type: "bg", style: "night" },
        { type: "cut", outlet: "Down To Earth", date: "20 Jun 2013", text: "Uttarakhand government ignored Met warning", from: at(0), to: at(1), x: 170, y: 170, w: 980, rot: -3, seed: 4 },
        { type: "cut", outlet: "The Kathmandu Post", date: "2 Sep 2026", text: "Nepal sent its disaster alert 38 minutes after the glacier collapse. It wasn't enough", from: ch(0, 1), to: at(1), x: 760, y: 470, w: 1000, rot: 2, seed: 8 },
        { type: "text", cls: "eyebrow", html: "Rasuwa, Nepal · 26 August 2026", from: at(1), to: at(4), x: 170, y: 120, size: 24, anim: "rise" },
        { type: "timeline", from: at(1), to: at(4), t0: 8 * 60 + 25, t1: 10 * 60 + 5, x: 170, y: 520, w: 1580, events: [
          { m: 8 * 60 + 37, time: "8:37", text: "Ice and rock collapse", at: 0.3 },
          { m: 8 * 60 + 50, time: "8:50", text: "River gauge swept away", at: 1.0 },
          { m: 9 * 60 + 15, time: "9:15", text: "Mass alert SMS sent,\n*in Nepali only*", at: ch(1, 2) - at(1) },
          { m: 9 * 60 + 54, time: "9:54", text: "“The SMS and the flood\ncame together”", at: at(3) - at(1) },
        ], bracket: [8 * 60 + 37, 9 * 60 + 15, "38 minutes"], bracketAt: ch(1, 2) - at(1) + 0.5 },
        { type: "tag", html: "Sources: Kathmandu Post, 27 Aug & 2 Sep 2026 · Mongabay, 7 Sep 2026 (a Nuwakot resident; the 9:35 text arrived at 9:54)", from: at(1) + 1, to: at(4), pos: { left: "170px", top: "868px" } },
        { type: "stat", text: "1 in 3", count: false, value: 0, label: "people in India say warnings of extreme weather\n*don't reach them*", source: "Yale Program on Climate Change Communication & CVoter, 2023 survey", from: at(4), to: at(5), x: 150, y: 300, w: 1500, size: 230 },
        { type: "quote", text: "A warning cannot be considered effective until it is received, understood and responded to by those at risk.", who: "Cumiskey et al., 2015", source: "a field study of flash-flood warnings in Sunamganj, Bangladesh", from: at(5), to: dur, x: 200, y: 250, size: 68, span: 2.4 },
      ],
      sfx: [{ name: "paper_slam", t: at(0), gain: -9 }, { name: "paper_slam", t: ch(0, 1), gain: -10 }, { name: "clock", t: at(1) + 0.3, gain: -10 }, { name: "clock", t: at(1) + 1.0, gain: -10 }, { name: "clock", t: ch(1, 2), gain: -10 }, { name: "hit", t: ch(1, 2) - at(1) + at(1) + 0.5, gain: -16 }, { name: "chime", t: at(3) - 0.5, gain: -18 }],
    };
    case "hope": return {
      layers: [
        { type: "clip", name: "dawn", from: 0, to: dur, grade: { b: 0.85, c: 1.05, s: 1.05 }, kb: { s: [1.02, 1.1] } },
        { type: "text", html: "And yet, this can be *fixed.*", from: at(0), to: at(1), x: 150, y: 420, size: 124, stagger: 0.12 },
        { type: "bg", style: "night", from: at(1), to: dur, fadeIn: 0.5 },
        { type: "bars", from: at(1), to: at(2), x: 170, y: 230, w: 1500, rows: [
          { title: "Weather, climate and water disasters, 1970s → 2010s", value: "×5", note: "more disasters (part of it is better reporting)", color: "linear-gradient(90deg,#3b6b93,#8ad0ff)", w0: 90, w1: 450, at: 0.3 },
          { title: "Deaths", value: "50,000+ → under 20,000", note: "fewer deaths: *better early warning and disaster management*", color: "linear-gradient(90deg,#1f8fd6,#4fb3ff)", w0: 520, w1: 200, at: ch(1, 1) - at(1) },
        ], source: "WMO, Atlas of Mortality and Economic Losses, 1970–2019 (31 Aug 2021)" },
        { type: "stat", value: 1.5, decimals: 1, suffix: " million", label: "people moved in a day before *Cyclone Fani*, Odisha 2019.\n64 died. In 1999, nearly 10,000 had.", source: "Fani Post-Disaster Needs Assessment, Govt of Odisha, 2019", from: at(2), to: dur, x: 150, y: 300, w: 1600, size: 200 },
      ],
      sfx: [{ name: "swell", t: at(0) - 1.2, gain: -14 }],
    };
    case "school": return {
      layers: [
        { type: "clip", name: "nepal-valley", from: 0, to: dur, grade: { b: 0.75, c: 1.05, s: 1 }, kb: { s: [1.02, 1.08] }, tag: "Nepal · illustrative footage, not the school" },
        { type: "cut", outlet: "Reuters", date: "31 Aug 2026", text: "Last-minute flood warning saved over 900 Nepal students, school head says", from: 0.3, to: at(1) + 0.2, x: 330, y: 330, w: 1100, rot: -2, seed: 12 },
        { type: "stat", value: 900, suffix: "+", label: "students up the hill.\n“Stop the class, *ring the bell.*”", source: "Head teacher Rajendra Dawadi, to Reuters · 31 Aug 2026", from: at(1), to: at(2), x: 150, y: 290, w: 1500, size: 220 },
        { type: "text", html: "in time,\nin *their own language.*", from: at(2) + 0.2, to: dur, x: 150, y: 380, size: 120, times: [0, 0.25, ch(2, 3) - at(2) - 0.2, ch(2, 3) - at(2), ch(2, 3) - at(2) + 0.2, ch(2, 3) - at(2) + 0.4] },
      ],
      sfx: [{ name: "paper_slam", t: 0.3, gain: -9 }, { name: "bell", t: ch(1, 0) - 0.3, gain: -15 }, { name: "riser", t: dur - 2.2, gain: -12 }],
    };
    case "pukaar": return {
      layers: [
        { type: "clip", name: "barot", from: 0, to: dur + 0.3, grade: { b: 0.4, c: 1.1, s: 0.8 }, tint: "rgba(6,17,31,.45)", kb: { s: [1.0, 1.06] }, tag: "Barot valley, Mandi district", tagPos: { left: "56px", top: "960px" } },
        { type: "valley", from: 0, to: dur + 0.3, y: 700, draw: 1.6 },
        { type: "logo", from: 0.1, to: dur + 0.3, y: 230, tagline: "The call that reaches the village *before the river does.*", taglineAt: at(1) - 0.2 },
      ],
      sfx: [{ name: "hit", t: 0.12, gain: -8 }],
      flashes: [{ t: 0.1, d: 0.45, a: 0.4 }],
    };
    case "sweep": return {
      layers: [
        { type: "bg", style: "paper" },
        { type: "live", cap: "live", from: 0, to: at(1) + 0.1, zoom: [{ t: 1.4, dur: 1.2, s: 1.15, cx: 640, cy: 520 }], tag: "Amazon EventBridge Scheduler → AWS Lambda · every 15 min" },
        { type: "live", cap: "sensors", from: at(1), to: dur, zoom: [{ t: 0.2, dur: 2.5, s: 1.12 }], tag: "River gauges · <b>AWS IoT Core</b> (MQTT) → rules → Lambda" },
      ],
      sfx: [{ name: "whoosh", t: -0.3, gain: -14 }, { name: "tick", t: at(1), gain: -16 }],
    };
    case "rules": return {
      layers: [
        { type: "bg", style: "paper" },
        { type: "live", cap: "story", from: 0, to: dur, tag: "Rules in code: <b>IMD rain bands</b> · each village's <b>1984–2024 river record</b>" },
      ],
      sfx: [{ name: "tick", t: 0.2, gain: -16 }],
    };
    case "draft": {
      const m = c.captures.agents.marks.chips;
      return {
        layers: [
          { type: "bg", style: "paper" },
          { type: "live", cap: "agents", from: 0, to: dur, zoom: m ? [{ t: at(1) - 0.3, dur: 1.0, s: 1.7, cx: m[0] + m[2] / 2, cy: m[1] + m[3] / 2 + 20 }] : [], boxes: m ? [{ from: at(1) + 0.6, to: dur, rect: [m[0], m[1], m[2], m[3] + 40], pad: 10 }] : [], tag: "Amazon Bedrock drafts · a checker and a fixed template stand by", tagPos: { left: "150px", top: "880px" } },
          { type: "tag", html: "Shown live: <b>fixed Hindi template while model access is pending</b>", from: at(1) + 0.8, to: dur, pos: { right: "150px", bottom: "190px" } },
        ],
        sfx: [{ name: "tick", t: at(1) + 0.6, gain: -15 }],
      };
    }
    case "approve": return {
      layers: [
        { type: "bg", style: "night" },
        { type: "live", cap: "console", from: 0, to: dur, area: { x: 90, y: 110, w: 1120, h: 630 }, offset: -0.1, tag: "Officer console · signed in with Cognito · <b>a real approval</b>", tagPos: { left: "90px", top: "800px" },
          zoom: c.captures.console.marks.card ? [{ t: 0.3, dur: 1.0, s: 1.25, cx: c.captures.console.marks.card[0] + c.captures.console.marks.card[2] / 2, cy: c.captures.console.marks.card[1] + 260 }, { t: 2.1, dur: 0.6, s: 1, cx: 800, cy: 450 }] : [] },
        { type: "phone", mode: "push", from: 0.2, to: dur, x: 1330, y: 140, clock: "02:14", date: "Thursday, 9 July", notifAt: 0.7,
          title: "पुकार: गोहर गंभीर ख़तरा", body: "पुकार: गोहर के लिए गंभीर ख़तरा। तुरंत नदी-नालों और ढलानों से दूर ऊँची, सुरक्षित जगह पर जाएँ।…\n10 मिनट में मंज़ूरी दें · Approve within 10 min", actions: ["✓ मंज़ूर", "✕ नहीं"],
          label: "Illustration of Pukaar's Web Push approval<small>text and buttons from the backend payload</small>", labelAt: 1.0 },
        { type: "tag", html: "<b>AWS Step Functions</b> waits for the tap · no answer in 10 min → the next officer", from: at(1), to: dur, pos: { left: "90px", top: "870px" } },
      ],
      sfx: [{ name: "chime", t: 0.7, gain: -12 }, { name: "tap", t: 2.2, gain: -8 }, { name: "tap", t: 3.3, gain: -8 }],
    };
    case "voice": return {
      layers: [
        { type: "bg", style: "paper" },
        { type: "live", cap: "village", from: 0, to: dur, offset: 0, zoom: [{ t: 0.3, dur: 1.4, s: 1.25, cx: (c.captures.village.marks.card?.[0] ?? 400) + (c.captures.village.marks.card?.[2] ?? 800) / 2, cy: (c.captures.village.marks.card?.[1] ?? 300) + (c.captures.village.marks.card?.[3] ?? 200) / 2 }], tag: "Amazon Polly · Kajal · hi-IN · <b>the real alert audio</b>" },
        { type: "text", cls: "abs", anim: "rise", html: "पुकार: गोहर के लिए गंभीर ख़तरा। तुरंत नदी-नालों और ढलानों से दूर ऊँची, सुरक्षित जगह पर जाएँ।", from: end(0) + 0.3, to: dur, x: 160, y: 760, w: 1600, size: 44, style: "font-family:var(--display);line-height:1.45;color:#0b1f33;background:rgba(255,255,255,.94);padding:22px 30px;border-radius:16px;box-shadow:0 20px 50px rgba(11,31,51,.25)" },
      ],
      sfx: [],
    };
    case "telegram": {
      const audio = `<div class="bub"><div class="aud"><div class="pl"><svg width="20" height="20" viewBox="0 0 20 20"><path d="M5 3l12 7-12 7z" fill="#fff"/></svg></div><div class="wv">${Array.from({ length: 26 }, (_, i) => `<i style="height:${8 + Math.round(Math.abs(Math.sin(i * 1.7) * 26))}px"></i>`).join("")}</div><div class="ti"><b>पुकार</b>0:13</div></div><div class="txt">पुकार: गोहर के लिए गंभीर ख़तरा। तुरंत नदी-नालों और ढलानों से दूर ऊँची, सुरक्षित जगह पर जाएँ। पुल और नाले पार न करें।…</div><div class="meta">02:16</div></div>`;
      const kb = `<div class="kb"><div class="btn">✓ मिल गया</div></div>`;
      return {
        layers: [
          { type: "bg", style: "night" },
          { type: "phone", mode: "chat", from: 0, to: dur, x: 330, y: 130, msgs: [{ html: audio, at: 0.4 }, { html: kb, at: 0.7 }], tapAt: ch(1, 0) - 0.1, toast: "धन्यवाद, दर्ज हो गया।", toastAt: ch(1, 0) + 0.1, playAt: 0.6, playDur: 7,
            label: "Phone A taps “मिल गया”<small>the tap comes back through API Gateway</small>" },
          { type: "phone", mode: "chat", from: 0.4, to: dur, x: 1160, y: 130, msgs: [{ html: audio, at: 0.6 }, { html: kb, at: 0.8 }, { html: `<div class="chip">दोबारा भेजा · Re-sent</div>`, at: at(2) + 0.4 }, { html: audio.replace("02:16", "02:21"), at: at(2) + 0.6 }],
            label: "Phone B doesn't tap<small>after 5 min, Step Functions sends it again</small>", labelAt: at(2) },
          { type: "tag", html: "Reproduction of the bot's message (text and button from the backend) · not a screen recording", from: 0.3, to: dur, pos: { left: "790px", top: "430px", width: "340px", whiteSpace: "normal", textAlign: "center", borderRadius: "18px" } },
        ],
        sfx: [{ name: "chime", t: 0.45, gain: -12 }, { name: "tap", t: ch(1, 0) - 0.1, gain: -8 }, { name: "chime", t: at(2) + 0.5, gain: -13 }],
      };
    }
    case "stopwatch": {
      const m = c.captures.village.marks.tte;
      return {
        layers: [
          { type: "bg", style: "paper" },
          { type: "live", cap: "village", from: 0, to: dur, offset: 10, zoom: m ? [{ t: 0.2, dur: 1.2, s: 1.35, cx: m[0] + m[2] / 2, cy: m[1] + m[3] / 2 }] : [], boxes: m ? [{ from: 1.3, to: dur, rect: m, dim: 0 }] : [], tag: "Time to ear: from the river rising to the first “मिल गया”" },
        ],
        sfx: [{ name: "clock", t: 0.3, gain: -12 }, { name: "clock", t: 0.9, gain: -12 }],
      };
    }
    case "safe": {
      const rc = `पुकार: क्या आप सुरक्षित हैं? / Are you safe?\nगोहर · Gohar\nएक बटन दबाएँ। इससे फ़ोन लाइनें खाली रहती हैं और अधिकारी जानते हैं कि किसे मदद चाहिए।`;
      return {
        layers: [
          { type: "bg", style: "night" },
          { type: "phone", mode: "chat", from: 0, to: at(1) + 0.3, x: 745, y: 130, msgs: [{ html: `<div class="bub"><div class="txt" style="white-space:pre-line">${rc}</div><div class="meta">03:40</div></div>`, at: 0.3 }, { html: `<div class="kb"><div class="btn">✓ मैं सुरक्षित हूँ</div><div class="btn" style="color:#9c0d2f">मदद चाहिए</div></div>`, at: 0.55 }], tapAt: end(0) - 0.2,
            label: "“Surakshit Hoon” roll-call · reproduction<small>text and buttons from the backend</small>" },
          { type: "bg", style: "paper", from: at(1), to: dur },
          { type: "live", cap: "safe", from: at(1), to: dur, zoom: [{ t: 0.3, dur: 1.5, s: 1.1 }], tag: "Safe places from OpenStreetMap · walking routes · <b>road blocks</b> marked by officers" },
        ],
        sfx: [{ name: "chime", t: 0.3, gain: -13 }, { name: "tap", t: end(0) - 0.2, gain: -9 }, { name: "whoosh_short", t: at(1) - 0.2, gain: -15 }],
      };
    }
    case "report": return {
      layers: [
        { type: "bg", style: "paper" },
        { type: "livephone", cap: "report", from: 0, to: dur, x: 300, y: 120, label: "<span style='color:#0b1f33'>The live report page, phone-sized</span>" },
        { type: "roadmap", light: true, from: 0.4, to: dur, x: 900, y: 220, w: 900, items: [
          { icon: "voice", t: "Voice, photo or text", s: "works offline; sends when the signal returns", at: 0.3 },
          { icon: "sms", t: "Amazon Transcribe", s: "turns a voice report into text", at: ch(0, 1) - 0.2 },
          { icon: "link", t: "Bedrock Guardrails", s: "screen every word before an agent reads it", at: at(1) },
        ] },
      ],
      sfx: [{ name: "whoosh_short", t: -0.2, gain: -15 }],
    };
    case "aws": {
      const l1 = c.tl.lines[1], l2 = c.tl.lines[2];
      const pos = (line, word) => line.start + (line.say.replace(/\|/g, "").indexOf(word) / line.say.replace(/\|/g, "").length) * (line.end - line.start) - 0.15;
      return {
        layers: [{ type: "arch", from: 0, to: dur, nodes: ARCH.nodes, edges: ARCH.edges, title: "One serverless stack", allAt: end(2) + 0.2, steps: [
          { t: pos(l1, "EventBridge"), on: ["eb", "sweep", "meteo"], title: "EventBridge and Lambda", dist: 15 },
          { t: pos(l1, "IoT"), on: ["iot", "sweep"], title: "AWS IoT Core", dist: 14 },
          { t: pos(l1, "DynamoDB"), on: ["sweep", "ddb"], title: "DynamoDB", dist: 14 },
          { t: pos(l1, "Step"), on: ["sfn", "apigw"], title: "Step Functions", dist: 15 },
          { t: pos(l2, "Bedrock"), on: ["sfn", "bedrock"], title: "Bedrock + Guardrails", dist: 15 },
          { t: pos(l2, "Polly"), on: ["bedrock", "polly", "s3"], title: "Polly", dist: 15 },
          { t: pos(l2, "Transcribe"), on: ["apigw", "transcribe", "s3"], title: "Transcribe", dist: 16 },
          { t: pos(l2, "AppSync"), on: ["appsync", "ddb"], title: "AppSync live push", dist: 17 },
          { t: pos(l2, "Cognito"), on: ["apigw", "cognito"], title: "Cognito", dist: 16 },
          { t: pos(l2, "S3"), on: ["s3", "polly"], title: "S3", dist: 15 },
          { t: pos(l2, "CloudWatch"), on: ["cw", "ddb", "sfn"], title: "CloudWatch", dist: 18 },
        ] }],
        sfx: [{ name: "whoosh", t: -0.3, gain: -13 }],
      };
    }
    case "trust": {
      const d = c.captures.audit.marks.deny;
      return {
        layers: [
          { type: "bg", style: "paper" },
          { type: "live", cap: "audit", from: 0, to: at(1) + 0.2, boxes: d ? [{ from: 0.9, to: at(1) + 0.2, rect: d }] : [], tag: "Cedar policy: a village pradhan's approval <b>denied</b>, with the reason" },
          { type: "bg", style: "night", from: at(1), to: dur },
          { type: "stat", value: f.stack.alarms, label: "Amazon CloudWatch alarms on the stack", source: `read from the live account (stack pukaar-dev) at render time`, from: at(1), to: at(2), x: 150, y: 330, w: 1400, size: 230 },
          { type: "term", from: at(2), to: dur, x: 160, y: 120, w: 1600, h: 760, title: "curl -s https://362iqe4oae.execute-api.us-east-1.amazonaws.com/cap/alerts.atom", lines: c.env.cap, rate: 14, rows: 18 },
        ],
        sfx: [{ name: "tick", t: 0.9, gain: -14 }, { name: "hit", t: at(1) + 0.1, gain: -18 }],
      };
    }
    case "next": return {
      layers: [
        { type: "bg", style: "night" },
        { type: "valley", from: 0, to: dur, y: 760, opacity: 0.8, draw: 3 },
        { type: "text", cls: "eyebrow", html: "We keep building · what AWS adds next", from: 0.1, to: at(3) - 0.1, x: 150, y: 96, size: 26, anim: "rise" },
        { type: "roadmap", from: 0, to: at(3) - 0.1, x: 150, y: 160, w: 1620, items: [
          { icon: "gauge", t: "Built: river gauges on *AWS IoT Core*", s: "MQTT, one X.509 certificate per gauge; a reading at a danger mark raises the level by itself (simulated until hardware is installed)", at: at(0) },
          { icon: "radio", t: "*AWS IoT Core for LoRaWAN*", s: "long-range radio for bridges with no phone signal", at: at(1) },
          { icon: "chip", t: "*AWS IoT Greengrass* at the gauge", s: "a local siren that still works when the network is down", at: ch(1, 2) },
          { icon: "chart", t: "*Amazon SageMaker* with *Amazon Timestream*", s: "every reading kept; each river's warning signs learned from its own record", at: ch(1, 3) },
          { icon: "phone", t: "Calls and SMS to basic phones, India's national alert system (SACHET over CAP 1.2)", s: `*AWS End User Messaging* · *Amazon Location Service* for live routes · ${f.villages} villages to the Himalayan states and Nepal`, at: at(2) },
        ] },
        { type: "text", html: "We want to build this *to scale*,\nuntil every village hears it *in time.*", from: at(3), to: dur, x: 150, y: 330, size: 104, stagger: 0.1 },
      ],
      sfx: [],
    };
    case "close": return {
      layers: [
        { type: "bg", style: "black", fadeIn: 0 },
        { type: "text", html: "The warning that night\nwas a *dog.*", from: at(0), to: at(1), x: 150, y: 360, size: 124, stagger: 0.12 },
        { type: "clip", name: "kullu", from: at(1) - 0.1, to: end(1) + 1.0, grade: { b: 0.75, c: 1.05, s: 1 }, kb: { s: [1.02, 1.1] }, tag: "Kullu district, Himachal Pradesh", tagPos: { left: "56px", top: "960px" } },
        { type: "text", html: "Next time, it should be *a call*,\nin their own language,\nthat someone *confirms* they heard.", from: at(1), to: end(1) + 0.75, x: 150, y: 300, size: 92, times: [0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, ch(1, 1) - at(1), ch(1, 1) - at(1) + 0.15, ch(1, 1) - at(1) + 0.3, ch(1, 1) - at(1) + 0.45, ch(1, 2) - at(1), ch(1, 2) - at(1) + 0.15, ch(1, 2) - at(1) + 0.3, ch(1, 2) - at(1) + 0.45, ch(1, 2) - at(1) + 0.6] },
        { type: "bg", style: "night", from: end(1) + 0.75, to: dur, fadeIn: 0.5, fadeOut: 0 },
        { type: "valley", from: end(1) + 1.0, to: dur, y: 800, opacity: 0.6, draw: 2.5, fadeOut: 0.01 },
        { type: "end", from: end(1) + 1.1, to: dur, tagline: "The call that reaches the village *before the river does.*", url: f.liveUrl.replace("https://", ""), repo: "github.com/Prashant-thakur77/pukaar", meta: "Built on AWS · footage, image and source credits in the description", fadeOut: 0.01 },
      ],
      sfx: [{ name: "hit", t: end(1) + 1.1, gain: -10 }],
    };
  }
  return { layers: [] };
}

const ARCH = {
  nodes: [
    { id: "eb", name: "EventBridge Scheduler", detail: "every 15 min", x: -11, z: -4, kind: "aws" },
    { id: "meteo", name: "Open-Meteo", detail: "rain + river forecasts", x: -11, z: 1, kind: "ext" },
    { id: "iot", name: "AWS IoT Core", detail: "river gauges · MQTT", x: -11, z: 5.5, kind: "aws" },
    { id: "sweep", name: "Lambda · sweep", detail: "level by rule", x: -6.5, z: -1, kind: "aws" },
    { id: "ddb", name: "DynamoDB", detail: "conditional writes", x: -6.5, z: 4.5, kind: "aws" },
    { id: "sfn", name: "Step Functions", detail: "one-tap approval", x: -2, z: -4, kind: "aws" },
    { id: "bedrock", name: "Bedrock · Guardrails", detail: "draft · checker · screen", x: -2, z: 1.5, kind: "aws" },
    { id: "cw", name: "CloudWatch", detail: "alarms · dashboard", x: -2, z: 6.5, kind: "aws" },
    { id: "polly", name: "Polly", detail: "Kajal · hi-IN", x: 2.5, z: 1.5, kind: "aws" },
    { id: "s3", name: "S3", detail: "audio · photos", x: 2.5, z: 6, kind: "aws" },
    { id: "apigw", name: "API Gateway · Lambda", detail: "FastAPI", x: 2.5, z: -4, kind: "aws" },
    { id: "transcribe", name: "Transcribe", detail: "voice reports", x: 6.5, z: 5, kind: "aws" },
    { id: "cognito", name: "Cognito · Cedar", detail: "sign-in · policy · audit", x: 6.5, z: -6.5, kind: "aws" },
    { id: "appsync", name: "AppSync", detail: "live push", x: 7, z: -1.5, kind: "aws" },
    { id: "tg", name: "Telegram", detail: "voice + मिल गया", x: 10.5, z: 1.5, kind: "ext" },
    { id: "phone", name: "Village phones", detail: "hear · confirm · report", x: 12, z: 5, kind: "phone" },
  ],
  edges: [["eb", "sweep"], ["meteo", "sweep"], ["iot", "sweep"], ["sweep", "ddb"], ["sweep", "sfn"], ["sfn", "bedrock"], ["bedrock", "polly"], ["polly", "s3"],
    ["sfn", "apigw"], ["apigw", "cognito"], ["sfn", "tg"], ["tg", "phone"], ["phone", "apigw"], ["apigw", "transcribe"], ["transcribe", "s3"], ["ddb", "appsync"], ["appsync", "apigw"], ["ddb", "cw"], ["sfn", "cw"]],
};

export const lightRanges = (startOf) => [[startOf("sweep"), startOf("approve")], [startOf("voice"), startOf("telegram")], [startOf("stopwatch"), startOf("safe")], [startOf("report"), startOf("aws")]];
export const posterAt = (startOf) => startOf("pukaar") + 3.2;

export function score(startOf, T) {
  const s = (a, b, mood, gain_db = 0) => ({ from: startOf(a), to: b ? startOf(b) : T, mood, gain_db });
  return {
    sections: [s("night", "scale", "night", 0), s("scale", "fail", "sombre", -1), s("fail", "hope", "tense", -2), s("hope", "pukaar", "hope", 0),
      s("pukaar", "aws", "drive", -1), s("aws", "next", "build", 0), s("next", "close", "reflect", 0), s("close", null, "resolve", 2)],
    hits: [startOf("pukaar") + 0.12],
    drops: [[startOf("pukaar") - 0.7, 0.75]],
  };
}

export const SOURCES = [
  ["Syathi, 30 Jun 2025: “more than 60 people”, “20 households”; Mohan's quote", "The Tribune, “Pet dog emerges saviour in Mandi village, saves 60 lives amid monsoon fury”, 9 Jul 2025", "https://www.tribuneindia.com/news/himachal/pet-dog-emerges-saviour-in-mandi-village-saves-60-lives-amid-monsoon-fury"],
  ["Red alert for Mandi district, 30 Jun 2025", "ANI via The News Mill, “Red alert issued in Mandi district of Himachal Pradesh, Beas river flooded after heavy rainfall”, 30 Jun 2025", "https://thenewsmill.com/2025/06/red-alert-issued-in-mandi-district-of-himachal-pradesh-beas-river-flooded-after-heavy-rainfall/"],
  ["169 floods a year (2005–2024 average), the most frequent disaster", "CRED / UCLouvain, EM-DAT, 2025 Disasters in Numbers", "https://files.emdat.be/reports/2025_EMDAT_report.pdf"],
  ["1.81 billion people exposed to 1-in-100-year floods; 390 million in India", "Rentschler, Salhab & Jafino, Nature Communications 13, 3527 (2022)", "https://pmc.ncbi.nlm.nih.gov/articles/PMC9240081/"],
  ["Himachal Pradesh, monsoon 2023: more than 500 lives lost", "Govt of Himachal Pradesh / HPSDMA with NDMA, Post-Disaster Needs Assessment, Monsoon 2023", "https://recovery.preventionweb.net/publication/report-post-disaster-needs-assessment-himachal-pradesh-monsoon-2023-floods-cloudbursts"],
  ["Uttarakhand, June 2013: 580 dead, 5,474 missing (6,054)", "Ministry of Home Affairs, Rajya Sabha Unstarred Q. 388, 7 Aug 2013", "https://www.mha.gov.in/MHA1/Par2017/pdfs/par2013-pdfs/rs-070813/388.pdf"],
  ["Sikkim, 4 Oct 2023: 55 dead, 74 missing", "Sattar et al., “The Sikkim flood of October 2023”, Science 387 (2025)", "https://eprints.whiterose.ac.uk/id/eprint/224098/"],
  ["Nepal, 26 Aug 2026: 1,451 dead, 5,745 missing (as of 21 Sep 2026)", "NDRRMA, Rasuwa-Bhotekoshi Flood SitRep #20, 21 Sep 2026", "https://ndrrma.gov.np/mediafiles/rasuwa/SitRep_ENG_20_21092026.pdf"],
  ["Rasuwa timeline: 8:37 collapse, 8:50 gauge offline, 9:15 mass SMS (38 minutes)", "The Kathmandu Post, 27 Aug 2026 and 2 Sep 2026", "https://kathmandupost.com/national/2026/09/02/nepal-sent-its-disaster-alert-38-minutes-after-the-glacier-collapse-it-wasn-t-enough"],
  ["“The SMS and the flood came together”; Nepali-only text", "Mongabay India, “Community-based warning saves lives during Nepal floods”, 7 Sep 2026", "https://india.mongabay.com/2026/09/community-based-warning-saves-lives-during-nepal-floods/"],
  ["Uttarakhand 2013 warnings", "Down To Earth, “Uttarakhand government ignored Met warning”, 20 Jun 2013", "https://www.downtoearth.org.in/environment/uttarakhand-government-ignored-met-warning-41421"],
  ["1 in 3 people in India say they get no warning", "Yale Program on Climate Change Communication & CVoter, Climate Change in the Indian Mind 2023", "https://climatecommunication.yale.edu/publications/climate-change-in-the-indian-mind-2023/toc/4"],
  ["“A warning cannot be considered effective until…” (a Bangladesh field study)", "Cumiskey et al., Int. J. Disaster Resilience in the Built Environment 6(1), 2015, doi:10.1108/IJDRBE-08-2014-0062", "https://doi.org/10.1108/IJDRBE-08-2014-0062"],
  ["Disasters ×5, deaths from over 50,000 (1970s) to under 20,000 (2010s)", "WMO, Atlas of Mortality and Economic Losses from Weather, Climate and Water Extremes (1970–2019), 31 Aug 2021", "https://wmo.int/media/news/weather-related-disasters-increase-over-past-50-years-causing-more-damage-fewer-deaths"],
  ["Odisha, Cyclone Fani 2019: 1.5 million moved in 24 hours; 64 dead; nearly 10,000 in 1999", "Govt of Odisha, Cyclone Fani Post-Disaster Needs Assessment, 2019", "https://www.preventionweb.net/publication/fani-cyclone-odisha-post-disaster-needs-assessment"],
  ["Trishuli school, 26 Aug 2026: over 900 students; “Stop the class, ring the bell”", "Reuters, “Last-minute flood warning saved over 900 Nepal students, school head says”, 31 Aug 2026", "https://www.internazionale.it/ultime-notizie-reuters/2026/08/31/last-minute-flood-warning-saved-over-900-nepal-students-school-head-says"],
  ["SACHET is India's CAP-based Integrated Alert System", "PIB (MHA), “Glacial Lake Outburst Flood Mitigation”, 1 Apr 2025", "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2117268"],
];

export function creditsMd({ facts, chapters }) {
  const items = JSON.parse(readFileSync(join(ROOT, "video/pitch-media.json"), "utf8")).items;
  const mmss = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
  return `# Pukaar pitch video: description and credits

Paste-ready for the YouTube description of docs/media/pukaar-pitch.mp4. Written by \`node video/record.mjs pitch\`.

\`\`\`
Pukaar (पुकार): the call that reaches the village before the river does. A flood early-warning loop for Himalayan villages in Mandi district, Himachal Pradesh, live on AWS.

Live: ${facts.liveUrl}
Code: https://github.com/Prashant-thakur77/pukaar

${chapters.map((c) => `${mmss(c.from)} ${c.label}`).join("\n")}
\`\`\`

## Honesty notes
- The live-site scenes are screenshots of the deployed site captured at render time. The lock-screen approval and the Telegram chats are labelled reproductions built from the exact text and buttons in the backend code; they are not screen recordings.
- Footage marked "illustrative" is stock and does not show the event being described.
- The drafting agent's page shows its real state: Bedrock model access is pending, so drafts use the fixed Hindi template.
- Headline cuts quote headlines as published, in neutral type; no mastheads, logos, layouts or photos are reproduced.

## Sources behind every number and headline on screen
${SOURCES.map(([what, src, url]) => `- ${what}: ${src}. ${url}`).join("\n")}
- CloudWatch alarm count (${facts.stack.alarms}): read from the live AWS account (stack pukaar-dev) at render time.

## Images and footage
${items.map((it) => `- ${it.what}: ${it.credit}. ${it.license}. ${it.page}`).join("\n")}

## Sound
- Narration: Chatterbox TTS (open source) with its own built-in synthetic voice; no real person's voice is cloned.
- The Hindi alert: the real Amazon Polly (Kajal, hi-IN) MP3 for the Gohar alert, from the live stack.
- Music: an original score synthesised for this video by video/narration/score.py. CC0 1.0.
- Sound effects (rain, thunder, river, paper, whooshes, chime, ticks, bell): synthesised from scratch by video/narration/sfx.py. CC0 1.0. The notification chime is a neutral two-note tone, not any app's sound.
`;
}
