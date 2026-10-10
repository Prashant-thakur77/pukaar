// Every number the videos say or show, read at render time. A number that cannot be found fails the render.
//   repo:  data/backtest.json, frontend/src/data/story-gohar-2023.json, README.md
//   live:  the deployed API (/health, /villages)
//   AWS:   the CloudFormation stack, its alarms and the approval state machine's executions (aws CLI, us-east-1)
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";

export const STACK = "pukaar-dev";
export const REGION = "us-east-1";

const need = (v, what) => {
  if (v === undefined || v === null || v === "" || (typeof v === "number" && !Number.isFinite(v)))
    throw new Error(`facts: could not find ${what}`);
  return v;
};
const aws = (...args) =>
  JSON.parse(execFileSync("aws", [...args, "--region", REGION, "--output", "json"], { encoding: "utf8" }));

export async function pukaarFacts(ROOT) {
  const readme = readFileSync(join(ROOT, "README.md"), "utf8");
  const story = JSON.parse(readFileSync(join(ROOT, "frontend/src/data/story-gohar-2023.json"), "utf8"));
  const bt = JSON.parse(readFileSync(join(ROOT, "data/backtest.json"), "utf8"));

  // README: the sourced Mandi 2025 figures and the measured 3G load
  const dte = readme.match(/at least (\d+)\s+people dead and (\d+) missing/);
  const g3 = readme.match(/Slow 3G[^|]*\|\s*([\d.]+) s\s*\|\s*(\d+) kB/);
  const live = readme.match(/\*\*Live:\*\* (https:\/\/\S+)/);

  // back-test: 2023 villages that reached critical; 2025 the forecast's 24 h rain range at the four quiet villages
  const s23 = bt.scenarios.find((s) => s.name === "himachal_2023_07");
  const s25 = bt.scenarios.find((s) => s.name !== "himachal_2023_07");
  const crit23 = s23.villages.filter((v) => v.first_critical).map((v) => v.village);
  const gohar = s23.villages.find((v) => v.village_id === "gohar");

  // live API
  const outs = Object.fromEntries(
    aws("cloudformation", "describe-stacks", "--stack-name", STACK).Stacks[0].Outputs.map((o) => [
      o.OutputKey,
      o.OutputValue,
    ]),
  );
  const api = need(outs.ApiUrl, "the stack's ApiUrl output");
  const health = await (await fetch(`${api}/health`)).json();
  const villages = await (await fetch(`${api}/villages`)).json();

  // AWS account
  const resources = aws("cloudformation", "list-stack-resources", "--stack-name", STACK).StackResourceSummaries;
  const types = new Set(resources.map((r) => r.ResourceType));
  const lambdas = resources.filter((r) => r.ResourceType === "AWS::Lambda::Function").length;
  const alarms = resources.filter((r) => r.ResourceType === "AWS::CloudWatch::Alarm").length;
  const sm = resources.find((r) => r.ResourceType === "AWS::StepFunctions::StateMachine").PhysicalResourceId;
  const execs = aws("stepfunctions", "list-executions", "--state-machine-arn", sm, "--max-results", "100").executions;

  return {
    liveUrl: need(live?.[1], "the live URL in README.md"),
    apiUrl: api,
    repoUrl: "https://github.com/Prashant-thakur77/pukaar",
    mandiDead: Number(need(dte?.[1], "the Down To Earth death toll in README.md")),
    mandiMissing: Number(need(dte?.[2], "the Down To Earth missing count in README.md")),
    slow3gSeconds: Number(need(g3?.[1], "the slow 3G load time in README.md")),
    slow3gKb: Number(need(g3?.[2], "the slow 3G download size in README.md")),
    imd: need(story.imd_bands_mm, "IMD bands"),
    leadHours: need(story.lead_hours_watch_to_peak_day, "Gohar's lead time"),
    goharFirst: need(story.first, "Gohar's first levels"),
    goharWatchMark: need(gohar?.thresholds?.watch, "Gohar's watch discharge"),
    crit2023: crit23,
    rain2025: s25.villages.map((v) => v.max_rain_24h_mm).filter((x) => x != null),
    health: { status: need(health.status, "/health status"), mode: health.mode, telegram: health.services?.telegram },
    villages: need(villages.length, "village count"),
    stack: {
      resources: resources.length,
      lambdas: need(lambdas, "Lambda count"),
      alarms: need(alarms, "alarm count"),
      types: types.size,
      stateMachine: sm,
      executions: execs.length,
      succeeded: execs.filter((e) => e.status === "SUCCEEDED").length,
    },
  };
}
