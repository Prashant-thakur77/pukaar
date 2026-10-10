#!/usr/bin/env node
// Sets the live stack up for the demo's live scenes, then hands over to `node video/record.mjs demo`:
//   1. signs in as the demo officer (Cognito, USER_PASSWORD_AUTH; the password stays in .env.demo.local),
//   2. resets the demo state and starts the July 2023 replay on AWS (real sweeps, real Step Functions executions;
//      replay alerts are labelled and only ever reach the stub test phones),
//   3. waits until Gohar's alert is pending at Critical with its Polly audio drafted,
//   4. copies that real Polly MP3 to video/.out/polly-gohar.mp3 for the soundtrack.
// The approval wait is 10 minutes per officer, so record within about 15 minutes of this finishing.
//   node video/live.mjs [--speed 1.5]
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { ROOT, log, sleep } from "./lib/engine.mjs";
import { REGION, STACK } from "./lib/facts.mjs";

const arg = (k, d) => {
  const i = process.argv.indexOf(k);
  return i > 0 ? process.argv[i + 1] : d;
};
const aws = (...a) => JSON.parse(execFileSync("aws", [...a, "--region", REGION, "--output", "json"], { encoding: "utf8" }));
const outs = Object.fromEntries(
  aws("cloudformation", "describe-stacks", "--stack-name", STACK).Stacks[0].Outputs.map((o) => [o.OutputKey, o.OutputValue]),
);
const pw = readFileSync(join(ROOT, ".env.demo.local"), "utf8").match(/^PUKAAR_DEMO_PASSWORD=(.+)$/m)[1].trim().replace(/^["']|["']$/g, "");
const clientId = outs.UserPoolClientId ?? outs.ClientId ?? outs.CognitoClientId;
const token = aws("cognito-idp", "initiate-auth", "--client-id", clientId, "--auth-flow", "USER_PASSWORD_AUTH",
  "--auth-parameters", `USERNAME=officer1,PASSWORD=${pw}`).AuthenticationResult.IdToken;
const api = async (path, opts = {}) => {
  const r = await fetch(outs.ApiUrl + path, {
    method: opts.method ?? "GET",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!r.ok) throw new Error(`${opts.method ?? "GET"} ${path}: ${r.status} ${await r.text()}`);
  return r.json();
};

log("reset demo state");
await api("/replay/reset", { method: "POST", body: {} });
await sleep(3000);
const speed = Number(arg("--speed", "1.5"));
log(`start replay at ${speed} s per hour`);
const st = await api("/replay/start", { method: "POST", body: { speed_seconds_per_hour: speed } });
log(`replay: ${st.title ?? st.scenario}, ${st.hours_total} hours`);

let gohar = null;
for (let i = 0; i < 160; i++) {
  await sleep(5000);
  const pending = await api("/alerts?status=pending&village_id=gohar");
  gohar = pending.find((a) => a.level === "critical" && a.has_audio) ?? null;
  const all = await api("/alerts");
  log(`  ${i * 5 + 5} s: ${all.length} alerts; gohar ${pending.map((a) => a.level).join(",") || "-"}`);
  if (gohar) break;
}
if (!gohar) throw new Error("no pending critical Gohar alert with audio");

// a village pradhan tries to approve: Cedar refuses, and the refusal is in the audit log (a real deny row)
const ptoken = aws("cognito-idp", "initiate-auth", "--client-id", clientId, "--auth-flow", "USER_PASSWORD_AUTH",
  "--auth-parameters", `USERNAME=pradhan_thunag,PASSWORD=${pw}`).AuthenticationResult.IdToken;
const denied = await fetch(`${outs.ApiUrl}/alerts/${gohar.id}/approve`, {
  method: "POST",
  headers: { authorization: `Bearer ${ptoken}`, "content-type": "application/json" },
  body: "{}",
});
log(`pradhan approve attempt: ${denied.status} (expected 403)`);

// copy the real Polly MP3 for the soundtrack
const bucket = aws("cloudformation", "describe-stack-resources", "--stack-name", STACK).StackResources.find(
  (r) => r.ResourceType === "AWS::S3::Bucket",
).PhysicalResourceId;
mkdirSync(join(ROOT, "video/.out"), { recursive: true });
execFileSync("aws", ["s3", "cp", `s3://${bucket}/audio/alerts/${gohar.id}.mp3`, join(ROOT, "video/.out/polly-gohar.mp3"), "--region", REGION]);
writeFileSync(join(ROOT, "video/.out/live.json"), JSON.stringify({ goharAlert: gohar.id, at: new Date().toISOString() }, null, 1));
log(`ready: ${gohar.id} pending at critical; Polly MP3 saved. Record now: node video/record.mjs demo`);
