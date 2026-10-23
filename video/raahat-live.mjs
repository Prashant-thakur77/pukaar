#!/usr/bin/env node
// Sets the Raahat stack up for the film's live scenes, then hands over to `node video/record.mjs raahat`:
//   1. resets the demo state (make reset-demo STAGE=raahat) and the replays' cooldowns on chain (make
//      raahat-reset-exercise STAGE=raahat; live cooldowns are never touched),
//   2. signs in as the demo officer (Cognito; the password stays in .env.deploy.raahat.local) and starts the July
//      2023 replay on AWS (labelled everywhere, exercise=true on chain),
//   3. files the labelled DEMO photo as Pandoh's verified replay report (after the start: starting a replay clears
//      the last replay's reports),
//   4. waits until Pandoh's alert is pending at Warning or above, and writes its id to video/.out/raahat-live.json.
// The approval wait is 10 minutes per officer, so record within about 8 minutes of this finishing.
//   node video/raahat-live.mjs [--speed 2]
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { ROOT, log, sleep } from "./lib/engine.mjs";
import { RAAHAT_STACK, REGION } from "./raahat.mjs";

const arg = (k, d) => {
  const i = process.argv.indexOf(k);
  return i > 0 ? process.argv[i + 1] : d;
};
const aws = (...a) => JSON.parse(execFileSync("aws", [...a, "--region", REGION, "--output", "json"], { encoding: "utf8" }));
const make = (target) => execFileSync("make", [target, "STAGE=raahat"], { cwd: ROOT, encoding: "utf8" });
const outs = Object.fromEntries(
  aws("cloudformation", "describe-stacks", "--stack-name", RAAHAT_STACK).Stacks[0].Outputs.map((o) => [o.OutputKey, o.OutputValue]),
);
const pw = readFileSync(join(ROOT, ".env.deploy.raahat.local"), "utf8").match(/^PUKAAR_DEMO_PASSWORD=(.+)$/m)[1].trim().replace(/^["']|["']$/g, "");
const token = aws("cognito-idp", "initiate-auth", "--client-id", outs.UserPoolClientId, "--auth-flow", "USER_PASSWORD_AUTH",
  "--auth-parameters", `USERNAME=officer1,PASSWORD=${pw}`).AuthenticationResult.IdToken;
const api = async (path, opts = {}) => {
  const r = await fetch(outs.ApiUrl + path, {
    method: opts.method ?? "GET",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    signal: AbortSignal.timeout(30_000),
  });
  if (!r.ok) throw new Error(`${opts.method ?? "GET"} ${path}: ${r.status} ${await r.text()}`);
  return r.json();
};

log("reset demo state and the replays' cooldowns on chain");
make("reset-demo");
make("raahat-reset-exercise");
const pool = await api("/raahat/pool");
const need = 30n * (BigInt(pool.rule.amount_anticipatory_wei) + BigInt(pool.rule.amount_confirmed_wei));
if (BigInt(pool.pool.balance_wei) < need) throw new Error("the pool cannot pay both tranches for 30 households: make raahat-fund STAGE=raahat");

const speed = Number(arg("--speed", "2"));
log(`start the July 2023 replay at ${speed} s per hour`);
await api("/replay/start", { method: "POST", body: { scenario: "himachal_2023_07", speed_seconds_per_hour: speed } });
const photo = make("raahat-demo-photo").match(/rep_[a-z0-9]+/)?.[0];
if (!photo) throw new Error("make raahat-demo-photo printed no report id");
log(`demo photo report: ${photo}`);

let pandoh = null;
for (let i = 0; i < 160 && !pandoh; i++) {
  await sleep(5000);
  const pending = await api("/alerts?status=pending&village_id=pandoh");
  pandoh = pending.find((a) => a.level === "warning" || a.level === "critical") ?? null;
  log(`  ${i * 5 + 5} s: pandoh ${pending.map((a) => a.level).join(",") || "-"}`);
}
if (!pandoh) throw new Error("no pending Warning or Critical alert for Pandoh");
mkdirSync(join(ROOT, "video/.out"), { recursive: true });
writeFileSync(join(ROOT, "video/.out/raahat-live.json"), JSON.stringify({ alert: pandoh.id, report: photo, at: new Date().toISOString() }, null, 1));
log(`ready: ${pandoh.id} pending at ${pandoh.level}. Record now: node video/record.mjs raahat`);
