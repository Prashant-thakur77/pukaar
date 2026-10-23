// The Pukaar Raahat demo film (Web3 for Social Good, under three minutes): the hook, the problem, the evidence for
// cash before a flood, the turn, then one replayed flood on the live stack and Base Sepolia (the sealed rule, the
// officer's approval, the anchor and its re-verify, tier 1, three attestations, the satellite's evidence, tier 2, the
// receipts, the public ledger), why a chain, the chain read at render time, what is not real yet, and the close.
//   node video/raahat-live.mjs            # stage it: reset, start the replay, wait for Pandoh's pending alert
//   node video/record.mjs raahat [--plan] [--only a,b] [--preview]
// The live scenes act on the deployed stack in order (approve, release, attest, release, receipts), so a full render
// needs a fresh staging; --only re-records card scenes only.
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { L as L0, ROOT } from "./lib/engine.mjs";

export const RAAHAT_STACK = "pukaar-raahat";
export const REGION = "us-east-1";
const RPC = "https://base-sepolia-rpc.publicnode.com";
const CAST = process.env.CAST ?? join(process.env.HOME, ".foundry/bin/cast");

/** A narration line, with names and symbols respelled for the voice only (the caption keeps the text). */
const L = (text, say = text, opts = {}) =>
  L0(text, say.replace(/Pukaar/g, "Poo-kaar").replace(/Raahat/g, "Raa-hut").replace(/pradhan/gi, "pradhaan"), opts);

const NUM = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
  "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"];
const TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];
/** 72 -> "seventy-two", 1500 -> "fifteen hundred", 23000 -> "twenty-three thousand" (what Chatterbox reads). */
function sayInt(n) {
  if (n < 20) return NUM[n];
  if (n < 100) return TENS[Math.floor(n / 10)] + (n % 10 ? `-${NUM[n % 10]}` : "");
  if (n < 1000) return `${NUM[Math.floor(n / 100)]} hundred${n % 100 ? ` ${sayInt(n % 100)}` : ""}`;
  if (n % 1000 === 0) return `${sayInt(n / 1000)} thousand`;
  if (n < 10000 && n % 100 === 0) return `${sayInt(n / 100)} hundred`;
  return `${sayInt(Math.floor(n / 1000))} thousand ${sayInt(n % 1000)}`;
}
const sayDec = (x) => {
  const [a, b] = String(x).split(".");
  return b ? `${sayInt(Number(a))} point ${[...b].map((d) => NUM[Number(d)]).join(" ")}` : sayInt(Number(a));
};
const rupees = (n) => n.toLocaleString("en-IN");
const ILLUSTRATIVE = "illustrative, SDRF norms to be mapped with DDMA";
let liveForDoc = ""; // the live URL for the script doc's description (facts() runs before the doc is written)

const need = (v, what) => {
  if (v === undefined || v === null || v === "" || (typeof v === "number" && !Number.isFinite(v)))
    throw new Error(`facts: could not find ${what}`);
  return v;
};
const aws = (...a) => JSON.parse(execFileSync("aws", [...a, "--region", REGION, "--output", "json"], { encoding: "utf8" }));
/** A read-only call to the chain; the public RPC drops calls now and then, so try three times. */
function cast(...args) {
  for (let i = 0; ; i++) {
    try {
      return execFileSync(CAST, [...args, "--rpc-url", RPC], { encoding: "utf8", timeout: 30_000 }).trim();
    } catch (e) {
      if (i >= 2) throw e;
      execFileSync("sleep", ["2"]);
    }
  }
}
const keccak = (s) => execFileSync(CAST, ["keccak", s], { encoding: "utf8" }).trim();

/** Every number the film says or shows: the Raahat stack, the chain, the repo. A missing number fails the render. */
export async function facts(ROOT) {
  const outs = Object.fromEntries(
    aws("cloudformation", "describe-stacks", "--stack-name", RAAHAT_STACK).Stacks[0].Outputs.map((o) => [o.OutputKey, o.OutputValue]),
  );
  const api = need(outs.ApiUrl, "the Raahat stack's ApiUrl");
  const pool = await (await fetch(`${api}/raahat/pool`)).json();
  if (!pool.rule?.sealed) throw new Error("facts: the rule is not sealed on chain");
  const wei = (w) => Number(BigInt(w) / 10n ** 18n);
  const dep = JSON.parse(readFileSync(join(ROOT, "contracts/deployments/base-sepolia.json"), "utf8"));
  const sources = readFileSync(join(ROOT, "docs/submission/w3sg-sources.md"), "utf8");
  const wfp = sources.match(/\$(\d+) by mobile money to ([\d,]+)\+ households[^;]*;[^%]*?(\d+)% less likely to go a day without eating/);
  const readme = readFileSync(join(ROOT, "README.md"), "utf8");
  const dte = readme.match(/at least (\d+)\s+people dead and (\d+) missing/);
  const forge = readme.match(/Foundry: (\d+) tests on the four contracts[\s\S]*?with (\d+)% line/);
  const sat = JSON.parse(readFileSync(join(ROOT, "data/raahat/satellite_2023.json"), "utf8"));
  const scene = need(sat.scenes[0], "the first Sentinel-2 scene after the flood");
  liveForDoc = need(outs.WebUrl, "the Raahat stack's WebUrl");
  const households = Number(cast("call", dep.pool, "householdCount(bytes32)(uint32)", keccak("pandoh")));
  return {
    liveUrl: need(outs.WebUrl, "the Raahat stack's WebUrl"),
    apiUrl: api,
    repoUrl: "https://github.com/Prashant-thakur77/pukaar",
    deployment: dep,
    explorer: need(pool.explorer, "the explorer"),
    network: need(pool.network, "the network"),
    anticipatory: wei(pool.rule.amount_anticipatory_wei),
    confirmed: wei(pool.rule.amount_confirmed_wei),
    cooldownHours: need(pool.rule.cooldown_hours, "the cooldown"),
    sealedAt: new Date(pool.rule.sealed_at * 1000).toISOString().slice(0, 10),
    households: need(households || null, "Pandoh's registered households on chain"),
    wfpUsd: Number(need(wfp?.[1], "the WFP transfer in w3sg-sources.md")),
    wfpHouseholds: Number(need(wfp?.[2], "the WFP household count").replace(/,/g, "")),
    wfpLessHungry: Number(need(wfp?.[3], "the WFP food-security result")),
    mandiDead: Number(need(dte?.[1], "the Down To Earth death toll in README.md")),
    mandiMissing: Number(need(dte?.[2], "the Down To Earth missing count in README.md")),
    forgeTests: Number(need(forge?.[1], "the Foundry test count in README.md")),
    forgeCoverage: Number(need(forge?.[2], "the Foundry coverage in README.md")),
    sat: {
      event: sat.event,
      date: scene.date,
      before: scene.before_km2,
      after: scene.after_km2,
      compared: scene.compared_km2,
      severity: scene.severity,
      hash: scene.evidence_hash,
      water: scene.public_path,
    },
  };
}

/** The demo officer's password, from the git-ignored .env.deploy.raahat.local; never printed. */
function demoPassword() {
  const m = readFileSync(join(ROOT, ".env.deploy.raahat.local"), "utf8").match(/^PUKAAR_DEMO_PASSWORD=(.+)$/m);
  if (!m) throw new Error(".env.deploy.raahat.local has no PUKAAR_DEMO_PASSWORD");
  return m[1].trim().replace(/^["']|["']$/g, "");
}

async function signIn(page, f, user) {
  await page.goto(`${f.liveUrl}/login`, { waitUntil: "domcontentloaded" });
  await page.locator('input[autocomplete="username"]').fill(user);
  await page.locator('input[type="password"]').fill(demoPassword());
  await page.locator('form button[type="submit"]').click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
}

/** A labelled card dropped into a live page (who is acting, or what is real). */
async function overlay(page, html, pos = "right") {
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
const unoverlay = (page) => page.evaluate(() => document.querySelectorAll(".__vbox").forEach((d) => d.remove()));
const who = (eyebrow, title, sub) =>
  `<div style="font:700 18px/1 JetBrains Mono,monospace;letter-spacing:.18em;color:#5b6185;margin-bottom:8px">${eyebrow}</div>${title}<div style="font:500 22px/1.3 Inter,sans-serif;color:#5b6185;margin-top:6px">${sub}</div>`;
const TEST_MONEY = who("TEST MONEY", "tINR has no value", `Amounts ${ILLUSTRATIVE}`);

/** Lays the app out larger (CSS zoom on <body>), so it reads at phone size; the camera's boxes follow it. */
const ZOOM = { console: 2, site: 1.6, explorer: 1.45 };
async function enlarge(page, z) {
  await page.evaluate((z) => {
    document.body.style.zoom = String(z);
    window.__vZoom = z;
  }, z);
  await page.waitForTimeout(600);
}
/** Films one console panel on its own: the other panels are hidden and this one takes the grid's full width. */
const focusPanel = (page, id) =>
  page.evaluate((id) => {
    const sec = document.getElementById(id);
    for (const el of document.querySelectorAll(".console-grid > *")) if (el !== sec) el.style.display = "none";
    Object.assign(sec.style, { gridArea: "auto", gridColumn: "1 / -1", maxWidth: "940px" });
  }, id);
/** Scrolls so the element's top sits `top` px below the top of the frame. */
const scrollTop = (loc, top = 100) => loc.evaluate((el, top) => window.scrollTo(0, el.getBoundingClientRect().top + scrollY - top), top);

/** Waits for a locator without holding up the scene clock: the chain answers in its own time. */
const later = (fn) => fn().catch(() => {});

/** The officer console's relief card for the alert, scrolled into view. */
async function reliefCard(page, f, alert, user = "officer1") {
  await signIn(page, f, user);
  await page.goto(`${f.liveUrl}/console#${user === "officer1" ? "relief" : "receipts"}`, { waitUntil: "domcontentloaded" });
  const card = page.locator(".relief-card").first();
  await card.waitFor({ timeout: 60_000 });
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(1200);
  await focusPanel(page, user === "officer1" ? "relief" : "receipts");
  await enlarge(page, ZOOM.console);
  await scrollTop(card, 90);
  await page.waitForTimeout(400);
  return card;
}

/** The alert being filmed (video/raahat-live.mjs), and an API read of its state. */
function staged() {
  const p = join(ROOT, "video/.out/raahat-live.json");
  if (!existsSync(p)) throw new Error("no video/.out/raahat-live.json: run node video/raahat-live.mjs first");
  return JSON.parse(readFileSync(p, "utf8"));
}
async function until(f, path, test, what, secs = 240) {
  for (let i = 0; i < secs / 3; i++) {
    const r = await fetch(f.apiUrl + path).then((r) => (r.ok ? r.json() : null), () => null);
    if (r && test(r)) return r;
    await new Promise((res) => setTimeout(res, 3000));
  }
  throw new Error(`waited ${secs} s for ${what}`);
}

/** The chain, read when the proof scene records (after the live scenes have acted on it). */
function chainProof(f, alert) {
  const d = f.deployment;
  const key = keccak(alert);
  const short = (a) => `${a.slice(0, 6)}…${a.slice(-4)}`;
  const q = (addr, sig, ...args) => cast("call", addr, sig, ...args);
  return {
    groups: [
      { cmd: `cast call ${short(d.pool)} "rulesSealed()"`, out: [q(d.pool, "rulesSealed()(bool)")], hot: [0] },
      { cmd: `cast call ${short(d.alert_registry)} "isExercise(bytes32)" keccak("${alert}")`, out: [q(d.alert_registry, "isExercise(bytes32)(bool)", key)], hot: [0] },
      {
        cmd: `cast call ${short(d.impact_attestation)} "isConfirmed" / "attesterCount"`,
        out: [`confirmed: ${q(d.impact_attestation, "isConfirmed(bytes32)(bool)", key)}   attesters: ${q(d.impact_attestation, "attesterCount(bytes32)(uint8)", key)}`],
        hot: [0],
      },
      {
        cmd: `cast call ${short(d.pool)} "released" / "receiptCount"`,
        out: [
          `tier 1: ${q(d.pool, "released(bytes32,uint8)(bool)", key, "1")}   tier 2: ${q(d.pool, "released(bytes32,uint8)(bool)", key, "2")}`,
          `receipts: ${q(d.pool, "receiptCount(bytes32)(uint32)", key)}`,
        ],
        hot: [0, 1],
      },
    ],
    stamp: `Read from ${f.network} at ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC · ${RPC.replace("https://", "")}`,
  };
}

export async function probe(_browser, _f) {
  // the plan, and a preview of card scenes, need no staged alert
  if (process.argv.includes("--plan") || (process.argv.includes("--preview") && !existsSync(join(ROOT, "video/.out/raahat-live.json"))))
    return { alert: "alr_plan", report: "rep_plan" };
  return staged();
}

export function scenes(f, live) {
  const a = f.anticipatory, c = f.confirmed, n = f.households;
  const s = f.sat;
  return [
    // ============================================================ hook
    {
      id: "hook",
      chapter: "The problem",
      kind: "card",
      bar: false,
      tag: "Pukaar Raahat",
      screen: "Kinetic type on night blue, each phrase landing as it is said, key words in marigold, then the wordmark पुकार राहत.",
      card: {
        mode: "hook",
        brandHi: "पुकार राहत",
        brandEn: "Pukaar Raahat",
        beats: [
          { text: "In 2025, a [dog] woke a Himalayan village at midnight." },
          { text: "[No warning] reached them." },
          { text: "And when relief comes," },
          { text: "nobody can [see where it goes.]" },
          { brand: true, pre: "This is" },
        ],
      },
      lines: [
        L("In 2025, a dog woke a Himalayan village at midnight. | No warning reached them.", "In twenty twenty-five, a dog woke a Himalayan village at midnight. | No warning reached them."),
        L("And when relief comes, | nobody can see where it goes."),
        L("This is Pukaar Raahat."),
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
      screen: "Stock footage (Pexels License; credits in docs/media/CREDITS.md): storm clouds over Himalayan ridges, a river in flood, a landslide.",
      lines: [
        L(
          `On the night of 30 June 2025, | cloudbursts hit Mandi district: | at least ${f.mandiDead} dead, ${f.mandiMissing} missing.`,
          `On the night of the thirtieth of June, twenty twenty-five, | cloudbursts hit Mandi district: | at least ${sayInt(f.mandiDead)} dead, ${sayInt(f.mandiMissing)} missing.`,
        ),
        L("Relief is paid after the water, | and the village can't check who got it."),
      ],
      shots: [
        ["timelapse", 0, 0],
        ["river", 0, 1],
        ["damage", 0, 2],
      ],
    },
    // ============================================================ the evidence for cash before a flood
    {
      id: "evidence",
      kind: "card",
      tag: "The evidence",
      screen: "Three numbers count up as they are said: the WFP / Oxford CSAE evaluation of anticipatory cash in the 2020 Bangladesh floods.",
      card: {
        mode: "stat",
        title: "Cash [before] the flood works",
        stats: [
          { value: f.wfpUsd, prefix: "$", label: "by mobile money, about a week before the peak" },
          { value: f.wfpHouseholds, suffix: "+", label: "households, Bangladesh 2020 floods" },
          { value: f.wfpLessHungry, suffix: "%", label: "less likely to go a day [without eating]" },
        ],
        source: "Oxford CSAE and WFP evaluation of the 2020 Bangladesh floods · sources in docs/submission/w3sg-sources.md",
      },
      lines: [
        L("Money before the water works."),
        L(
          `In Bangladesh in 2020, | the World Food Programme sent $${f.wfpUsd} by mobile money, | about a week before the flood peaked, | to over ${f.wfpHouseholds.toLocaleString("en-US")} households.`,
          `In Bangladesh in twenty twenty, | the World Food Programme sent ${sayInt(f.wfpUsd)} dollars by mobile money, | about a week before the flood peaked, | to over ${sayInt(f.wfpHouseholds)} households.`,
        ),
        L(`They were ${f.wfpLessHungry}% less likely | to go a day without eating.`, `They were ${sayInt(f.wfpLessHungry)} percent less likely | to go a day without eating.`),
      ],
      async run(h) {
        await h.chunk(1, 1, 0.2);
        await h.page.evaluate(() => window.__stat.show(0));
        await h.chunk(1, 3, 0.4);
        await h.page.evaluate(() => window.__stat.show(1));
        await h.cue(2, 0.2);
        await h.page.evaluate(() => window.__stat.show(2));
      },
      tail: 0.8,
    },
    // ============================================================ the turn
    {
      id: "turn",
      chapter: "What Raahat does",
      kind: "card",
      tag: "Pukaar Raahat",
      screen: "The wordmark, the one-liner and the three people in the loop, appearing as they are said.",
      card: {
        mode: "turn",
        brandHi: "पुकार राहत",
        brandEn: "Pukaar Raahat",
        one: "Pukaar warns the village. Raahat sends [the money before the river], on a rule anyone can check.",
        who: [
          { icon: "officer", big: "District officer", small: "releases each tranche in one tap" },
          { icon: "pradhan", big: "Village pradhan", small: "attests the flood, records receipts" },
          { icon: "villager", big: "Anyone", small: "checks every rupee: no wallet, no account" },
        ],
      },
      lines: [
        L("Today, Pukaar warns villages before a flood, | live on AWS."),
        L("Raahat adds the money: | released before the river, | on a sealed rule, | every rupee on a public chain."),
      ],
      async run(h) {
        await h.page.evaluate(() => window.__turn.show(0));
        await h.cue(1, -0.1);
        await h.page.evaluate(() => window.__turn.show(1));
        await h.chunk(1, 1, 0);
        await h.page.evaluate(() => window.__turn.show(2));
        await h.chunk(1, 2, 0);
        await h.page.evaluate(() => window.__turn.show(3));
        await h.chunk(1, 3, 0);
        await h.page.evaluate(() => window.__turn.show(4));
      },
      tail: 0.8,
    },
    // ============================================================ the sealed rule, on the live site
    {
      id: "rule",
      chapter: "One flood, end to end",
      tag: "The sealed rule",
      screen: `/raahat on the deployed site: the pool, checked by the browser against ${f.network}, and the rule card, sealed on ${f.sealedAt}.`,
      lines: [
        L(
          `The rule is set before the monsoon: | at Warning, ₹${rupees(a)} per household; | once the flood is confirmed, ₹${rupees(c)} more; | then a ${f.cooldownHours}-hour cooldown.`,
          `The rule is set before the monsoon: | at Warning, ${sayInt(a)} rupees per household; | once the flood is confirmed, ${sayInt(c)} more; | then a ${sayInt(f.cooldownHours)}-hour cooldown.`,
        ),
        L("Then it's sealed on chain. | Nobody can change it mid-flood, | not even us."),
      ],
      async prepare(page) {
        await page.goto(`${f.liveUrl}/raahat`, { waitUntil: "domcontentloaded" });
        await page.locator(".raahat-rule").waitFor({ timeout: 60_000 });
        await page.locator(".raahat-pool .raahat-check .ok-icon").waitFor({ timeout: 60_000 }).catch(() => {});
        await page.waitForTimeout(800);
        await enlarge(page, ZOOM.site);
        await scrollTop(page.locator(".raahat-rule"), 220);
      },
      async run(h) {
        const rule = h.page.locator(".raahat-rule");
        await h.at(0.3);
        await h.box(rule.locator(".raahat-rule-line"), { dim: 0.2 });
        await h.cue(1, -0.1);
        await h.unbox();
        await h.box(rule, { dim: 0.2 });
      },
    },
    // ============================================================ the officer approves the warning
    {
      id: "approve",
      tag: "Officer console",
      screen: "The officer console (Cognito, demo account) during a labelled replay of the July 2023 Beas flood: Pandoh's pending Warning, its Hindi draft, Approve.",
      lines: [
        L("Now July 2023, | replayed on the deployed stack, | labelled as an exercise.", "Now July twenty twenty-three, | replayed on the deployed stack, | labelled as an exercise."),
        L("Pandoh reaches Warning. | The officer approves the Hindi alert | in one tap."),
      ],
      async prepare(page) {
        await signIn(page, f, "officer1");
        await page.goto(`${f.liveUrl}/console#approvals`, { waitUntil: "domcontentloaded" });
        await page.locator(".pending-card").first().waitFor({ timeout: 60_000 });
        const more = page.getByRole("button", { name: /^Show \d+ more$/ });
        if (await more.count()) await more.first().click();
        const card = page.locator(".pending-card", { hasText: "Pandoh" }).first();
        await card.waitFor({ timeout: 30_000 });
        await focusPanel(page, "approvals");
        await enlarge(page, ZOOM.console);
        await scrollTop(card, 60);
        await page.waitForTimeout(500);
      },
      async run(h) {
        const card = h.page.locator(".pending-card", { hasText: "Pandoh" }).first();
        await overlay(h.page, who("HERO USER · DEMO ACCOUNT", "Officer on duty, Mandi district", "signed in with Cognito"));
        await h.cue(1, 0);
        await unoverlay(h.page);
        await h.box(card.locator(".draft-hi"), { dim: 0.2 });
        await h.chunk(1, 2, -0.6);
        await h.unbox();
        await card.locator(".btn-approve").click();
        await h.page.locator("dialog[open] .btn-accent").waitFor({ timeout: 5000 });
        await h.page.waitForTimeout(450);
        await h.page.locator("dialog[open] .btn-accent").click();
      },
      tail: 1.2,
    },
    // ============================================================ the anchor, re-verified in the browser
    {
      id: "anchor",
      tag: "Anchored on chain",
      screen: "/raahat?alert=… on the deployed site: Pandoh's ledger row with the REPLAY chip and its chain receipt (exercise=true); Re-verify fetches the public CAP feed and hashes it in the browser.",
      lines: [
        L("As it goes out, | the alert is anchored on Base."),
        L("Re-verify fetches the public alert feed | and hashes it in your browser. | It matches."),
      ],
      async prepare(page) {
        await until(f, `/raahat/alerts/${live.alert}`, (r) => r.state === "sent", "the anchor");
        await page.goto(`${f.liveUrl}/raahat?alert=${live.alert}`, { waitUntil: "domcontentloaded" });
        await page.locator(".chain-receipt .chain-verify button").waitFor({ timeout: 60_000 });
        await page.waitForTimeout(800);
        await enlarge(page, ZOOM.site);
        await scrollTop(page.locator(".ledger-row.is-focus"), 60);
        await page.waitForTimeout(400);
      },
      async run(h) {
        const rc = h.page.locator(".chain-receipt");
        await h.at(0.2);
        await h.box(rc, { dim: 0.2 });
        await h.cue(1, -0.2);
        await h.unbox();
        await h.scrollTo(rc.locator(".chain-verify"), { offset: 420, ms: 600 });
        await rc.locator(".chain-verify button").click();
        await h.box(rc.locator(".chain-verify"), { dim: 0.2 });
      },
      tail: 0.6,
    },
    // ============================================================ tier 1, before the water
    {
      id: "tier1",
      tag: "Tier 1 · before the water",
      screen: "The officer console's Release relief panel: Pandoh's tier 1 (households × the anticipatory amount, illustrative), Release, the confirm dialog, then Released with its transaction.",
      lines: [
        L(`Code checks the sealed rule: | Pandoh is at Warning, | ${n} households registered.`, `Code checks the sealed rule: | Pandoh is at Warning, | ${sayInt(n)} households registered.`),
        L(`One tap releases tier one, | before the water: | ${n} times ₹${rupees(a)}.`, `One tap releases tier one, | before the water: | ${sayInt(n)} times ${sayInt(a)} rupees.`),
        L("The contract checks the rule again, | and pays."),
      ],
      async prepare(page) {
        await reliefCard(page, f, live.alert);
        await page.locator(".relief-card .relief-tier .btn-accent").first().waitFor({ timeout: 60_000 });
      },
      async run(h) {
        const card = h.page.locator(".relief-card").first();
        await overlay(h.page, TEST_MONEY);
        await h.box(card.locator(".relief-tier").first(), { dim: 0.2 });
        await h.chunk(1, 0, 0.3);
        await h.unbox();
        await card.locator(".relief-tier .btn-accent").first().click();
        await h.page.locator("dialog[open] .btn-accent").waitFor({ timeout: 5000 });
        await h.page.waitForTimeout(900);
        await h.page.locator("dialog[open] .btn-accent").click();
        later(async () => {
          await card.locator(".relief-tier .ok-text").first().waitFor({ timeout: 40_000 });
          await h.box(card.locator(".relief-tier").first(), { dim: 0.2 });
        });
      },
      tail: 1.2,
    },
    // ============================================================ the pradhan attests
    {
      id: "pradhan",
      chapter: "Three keys confirm the flood",
      tag: "Pradhan attests",
      screen: "The console signed in as Pandoh's pradhan (demo account): Flood confirmation (2 of 3), attesting from a verified photo report (a labelled DEMO photo filed for the replay).",
      lines: [
        L("After the flood, | three independent keys can confirm it."),
        L("Pandoh's pradhan attests first, | from a verified photo of the village."),
      ],
      async prepare(page) {
        await until(f, `/raahat/ledger`, (r) => r.items?.some((i) => i.alert_id === live.alert && i.releases.some((x) => x.tier === 1 && x.state === "sent")), "tier 1 on chain", 120);
        const card = await reliefCard(page, f, live.alert, "pradhan_pandoh");
        await card.locator(".attest-form select").last().waitFor({ timeout: 30_000 });
        await scrollTop(card.locator(".attest"), 160);
        await page.waitForTimeout(400);
      },
      async run(h) {
        const box = h.page.locator(".relief-card .attest").first();
        await overlay(h.page, who("DEMO ACCOUNT", "Pradhan, Pandoh", "the village's elected head"), "right");
        await h.box(box.locator(".chips-row"), { dim: 0.2 });
        await h.cue(1, 0);
        await h.unbox();
        await unoverlay(h.page);
        const selects = box.locator(".attest-form select");
        await selects.first().selectOption("2");
        await selects.last().selectOption({ index: 1 });
        await h.page.waitForTimeout(500);
        await box.getByRole("button", { name: "Send attestation" }).click();
      },
      tail: 1.0,
    },
    // ============================================================ the officer attests, and the satellite
    {
      id: "officer",
      tag: "Officer and satellite attest",
      screen: "The officer console: the officer attests severity 2 with a short note, the chips turn green, \"Confirmed\", then Run the satellite check (Sentinel-2).",
      lines: [
        L("The district officer attests, | severity two."),
        L("Two of three agree: | the flood is confirmed."),
        L("And the satellite adds a third."),
      ],
      async prepare(page) {
        await until(f, `/raahat/alerts/${live.alert}/attestations`, (r) => r.attestations?.pradhan?.on_chain, "the pradhan's attestation", 120);
        const card = await reliefCard(page, f, live.alert);
        await card.locator(".attest-form input").first().waitFor({ timeout: 30_000 });
        await scrollTop(card.locator(".attest"), 160);
        await page.waitForTimeout(400);
      },
      async run(h) {
        const box = h.page.locator(".relief-card .attest").first();
        await box.locator(".attest-form select").first().selectOption("2");
        await box.locator(".attest-form input").first().pressSequentially("Road to Pandoh dam under water", { delay: 28 });
        await box.getByRole("button", { name: "Attest as officer" }).click();
        await h.cue(1, -0.2);
        // no box here: tier 2's Release button appears above the chips as the flood is confirmed, moving them
        await h.cue(2, -0.3);
        const sat = box.getByRole("button", { name: /Run the satellite check/ });
        later(async () => {
          await sat.waitFor({ timeout: 20_000 });
          for (let i = 0; i < 40 && !(await sat.isEnabled()); i++) await h.page.waitForTimeout(250);
          await sat.click();
        });
      },
      tail: 1.0,
    },
    // ============================================================ the satellite's evidence
    {
      id: "sat",
      kind: "card",
      tag: "Satellite evidence",
      screen: `Sentinel-2 before and after over the Beas around Pandoh dam (AWS Open Data), as served by the live site; the water measured, the severity, and the evidence hash put on chain (keccak256 of the public after-flood water-mask PNG).`,
      card: {
        mode: "sat",
        title: "The satellite [measures the water]",
        before: { src: `${f.liveUrl}/satellite/2023/2023-06-03.jpg`, label: "3 June 2023 · before" },
        after: { src: `${f.liveUrl}/satellite/2023/${s.date}.jpg`, label: `${new Date(s.date).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })} · after` },
        facts: [
          { k: `${s.before} → ${s.after.toFixed(2)} km²`, small: `water, over ${s.compared} km² compared` },
          { k: `Severity ${s.severity}`, small: "by a fixed rule, not a model" },
        ],
        hash: `evidence on chain: ${s.hash}`,
      },
      lines: [
        L(
          `Sentinel-2 images of the river, | before and after: | water went from ${s.before} to ${s.after.toFixed(2)} square kilometres.`,
          `Sentinel two images of the river, | before and after: | water went from ${sayDec(s.before)} to ${sayDec(s.after.toFixed(1))} square kilometres.`,
        ),
        L("Severity three. | The image's hash goes on chain, | so anyone can check it."),
      ],
      async run(h) {
        await h.page.evaluate(() => window.__sat.show(0));
        await h.chunk(0, 1, 0);
        await h.page.evaluate(() => window.__sat.show(1));
        await h.chunk(0, 2, 0);
        await h.page.evaluate(() => window.__sat.show(2));
        await h.cue(1, 0);
        await h.page.evaluate(() => window.__sat.show(3));
        await h.chunk(1, 1, 0);
        await h.page.evaluate(() => window.__sat.show(4));
      },
      tail: 0.6,
    },
    // ============================================================ tier 2
    {
      id: "tier2",
      tag: "Tier 2 · confirmed",
      screen: "The officer console: three green attestation chips, Confirmed, and tier 2 released.",
      lines: [
        L(`Confirmation unlocks tier two: | ₹${rupees(c)} for each household.`, `Confirmation unlocks tier two: | ${sayInt(c)} rupees for each household.`),
        L("The contract checks the three keys itself."),
      ],
      async prepare(page) {
        await until(f, `/raahat/alerts/${live.alert}/attestations`, (r) => r.confirmed && r.attestations?.satellite?.on_chain, "the satellite's attestation", 120);
        const card = await reliefCard(page, f, live.alert);
        await card.locator(".relief-tier .btn-accent").first().waitFor({ timeout: 60_000 });
        await scrollTop(card.locator(".relief-tier").nth(1), 200);
      },
      async run(h) {
        const card = h.page.locator(".relief-card").first();
        await overlay(h.page, TEST_MONEY);
        await h.chunk(0, 1, -0.2);
        await card.locator(".relief-tier .btn-accent").first().click();
        await h.page.locator("dialog[open] .btn-accent").waitFor({ timeout: 5000 });
        await h.page.waitForTimeout(700);
        await h.page.locator("dialog[open] .btn-accent").click();
      },
      tail: 1.6,
    },
    // ============================================================ receipts
    {
      id: "receipts",
      tag: "Receipts",
      screen: "The pradhan's console: the household list (labels and hashes only), a demo UPI reference typed in, Record receipt, Receipt recorded.",
      lines: [
        L("The pradhan records each payment's UPI reference.", "The pradhan records each payment's U P I reference."),
        L("On chain, it's a receipt for a hashed household: | no name, | no phone number."),
      ],
      async prepare(page) {
        await until(f, `/raahat/ledger`, (r) => r.items?.some((i) => i.alert_id === live.alert && i.releases.some((x) => x.tier === 2 && x.state === "sent")), "tier 2 on chain", 120);
        const card = await reliefCard(page, f, live.alert, "pradhan_pandoh");
        await card.locator(".receipt-entry input").first().waitFor({ timeout: 30_000 });
        await scrollTop(card.locator(".table-wrap"), 160);
        await page.waitForTimeout(400);
      },
      async run(h) {
        const table = h.page.locator(".relief-card .table-wrap").first();
        await overlay(h.page, who("DEMO REFERENCES", "No real payment", "tINR is test money"), "right");
        const input = table.locator(".receipt-entry input").first();
        await input.pressSequentially("UPI-PANDOH-DEMO-0001", { delay: 35 });
        await table.locator(".receipt-entry button").first().click();
        await h.cue(1, -0.2);
        await h.box(table.locator("tbody tr").first(), { dim: 0.2 });
      },
      tail: 1.0,
    },
    // ============================================================ the public ledger
    {
      id: "ledger",
      chapter: "The public ledger",
      tag: "Public ledger",
      screen: "/raahat on the deployed site, signed out: Pandoh's row (REPLAY) with every step and its transaction links, and the totals kept apart for live and replay.",
      lines: [L("It all lands on one public page: | the alert, both tranches, | three confirmations, | the receipts.")],
      async prepare(page) {
        await new Promise((r) => setTimeout(r, 4000)); // the receipt from the last scene reaches the chain
        await page.goto(`${f.liveUrl}/raahat?alert=${live.alert}`, { waitUntil: "domcontentloaded" });
        await page.locator(".ledger-row.is-focus .ledger-steps").waitFor({ timeout: 60_000 });
        await page.waitForTimeout(1000);
        await enlarge(page, ZOOM.site);
        await scrollTop(page.locator(".ledger-row.is-focus"), 60);
        await page.waitForTimeout(400);
      },
      async run(h) {
        const row = h.page.locator(".ledger-row.is-focus");
        await h.at(0.2);
        await h.box(row.locator(".ledger-steps"), { dim: 0.2 });
      },
      tail: 0.4,
    },
    // ============================================================ the same transaction, on a public explorer
    {
      id: "explorer",
      tag: "Public explorer",
      // BaseScan puts headless browsers behind a bot check; Blockscout is an independent explorer of the same chain
      userAgent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
      // its ad slot is not part of the transaction: the ad network and the banner images are not loaded
      async context(ctx) {
        await ctx.route(/adx\.ws|id5-sync\.com|blockscout-marketing-banners/, (r) => r.abort());
      },
      screen: "Tier 1's release transaction on Blockscout (an independent public explorer for Base Sepolia): success, the ReliefPool call and the tINR token transfer.",
      lines: [L("Anyone can open every transaction: | no wallet, | no account.")],
      async prepare(page) {
        const ledger = await until(f, "/raahat/ledger", (r) => r.items?.some((i) => i.alert_id === live.alert), "the ledger row", 60);
        const tx = ledger.items.find((i) => i.alert_id === live.alert).releases.find((x) => x.tier === 1)?.tx;
        if (!tx) throw new Error("no tier 1 transaction in the ledger");
        await page.goto(`https://base-sepolia.blockscout.com/tx/${tx}`, { waitUntil: "domcontentloaded" });
        await page.getByText(/Success/i).locator("visible=true").first().waitFor({ timeout: 90_000 });
        await page.waitForTimeout(2500);
        await enlarge(page, ZOOM.explorer);
        // the explorer's ad slot (a "Sponsored" row) is not part of the transaction: hide its label and banner cells
        await page.evaluate(() => {
          const label = [...document.querySelectorAll("div")].find((e) => e.textContent.trim() === "Sponsored" && !e.children.length);
          // every grid cell from that label up to the "From" row
          for (let e = label?.parentElement; e && !/^From/.test(e.textContent.trim()); e = e.nextElementSibling) e.style.display = "none";
        });
      },
      async run(h) {
        await overlay(h.page, who("BLOCKSCOUT · BASE SEPOLIA", "Tier 1, on a public explorer", "no sign-in; anyone can open it"), "right");
        await h.chunk(0, 1, -0.2);
        // down to "Tokens transferred": 45,000 tINR from the pool
        await h.page.evaluate(() => {
          const row = [...document.querySelectorAll("div")].find((e) => /^Tokens transferred/.test(e.textContent.trim()) && !e.children.length);
          if (row) window.__v.scrollTo(row.getBoundingClientRect().top + scrollY - 560, 1400);
        });
      },
      tail: 0.5,
    },
    // ============================================================ why a chain
    {
      id: "why",
      chapter: "Why a chain",
      kind: "card",
      tag: "Why a chain",
      screen: "Four reasons, each landing as it is said.",
      card: {
        mode: "ticks",
        title: "Why a [chain]?",
        rows: [
          { icon: "lock", big: "A sealed rule", small: "nobody changes it mid-flood, not even us" },
          { icon: "three", big: "2 of 3 keys confirm", small: "pradhan, officer, satellite: no one person decides" },
          { icon: "receipt", big: "Public receipts", small: "households hashed; no names or phones on chain" },
          { icon: "voice", big: "Warnings never wait", small: "a chain failure is logged and skipped" },
        ],
      },
      lines: [
        L("Why a chain? | A rule nobody can quietly change, | a confirmation no one person controls, | receipts anyone can audit."),
        L("And if the chain is down, | the warning still goes out."),
      ],
      async run(h) {
        for (const [k, [li, ch]] of [[0, 1], [0, 2], [0, 3], [1, 0]].entries()) {
          await h.chunk(li, ch, -0.1);
          await h.page.evaluate((k) => window.__ticks.show(k), k);
        }
      },
      tail: 0.6,
    },
    // ============================================================ the chain, read now
    {
      id: "proof",
      tag: "Live proof",
      kind: "card",
      screen: `Real output of cast (Foundry) against ${f.network}, captured when this scene was recorded: the rule sealed, the alert marked exercise, the flood confirmed by three attesters, both tranches released, the receipts.`,
      get card() {
        return { mode: "terminal", title: "On Base Sepolia, right now", eyebrow: `ReliefPool ${f.deployment.pool}`, bar: "cast (Foundry) · read-only", ...chainProof(f, live.alert) };
      },
      lines: [
        L("Read from Base Sepolia right now: | the rule sealed, | the alert marked as an exercise, | three attesters, | both tranches, | the receipt."),
        L(`${f.forgeTests} contract tests, | ${f.forgeCoverage === 100 ? "full" : `${f.forgeCoverage}%`} coverage.`, `${sayInt(f.forgeTests)} contract tests, | ${f.forgeCoverage === 100 ? "full" : `${sayInt(f.forgeCoverage)} percent`} coverage.`),
      ],
      async run(h) {
        await h.page.evaluate(() => window.__term.group(0));
        await h.chunk(0, 2, -0.3);
        await h.page.evaluate(() => window.__term.group(1));
        await h.chunk(0, 3, -0.3);
        await h.page.evaluate(() => window.__term.group(2));
        await h.chunk(0, 4, -0.3);
        await h.page.evaluate(() => window.__term.group(3));
      },
      tail: 0.6,
    },
    // ============================================================ what is not real yet
    {
      id: "honest",
      chapter: "Limits and close",
      tag: "Not real yet",
      kind: "card",
      screen: "Three honest limits, each with what would replace it.",
      card: {
        mode: "gaps",
        title: "What's [not real] yet",
        strike: false, // the gaps are still true today; the right-hand side is what comes next
        rows: [
          { gap: "tINR is a test token", icon: "coins", big: "Next: a licensed INR partner", small: "pays real rupees to UPI" },
          { gap: "The amounts are illustrative", icon: "scale", big: "Next: SDRF norms", small: "mapped with the district authority (DDMA)" },
          { gap: "Our server holds testnet keys", icon: "key", big: "Next: keys on their own devices", small: "officers and pradhans sign themselves" },
        ],
      },
      lines: [
        L("What's not real yet: | the money is a test token."),
        L("The amounts await the state's relief norms, | and our server holds the testnet keys."),
      ],
      async run(h) {
        await h.chunk(0, 1, -0.1);
        await h.page.evaluate(() => window.__gaps.show(0));
        await h.cue(1, -0.1);
        await h.page.evaluate(() => window.__gaps.show(1));
        await h.chunk(1, 1, -0.1);
        await h.page.evaluate(() => window.__gaps.show(2));
      },
      tail: 0.8,
    },
    // ============================================================ close
    {
      id: "close",
      kind: "card",
      bar: false,
      tag: "Pukaar Raahat",
      screen: "End card: the callback line, the wordmark, the live URL, the repository and what it runs on.",
      card: {
        mode: "close",
        brandHi: "पुकार राहत",
        brandEn: "Pukaar Raahat",
        call: "The river will still rise.\n[Now help reaches first.]",
        url: `${f.liveUrl.replace("https://", "")}/raahat`,
        meta: [`${f.repoUrl.replace("https://", "")} · branch web3-social-good`, "AWS + Base Sepolia (testnet) · Web3 for Social Good 2026"],
      },
      lines: [L("The river will still rise. | Now help reaches first.")],
      tail: 4.5,
      async run(h) {
        await h.page.evaluate(() => window.__close.show(0));
        await h.at(h.tl.lines[0].end + 0.2);
        await h.page.evaluate(() => window.__close.show(1));
      },
    },
  ];
}

export const outputs = {
  narrated: "pukaar-raahat.mp4",
  silent: "pukaar-raahat-silent.mp4",
  srt: "pukaar-raahat.srt",
  poster: "pukaar-raahat-poster.png",
  transcript: "pukaar-raahat-narration.txt",
};
export const poster = { scene: "sat", at: 7 };
export const timing = { lead: 0.1, gap: 0.12, tail: 0.25, gapAfter: { ".": 0.45, "?": 0.6, ":": 0.35, ";": 0.35, ",": 0.25 } };
export const crf = 18;
export const tts = { speed: 1.08, speed_max_cps: 22, max_cps: 23 };

/** The score, cued to the film: tense under the hook, sombre over the footage, hope with the evidence, then a
 *  driving 112 bpm through the demo, building through the confirmation, reflecting on the limits, resolving at the
 *  close; hits on the brand and the reveals, a short drop before the brand. */
export const music = {
  speech_lufs: -29,
  gap_db: 6,
  fade_in: 0.5,
  fade_out: 3,
  target_lufs: -14,
  cues(tls, total) {
    // built from the scenes present, so a --preview of a few scenes gets its own score
    const at = (id) => tls.find((t) => t.id === id);
    const start = (id) => at(id)?.start;
    const line = (id, i) => (at(id) ? at(id).start + at(id).lines[i].start : undefined);
    const MOOD = [
      ["hook", { mood: "tense" }],
      ["problem", { mood: "sombre" }],
      ["evidence", { mood: "hope" }],
      ["turn", { mood: "drive", bpm: 112, gain_db: -1 }],
      ["pradhan", { mood: "build", bpm: 112, gain_db: -1 }],
      ["why", { mood: "drive", bpm: 112, gain_db: -1 }],
      ["honest", { mood: "reflect" }],
      ["close", { mood: "resolve" }],
    ].filter(([id]) => at(id));
    const sections = MOOD.map(([id, m], k) => ({ from: k ? start(id) : 0, to: k + 1 < MOOD.length ? start(MOOD[k + 1][0]) : total, ...m }));
    const brand = line("hook", 2);
    const has = (t) => t !== undefined;
    return {
      sections,
      hits: [brand, start("turn") + 0.1, line("evidence", 2), start("sat") + 0.1, start("close") + 0.2].filter((t) => has(t) && !Number.isNaN(t)),
      drops: has(brand) ? [[brand - 0.5, 0.45]] : [],
      sfx: [
        ...(has(brand) ? [{ name: "riser", t: brand - 1.6, gain: -16, dur: 1.6 }] : []),
        ...["problem", "evidence", "turn", "rule", "pradhan", "sat", "ledger", "explorer", "why", "proof", "honest", "close"]
          .filter((id) => start(id) > 0)
          .map((id) => ({ name: "whoosh", t: start(id) - 0.25, gain: -20 })),
        ...(has(start("close")) ? [{ name: "swell", t: start("close"), gain: -16 }] : []),
      ],
    };
  },
};

export const scriptDoc = {
  path: "docs/submission/w3sg-film-script.md",
  head: ({ total, words, wpm, mmss, chapters }) => `# Pukaar Raahat film script (${mmss(total)})

The narration of [docs/media/pukaar-raahat.mp4](../media/pukaar-raahat.mp4) (${total.toFixed(1)} s, 1920×1080), rendered by \`node video/record.mjs raahat\` from [video/raahat.mjs](../../video/raahat.mjs) after \`node video/raahat-live.mjs\` staged the stack; this file is written by the same run, so the times and words below are the film's own. Timed captions: [pukaar-raahat.srt](../media/pukaar-raahat.srt).

Every number is read at render time: the rule's amounts and cooldown from the live API (the sealed rule on chain), Pandoh's household count from ReliefPool on Base Sepolia, the WFP figures from w3sg-sources.md, the Mandi 2025 figures and the Foundry test count from README.md, the satellite figures from data/raahat/satellite_2023.json, and the proof scene's output from \`cast\` against Base Sepolia when that scene was recorded. The live scenes are the deployed stack during a labelled replay (exercise=true on chain); tINR is a test token with no value, and every amount is ${ILLUSTRATIVE}. The voice is Chatterbox TTS (open source) with its own built-in synthetic voice. ${words} words in ${total.toFixed(0)} s (${wpm} words a minute).

## Chapters

\`\`\`
${chapters.join("\n")}
\`\`\`

## Video description

\`\`\`
Pukaar Raahat (पुकार राहत): flood relief that reaches a Himalayan village before the river does, on a rule anyone can check. Pukaar's warning loop runs on AWS; Raahat anchors each alert on Base, releases relief on a rule sealed before the monsoon, confirms the flood with two of three independent keys (pradhan, officer, Sentinel-2) and records each household's receipt without personal data.

Testnet demo: tINR is a test token with no value; amounts are ${ILLUSTRATIVE}. The flood shown is a labelled replay of July 2023.

Live: ${liveForDoc}/raahat
Code: https://github.com/Prashant-thakur77/pukaar (branch web3-social-good)

${chapters.join("\n")}

Voice: Chatterbox TTS (open source) with its built-in synthetic voice.
Music and sound effects: synthesised for this video by video/narration/score.py and sfx.py (CC0). Stock footage: Pexels (Pexels License), credits in docs/media/CREDITS.md.
\`\`\``,
};
