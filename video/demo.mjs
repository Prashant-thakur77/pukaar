// The demo video (under three minutes, the Environmental Hacks limit): hook, problem, the turn, the Gohar story on the
// landing page, the live loop on AWS (map, officer approval, the real Polly voice, time to ear, a villager report), the
// architecture in 3D, live AWS proof, what it does not do yet, and the close.
//   node video/record.mjs demo [--plan] [--only a,b] [--preview]
// Live scenes run against the deployed stack while a replay is running there (video/live.mjs starts it).
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { L as L0, ROOT } from "./lib/engine.mjs";

/** A narration line, with the name respelled for the voice only (Chatterbox read "Pukaar" as "Bukhar"). */
const L = (text, say = text, opts = {}) => L0(text, say.replace(/Pukaar/g, "Poo-kaar"), opts);
import { REGION, STACK } from "./lib/facts.mjs";

const NUM = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
  "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"];
const TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];
/** 72 -> "seventy-two" (what Chatterbox reads; the caption keeps the digits). */
export function sayInt(n) {
  if (n < 20) return NUM[n];
  if (n < 100) return TENS[Math.floor(n / 10)] + (n % 10 ? `-${NUM[n % 10]}` : "");
  return `${NUM[Math.floor(n / 100)]} hundred${n % 100 ? ` ${sayInt(n % 100)}` : ""}`;
}
const sayDec = (x) => {
  const [a, b] = String(x).split(".");
  return b ? `${sayInt(Number(a))} point ${[...b].map((d) => NUM[Number(d)]).join(" ")}` : sayInt(Number(a));
};

/** The officer's demo password, from the git-ignored .env.demo.local; never printed. */
function demoPassword() {
  const env = readFileSync(join(ROOT, ".env.demo.local"), "utf8");
  const m = env.match(/^PUKAAR_DEMO_PASSWORD=(.+)$/m);
  if (!m) throw new Error(".env.demo.local has no PUKAAR_DEMO_PASSWORD");
  return m[1].trim().replace(/^["']|["']$/g, "");
}

async function openApp(page, f, path, ready) {
  await page.goto(f.liveUrl + path, { waitUntil: "domcontentloaded" });
  if (ready) await ready();
}

async function signIn(page, f) {
  await openApp(page, f, "/login");
  await page.locator('input[autocomplete="username"]').fill("officer1");
  await page.locator('input[type="password"]').fill(demoPassword());
  await page.locator('form button[type="submit"]').click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
}

/** A labelled card dropped into a live page (the hero user, or a note on what is real). */
async function overlay(page, html, pos = "left") {
  await page.evaluate(
    ([html, pos]) => {
      const d = document.createElement("div");
      d.className = "__vbox";
      d.innerHTML = html;
      Object.assign(d.style, {
        position: "fixed", zIndex: 2147483001, [pos === "left" ? "left" : "right"]: "48px", bottom: "190px",
        background: "#fff", color: "#141a33", border: "3px solid #141a33", boxShadow: "9px 9px 0 #141a33",
        borderRadius: "12px", padding: "18px 24px", font: "700 28px/1.25 Inter, sans-serif", maxWidth: "620px",
        opacity: "0", transform: "translateY(12px)", transition: "all 300ms cubic-bezier(0.16,1,0.3,1)",
      });
      // on <html>, not <body>: the camera zoom transforms <body>, which would carry a fixed card off screen
      document.documentElement.appendChild(d);
      requestAnimationFrame(() => requestAnimationFrame(() => Object.assign(d.style, { opacity: "1", transform: "none" })));
    },
    [html, pos],
  );
}

/** What the live stack shows right now, for the proof scene (run at render time; read-only). */
function awsProof(f) {
  const sh = (cmd, args) => execFileSync(cmd, args, { encoding: "utf8" });
  const ex = JSON.parse(
    sh("aws", ["stepfunctions", "list-executions", "--state-machine-arn", f.stack.stateMachine, "--max-results", "4",
      "--region", REGION, "--output", "json"]),
  ).executions;
  const bucket = JSON.parse(
    sh("aws", ["cloudformation", "describe-stack-resources", "--stack-name", STACK, "--region", REGION, "--output", "json"]),
  ).StackResources.find((r) => r.ResourceType === "AWS::S3::Bucket").PhysicalResourceId;
  const mp3 = sh("aws", ["s3", "ls", `s3://${bucket}/audio/alerts/`, "--region", REGION]).trim().split("\n").slice(-2);
  const health = JSON.parse(sh("curl", ["-s", `${f.apiUrl}/health`]));
  const hhmm = (d) => new Date(d).toISOString().slice(11, 19);
  return {
    groups: [
      {
        cmd: "aws stepfunctions list-executions --state-machine-arn …:pukaar-approval-dev",
        out: ex.map((e) => `${e.name.slice(0, 34).padEnd(36)}${e.status.padEnd(11)}${hhmm(e.startDate)} UTC`),
        hot: [0],
      },
      {
        cmd: `aws s3 ls s3://${bucket.slice(0, 22)}…/audio/alerts/`,
        out: mp3.map((l) => l.replace(/\s+/g, "  ")),
        hot: [mp3.length - 1],
      },
      {
        cmd: "curl -s https://362iqe4oae.execute-api.us-east-1.amazonaws.com/health",
        out: [
          `status: ${health.status}   mode: ${health.mode}   workflow: ${health.workflow}`,
          `dynamodb: ${health.services.dynamodb}   polly: ${health.services.polly}   telegram: ${health.services.telegram}`,
        ],
        hot: [0],
      },
    ],
    stamp: `Captured from the live account at ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC`,
  };
}

/** The real Polly voice for the Gohar alert, and the AWS proof captured now. */
export async function probe(_browser, f) {
  const voice = join(ROOT, "video/.out/polly-gohar.mp3");
  if (process.argv.includes("--plan")) return { voice, proof: { groups: [], stamp: "" } };
  if (!existsSync(voice)) throw new Error("no video/.out/polly-gohar.mp3: run node video/live.mjs first");
  return { voice, proof: awsProof(f) };
}

export function scenes(f, live) {
  const imd = f.imd;
  return [
    // ============================================================ hook
    {
      id: "hook",
      chapter: "The problem",
      kind: "card",
      bar: false,
      tag: "Pukaar",
      screen: "Kinetic type on the app's night blue; each phrase lands as it is said, key words marked in marigold, then the wordmark.",
      card: {
        mode: "hook",
        beats: [
          { text: "A mountain stream can flood a village in [hours,]" },
          { text: "often at [night.]" },
          { text: "The forecast [sees it coming.]" },
          { text: "The village [never hears it.]" },
          { brand: true, pre: "That's" },
        ],
      },
      lines: [
        L("A mountain stream can flood a village in hours, | often at night."),
        L("The forecast sees it coming. | The village never hears it."),
        L("That's Pukaar.", "That's Pukaar."),
      ],
      tail: 0.6,
      async run(h) {
        const chunks = h.tl.lines.flatMap((l) => l.chunks);
        for (let i = 0; i < chunks.length; i++) {
          await h.at(Math.max(0, chunks[i].start - 0.12));
          await h.page.evaluate((k) => window.__hook.beat(k), i);
        }
      },
    },
    // ============================================================ problem, over stock footage
    {
      id: "problem",
      kind: "footage",
      tag: "The problem",
      screen: "Stock footage (Pexels License; credits in docs/media/CREDITS.md): storm clouds over Himalayan ridges, a river in flood, a landslide scar, storms from orbit, a hill village.",
      lines: [
        L(
          `On the night of 30 June 2025, | cloudbursts hit Mandi district: | at least ${f.mandiDead} dead, ${f.mandiMissing} missing.`,
          `On the night of the thirtieth of June, twenty twenty-five, | cloudbursts hit Mandi district: | at least ${sayInt(f.mandiDead)} dead, ${sayInt(f.mandiMissing)} missing.`,
        ),
        L("Forecasts exist, but they are numbers on a website, | not a warning anyone hears."),
      ],
      shots: [
        ["timelapse", 0, 0],
        ["river", 0, 1],
        ["damage", 0, 2],
        ["forecast", 1, 0],
        ["village", 1, 1],
      ],
    },
    // ============================================================ the turn
    {
      id: "turn",
      chapter: "What Pukaar does",
      kind: "card",
      tag: "Pukaar",
      screen: "The wordmark, the one-liner, and who it is for, appearing as they are said.",
      card: {
        mode: "turn",
        one: "A forecast becomes a [spoken Hindi alert] on every phone in the village.",
        who: [
          { icon: "officer", big: "District officers", small: "approve every alert in one tap" },
          { icon: "villager", big: "Villagers", small: "no account; hear it, tap “मिल गया”" },
          { icon: "pradhan", big: "Village pradhans", small: "see their village's alerts and reports" },
        ],
      },
      lines: [
        L("Pukaar turns a forecast | into a spoken Hindi alert | on every phone in the village.", "Pukaar turns a forecast | into a spoken Hindi alert | on every phone in the village."),
        L("A district officer approves it in one tap, | and villagers confirm they heard it."),
      ],
      async run(h) {
        await h.page.evaluate(() => window.__turn.show(0));
        await h.chunk(0, 1, -0.2);
        await h.page.evaluate(() => window.__turn.show(1));
        await h.cue(1, 0.1);
        await h.page.evaluate(() => window.__turn.show(2));
        await h.chunk(1, 1, -0.1);
        await h.page.evaluate(() => window.__turn.show(3));
        await h.chunk(1, 1, 0.6);
        await h.page.evaluate(() => window.__turn.show(4));
      },
      tail: 1.1,
    },
    // ============================================================ the Gohar story, on the live landing page
    {
      id: "story",
      chapter: "The night the river rose",
      tag: "Back-test",
      screen: "The live landing page: the 3D Beas valley (heightmap from AWS Open Data Terrain Tiles) with the water rising as the page scrolls, then 'the night the river rose': Gohar, July 2023, replayed through the real rules, the chart drawing itself step by step.",
      lines: [
        L("Here's Gohar, in Mandi, | July 2023, | replayed through Pukaar's real rules."),
        L(
          `The river forecast passes its own 90th percentile: | Watch.`,
          `The river forecast passes its own ninetieth percentile: | Watch.`,
        ),
        L(
          `Rain passes ${imd.watch} millimetres | with the river high: | Warning.`,
          `Rain passes ${sayDec(imd.watch)} millimetres | with the river high: | Warning.`,
        ),
        L(`Then ${imd.warning}: | Critical.`, `Then ${sayDec(imd.warning)}: | Critical.`),
        L(`${f.leadHours} hours | before the river's peak day.`, `${sayInt(f.leadHours)} hours | before the river's peak day.`, { pre: 0.45 }),
      ],
      keepSticky: true,
      async prepare(page) {
        await openApp(page, f, "/", () => page.locator(".story-step").first().waitFor({ timeout: 60_000 }));
        await page.locator(".hero-3d.is-ready, .hero canvas").first().waitFor({ timeout: 30_000 }).catch(() => {});
        await page.waitForTimeout(2500); // the hero's 3D valley loads its heightmap
        // the story reads small at 1920 px: lay the page out 1.45x larger (CSS zoom keeps the sticky chart working)
        await page.evaluate(() => (document.documentElement.style.zoom = "1.45"));
      },
      async run(h) {
        // the hero valley: the water rises with the scroll
        await h.page.evaluate(() => window.__v.scrollTo(380, 2600));
        const steps = h.page.locator(".story-step");
        const toStep = (i, ms = 900) =>
          steps.nth(i).evaluate((el, ms) => window.__v.scrollTo(el.getBoundingClientRect().top + scrollY - innerHeight * 0.26, ms), ms);
        await h.chunk(0, 1, 0);
        await toStep(0, 1100);
        for (let i = 1; i <= 4; i++) {
          await h.cue(i, -0.35);
          await toStep(i);
        }
      },
    },
    // ============================================================ live map on AWS
    {
      id: "live",
      chapter: "Live on AWS",
      tag: "Live on AWS",
      screen: "/live on the deployed site during a labelled replay on AWS: the 3D terrain map of the five villages turning to their levels, the counters and the acknowledgement funnel.",
      lines: [
        L("Now the same night, running live on AWS."),
        L("Every 15 minutes, | EventBridge wakes a Lambda | that sets each village's level by rule, | never by a model.", "Every fifteen minutes, | EventBridge wakes a Lambda | that sets each village's level by rule, | never by a model."),
      ],
      async prepare(page) {
        await openApp(page, f, "/live", () => page.locator(".maplibregl-canvas, canvas").first().waitFor({ timeout: 60_000 }));
        await page.waitForTimeout(4000);
      },
      async run(h) {
        const map = h.page.locator(".live-grid > *").first();
        await h.at(0.2);
        await h.zoom(map, { scale: 1.3, ms: 900 });
        await h.cue(1, 0.2);
        await h.box(map, { dim: 0.18, pad: 4 });
      },
    },
    // ============================================================ the officer approves
    {
      id: "approve",
      chapter: "The officer approves",
      tag: "Officer console",
      screen: "The officer console signed in as a demo officer (Cognito): the pending Gohar critical alert with its Hindi draft, the rule-fallback label, then Approve and the confirmation.",
      lines: [
        L("The officer on duty sees the Hindi draft. | Step Functions has paused, | waiting for one tap."),
        L("The model only fills a fixed template, | and a checker rejects any number | not in the decision trace."),
        L("Bedrock access is still pending on this account, | so it says rule-fallback, | and the alert still goes out."),
        L("Approve."),
      ],
      async prepare(page) {
        await signIn(page, f);
        await openApp(page, f, "/console#approvals", () => page.locator(".pending-card").first().waitFor({ timeout: 60_000 }));
        // the console lists the first pending cards and folds the rest behind "Show N more"
        const more = page.getByRole("button", { name: /^Show \d+ more$/ });
        if (await more.count()) await more.first().click();
        const card = page.locator(".pending-card", { hasText: "Gohar" }).first();
        await card.waitFor({ timeout: 30_000 });
        await card.evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + scrollY - 120));
      },
      async run(h) {
        const card = h.page.locator(".pending-card", { hasText: "Gohar" }).first();
        await overlay(h.page, '<div style="font:700 18px/1 JetBrains Mono,monospace;letter-spacing:.18em;color:#5b6185;margin-bottom:8px">HERO USER · DEMO ACCOUNT</div>Officer on duty, Mandi district<div style="font:500 22px/1.3 Inter,sans-serif;color:#5b6185;margin-top:6px">signed in with Cognito; wants every village warned in time</div>', "right");
        await h.zoom(card, { scale: 1.35 });
        await h.cue(1, 0);
        await h.page.evaluate(() => document.querySelectorAll(".__vbox").forEach((d) => d.remove()));
        await h.box(card.locator(".draft-hi"), { dim: 0.2 });
        await h.cue(2, 0);
        await h.unbox();
        await h.box(card.locator(".chip-row, .chip-warn").first(), { dim: 0.2 });
        await h.cue(3, -0.4);
        await h.unbox();
        await card.locator(".btn-approve").click();
        await h.page.locator("dialog[open] .btn-accent").waitFor({ timeout: 5000 });
        await h.page.waitForTimeout(500);
        await h.page.locator("dialog[open] .btn-accent").click();
      },
      tail: 1.4,
    },
    // ============================================================ the village hears it
    {
      id: "heard",
      chapter: "The village hears",
      tag: "The village hears",
      screen: "The Gohar village page after approval: the alert delivered, the Listen button playing the real Polly (Kajal, hi-IN) MP3, the time-to-ear stopwatch and the deliveries.",
      audio: [{ line: 0, dt: 2.6, path: live.voice, gain_db: -3 }],
      lines: [
        L("Amazon Polly speaks it in Hindi:"),
        L("Every phone gets the voice | and one button: | मिल गया, got it.", "Every phone gets the voice | and one button: | mil gaya, got it.", { pre: 6.2 }),
        L("Pukaar times each alert, from the river rising to the first person who heard it."),
        L("In a replay, | it goes to test phones only."),
      ],
      async prepare(page) {
        await signIn(page, f);
        await openApp(page, f, "/village/gohar", () => page.locator(".alert-card").first().waitFor({ timeout: 60_000 }));
        // the page fills in section by section; place nothing until the layout has stopped moving
        await page.waitForLoadState("networkidle").catch(() => {});
        // open the details once off camera, so the alert endpoint is warm when the scene opens them
        const toggle = page.locator(".alert-card").first().locator("button[aria-expanded]");
        await toggle.click();
        await page.locator(".tte").waitFor({ timeout: 30_000 }).catch(() => {});
        await toggle.click();
        await page.waitForTimeout(2000);
        await page.locator(".alert-card").first().evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + scrollY - 140));
        await page.waitForTimeout(500);
      },
      async run(h) {
        const card = h.page.locator(".alert-card").first();
        await h.box(card, { dim: 0.2, pad: 8 });
        await h.cue(1, -0.4);
        await h.unbox();
        // open the details now, so the stopwatch has loaded by the time it is named
        await card.locator("button[aria-expanded]").click();
        await h.box(card.locator(".ac-row"), { dim: 0.2 });
        await h.cue(2, -0.3);
        await h.unbox();
        await h.page.locator(".tte").waitFor({ timeout: 15_000 });
        await h.page.waitForTimeout(500); // the details panel finishes opening before the camera moves
        await h.zoom(h.page.locator(".tte"), { scale: 1.3 });
        await h.page.waitForTimeout(520); // boxes are placed from the settled transform, not mid-zoom
        await h.box(h.page.locator(".tte"), { dim: 0.15 });
        await h.cue(3, 0);
        await h.unbox();
        await h.unzoom(300);
        await h.scrollTo(h.page.locator(".alert-details .table-wrap"), { offset: 260, ms: 700 });
      },
    },
    // ============================================================ every decision, audited
    {
      id: "audit",
      tag: "Audit log",
      screen: "The audit page (officer view): the officer's approval allowed by a Cedar policy, and a village pradhan's attempt to approve refused, each with the policy and reason; recorded from the live stack.",
      lines: [
        L("Every decision lands in an audit log: | Cedar allowed the officer's approval,"),
        L("and refused a village pradhan who tried, | with the policy and the reason."),
      ],
      async prepare(page) {
        await signIn(page, f);
        await openApp(page, f, "/audit", () => page.locator(".data-table tbody tr").first().waitFor({ timeout: 60_000 }));
        await page.waitForTimeout(800);
      },
      async run(h) {
        const allow = h.page.locator(".data-table tbody tr:not(.row-deny)", { hasText: "officer1" }).filter({ hasText: /\bapprove\b/ }).first();
        const deny = h.page.locator(".data-table tbody tr.row-deny").first();
        await h.chunk(0, 1, -0.2);
        await h.box(allow, { dim: 0.2 });
        await h.cue(1, -0.1);
        await h.unbox();
        await h.scrollTo(deny, { offset: 300, ms: 600 });
        await h.box(deny, { dim: 0.2 });
      },
    },
    // ============================================================ a villager reports back
    {
      id: "report",
      tag: "Villager report",
      kind: "card",
      screen: "The live villager report page in a phone frame (390 px): Hindi first, one big record button, works offline.",
      card: { mode: "phone", url: `${f.liveUrl}/report`, caption: "Report page · live site · 390 px", value: f.slow3gSeconds, source: `Measured ${f.slow3gKb} kB, first visit, 4x CPU slowdown (README)` },
      lines: [
        L("Villagers report back by voice, photo or text, | from any phone, even offline."),
        L(
          `On slow 3G, | the page is ready in ${f.slow3gSeconds} seconds.`,
          `On slow three G, | the page is ready in ${sayDec(f.slow3gSeconds)} seconds.`,
        ),
      ],
      async run(h) {
        await h.cue(1, -0.2);
        await h.page.evaluate(() => window.__phone.stat());
      },
      tail: 1.4,
    },
    // ============================================================ architecture in 3D
    {
      id: "arch",
      chapter: "Architecture",
      kind: "three",
      tag: "Architecture",
      screen: "A three.js model of the stack: each AWS service lifts and glows as it is named, pulses running along the real request path, everything else dimmed.",
      three: ARCH(f),
      lines: [
        L("The whole loop is serverless on AWS."),
        L("EventBridge Scheduler runs the sweep Lambda, | with no retries and a dead-letter queue."),
        L("One DynamoDB table, | with conditional writes, | so an alert is never sent twice."),
        L("Step Functions waits for the officer; | no answer moves to the next one."),
        L("Bedrock drafts through Strands, | Polly speaks, | and the audio lands in S3."),
        L("Telegram delivers it, | and the tap comes back through API Gateway."),
        L(`Cognito signs officers in, Cedar checks every action, | and ${f.stack.alarms} CloudWatch alarms watch it all.`, `Cognito signs officers in, Cedar checks every action, | and ${sayInt(f.stack.alarms)} CloudWatch alarms watch it all.`),
      ],
      async run(h) {
        for (let i = 1; i < h.tl.lines.length; i++) {
          await h.cue(i, -0.25);
          await h.page.evaluate((k) => window.__arch.focus(k), i - 1);
        }
      },
    },
    // ============================================================ live AWS proof
    {
      id: "proof",
      tag: "Live proof",
      kind: "card",
      screen: "Real output captured from the AWS account at render time: the approval state machine's latest executions, the Polly MP3s in S3, and the live /health check.",
      card: { mode: "terminal", title: "Live in us-east-1, right now", eyebrow: `stack ${STACK}`, bar: "aws cli · curl", ...live.proof },
      lines: [
        L(
          `This is live: | ${f.stack.executions} approval workflows so far, | ${f.stack.succeeded} succeeded.`,
          `This is live: | ${sayInt(f.stack.executions)} approval workflows so far, | ${sayInt(f.stack.succeeded)} succeeded.`,
        ),
        L("Polly's Hindi audio in S3, | and the health check, | right now."),
        L("Nothing runs between requests: | no servers, no database instance."),
      ],
      async run(h) {
        await h.page.evaluate(() => window.__term.group(0));
        await h.cue(1, 0);
        await h.page.evaluate(() => window.__term.group(1));
        await h.chunk(1, 1, -0.2);
        await h.page.evaluate(() => window.__term.group(2));
      },
    },
    // ============================================================ what it does not do yet
    {
      id: "honest",
      chapter: "Limits and close",
      tag: "Not done yet",
      kind: "card",
      screen: "Two honest limits, each with what Pukaar does about it.",
      card: {
        mode: "gaps",
        title: "What it [doesn't do] yet",
        rows: [
          { gap: "Global models missed the 2025 Mandi cloudburst", icon: "report", big: "A verified villager report", small: "raises a level on its own" },
          { gap: "Bedrock access still pending", icon: "rule", big: "The fixed Hindi template", small: "goes out, labelled rule-fallback" },
        ],
      },
      lines: [
        L("In our 2025 back-test, | the global forecasts missed the Mandi cloudburst."),
        L("So a verified villager report | can raise a level on its own."),
      ],
      async run(h) {
        await h.chunk(0, 1, -0.2);
        await h.page.evaluate(() => window.__gaps.show(0));
        await h.cue(1, 0.3);
        await h.page.evaluate(() => window.__gaps.show(1));
      },
    },
    // ============================================================ close
    {
      id: "close",
      kind: "card",
      bar: false,
      tag: "Pukaar",
      screen: "End card: the callback line, the wordmark, the live URL, the repository and what it runs on.",
      card: {
        mode: "close",
        call: "The river will still rise.\n[Now the village hears first.]",
        url: f.liveUrl.replace("https://", ""),
        meta: ["github.com/Prashant-thakur77/pukaar", "Built on AWS · Environmental Hacks · Heat and Water"],
      },
      lines: [L("The river will still rise. | Now the village hears first.")],
      tail: 4.5,
      async run(h) {
        await h.page.evaluate(() => window.__close.show(0));
        await h.at(h.tl.lines[0].end + 0.2);
        await h.page.evaluate(() => window.__close.show(1));
      },
    },
  ];
}

/** The architecture model: nodes on a grid (x, z), edges along the request path, and one step per narrated line. */
function ARCH(f) {
  return {
    nodes: [
      { id: "eb", name: "EventBridge Scheduler", detail: "rate(15 min) · 0 retries · DLQ", x: -10, z: -3.5, kind: "aws" },
      { id: "meteo", name: "Open-Meteo", detail: "rain + river forecasts", x: -10, z: 1.5, kind: "ext" },
      { id: "sweep", name: "Lambda · sweep", detail: "level by rule, per village", x: -6, z: -1, kind: "aws" },
      { id: "ddb", name: "DynamoDB", detail: "one table · conditional writes", x: -6, z: 4, kind: "aws" },
      { id: "sfn", name: "Step Functions", detail: "waitForTaskToken · next officer", x: -1.5, z: -3.5, kind: "aws" },
      { id: "bedrock", name: "Bedrock · Strands", detail: "Nova drafts · checker · fallback", x: -1.5, z: 1.5, kind: "aws" },
      { id: "polly", name: "Polly", detail: "Kajal · hi-IN", x: 3, z: 1.5, kind: "aws" },
      { id: "s3", name: "S3", detail: "private · MP3 + photos", x: 3, z: 5.5, kind: "aws" },
      { id: "apigw", name: "API Gateway · Lambda", detail: "FastAPI · Cognito JWT", x: 3, z: -3.5, kind: "aws" },
      { id: "cognito", name: "Cognito · Cedar", detail: "officer sign-in · audit log", x: 7.5, z: -5.5, kind: "aws" },
      { id: "tg", name: "Telegram", detail: "voice + “मिल गया”", x: 8, z: 0, kind: "ext" },
      { id: "phone", name: "Village phones", detail: "hear · confirm · report", x: 11, z: 3, kind: "phone" },
      { id: "cw", name: "CloudWatch", detail: `${f.stack.alarms} alarms · X-Ray · dashboard`, x: -1.5, z: 6, kind: "aws" },
    ],
    edges: [
      ["eb", "sweep"], ["meteo", "sweep"], ["sweep", "ddb"], ["sweep", "sfn"], ["sfn", "bedrock"], ["bedrock", "polly"],
      ["polly", "s3"], ["sfn", "apigw"], ["apigw", "cognito"], ["sfn", "tg"], ["tg", "phone"], ["phone", "apigw"],
      ["ddb", "cw"], ["sfn", "cw"],
    ],
    steps: [
      { on: ["eb", "meteo", "sweep"], title: "Every 15 minutes", dist: 15 },
      { on: ["sweep", "ddb"], title: "One table, no double sends", dist: 14 },
      { on: ["sweep", "sfn", "apigw"], title: "One approval per alert", dist: 15 },
      { on: ["sfn", "bedrock", "polly", "s3"], title: "Draft, check, speak", dist: 16 },
      { on: ["sfn", "tg", "phone", "apigw"], title: "To every phone, and back", dist: 17 },
      { on: ["apigw", "cognito", "cw", "ddb", "sfn"], title: "Signed in, checked, watched", dist: 22 },
    ],
  };
}

export const outputs = {
  narrated: "pukaar-demo.mp4",
  silent: "pukaar-demo-silent.mp4",
  srt: "pukaar-demo.srt",
  poster: "pukaar-demo-poster.png",
  gif: "pukaar-demo.gif",
  transcript: "pukaar-demo-narration.txt",
};
export const poster = { scene: "arch", at: 6 };
export const gifScene = "story";
export const timing = { lead: 0.1, gap: 0.12, tail: 0.25, gapAfter: { ".": 0.5, "?": 0.65, ":": 0.4, ";": 0.4, ",": 0.3 } };
export const crf = 22;
export const tts = { speed: 1.06, speed_max_cps: 22, max_cps: 23 };
export const music = { seed: 11, speech_lufs: -30, gap_db: 5, fade_in: 2, fade_out: 3 };

export const scriptDoc = {
  path: "docs/submission/demo-script.md",
  head: ({ total, words, wpm, mmss, chapters }) => `# Demo video script (${mmss(total)})

The narration of [docs/media/pukaar-demo.mp4](../media/pukaar-demo.mp4) (${total.toFixed(1)} s, 1920×1080), rendered by \`node video/record.mjs demo\` from [video/demo.mjs](../../video/demo.mjs); this file is written by the same run, so the times and words below are the video's own. Timed captions: [pukaar-demo.srt](../media/pukaar-demo.srt).

Every number is read at render time: the Mandi 2025 figures and the 3G load time from README.md, the Gohar story from frontend/src/data/story-gohar-2023.json (built by the real rules), the alarm and execution counts from the AWS account, and the proof scene's output straight from the AWS CLI. The live scenes are the deployed site during a labelled replay on AWS; replay alerts go to test phones only. The voice is Chatterbox TTS (open source) with its own built-in synthetic voice; the Hindi alert is the real Amazon Polly (Kajal, hi-IN) MP3. ${words} words in ${total.toFixed(0)} s (${wpm} words a minute).

## Chapters

\`\`\`
${chapters.join("\n")}
\`\`\`

## Video description

\`\`\`
Pukaar (पुकार): a flood-warning loop for Himalayan villages, built on AWS. A forecast becomes a spoken Hindi alert on every phone in the village, approved by a district officer in one tap.

Live: https://main.d15r7ktz99l46x.amplifyapp.com
Code: https://github.com/Prashant-thakur77/pukaar

${chapters.join("\n")}

Voice: Chatterbox TTS (open source) with its built-in synthetic voice. Hindi alert: Amazon Polly (Kajal).
Music: synthesised for this video by video/narration/music.py (CC0). Stock footage: Pexels (Pexels License), credits in docs/media/CREDITS.md.
\`\`\``,
};
