// The pitch video (3:40-3:55, hard limit 4:00): the night in Syathi, the scale across the Himalaya, why warnings fail,
// why it can be fixed, Pukaar live on AWS, how deep the AWS stack goes, what we want to build next, and the close.
//   node video/live.mjs                 # stage the live replay first (the approve scene needs a pending alert)
//   node video/record.mjs pitch [--plan] [--only a,b]   # --only re-captures just those live scenes
// Unlike the demo, every frame is composed in video/pitch.html (stills, footage, satellite wipes, newspaper cuts,
// count-ups, live-site captures, the 3D architecture, captions) by video/lib/compose.mjs, one frame at a time on the
// narration's clock. Every number on screen carries its source line; sources are listed in SOURCES below and in
// docs/media/pukaar-pitch-credits.md.
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { L as L0, ROOT } from "./lib/engine.mjs";

/** A narration line, the name respelled for the voice only (Chatterbox read "Pukaar" as "Bukhar"). */
const L = (text, say = text, opts = {}) =>
  L0(text, say.replace(/Pukaar/g, "Poo-kaar").replace(/Syathi/g, "Syaathi"), opts);

export const SCENES = (f) => [
  // ================================================================ 1 · the night
  {
    id: "night",
    chapter: "The night",
    tag: "Mandi · 2025",
    lead: 3.4,
    gap: 0.7,
    lines: [
      L(
        "The night of 30 June 2025. | Cloudburst after cloudburst | hit Mandi district.",
        "The night of the thirtieth of June, twenty twenty-five. | Cloudburst after cloudburst | hit Mandi district.",
      ),
      L("There was a red alert for the district. | But what woke Syathi village | was not a warning.", undefined, {
        pre: 0.2,
      }),
    ],
    tail: 0.35,
  },
  {
    id: "dog",
    tag: "Syathi · 2025",
    lead: 0.25,
    gap: 0.75,
    lines: [
      L("It was a dog, barking."),
      L("The family found a crack in the wall, | and water coming in."),
      L(
        "They ran door to door. | More than 60 people got out | before the hillside came down.",
        "They ran door to door. | More than sixty people got out | before the hillside came down.",
      ),
      L("Then a survivor asked: | can we trust a dog to warn us next time?", undefined, { pre: 0.45 }),
    ],
    tail: 1.6,
  },
  // ================================================================ 2 · the scale
  {
    id: "scale",
    chapter: "Not one village",
    tag: "The scale",
    lead: 0.2,
    lines: [
      L("This is not one village."),
      L("Floods are the world's most frequent disaster."),
      L(
        "1.81 billion people live within their reach, | 390 million in India.",
        "One point eight one billion people live within their reach, | three hundred and ninety million in India.",
      ),
    ],
    tail: 0.3,
  },
  {
    id: "himalaya",
    tag: "The Himalaya",
    lead: 0.15,
    lines: [
      L("Himachal, 2023: | more than 500 lives.", "Himachal, twenty twenty-three: | more than five hundred lives."),
      L(
        "Uttarakhand, 2013: | more than 6,000 dead or never found.",
        "Uttarakhand, twenty thirteen: | more than six thousand dead or never found.",
      ),
      L("Sikkim, 2023: | a glacial lake burst in the night.", "Sikkim, twenty twenty-three: | a glacial lake burst in the night."),
      L(
        "And this August in Nepal, | a glacier collapse sent a flood down the Trishuli: | more than 1,400 dead, | over 5,700 missing.",
        "And this August in Nepal, | a glacier collapse sent a flood down the Trishuli: | more than fourteen hundred dead, | over fifty-seven hundred missing.",
      ),
    ],
    tail: 0.5,
  },
  // ================================================================ 3 · why warnings fail
  {
    id: "fail",
    chapter: "Why warnings fail",
    tag: "The last mile",
    lead: 0.3,
    lines: [
      L("The warnings exist. | They don't arrive."),
      L(
        "That morning in Nepal, | the alert text went out | 38 minutes after the collapse.",
        "That morning in Nepal, | the alert text went out | thirty-eight minutes after the collapse.",
      ),
      L("In Nepali only, | with nothing about where to go."),
      L("One man said: | the SMS and the flood came together.", "One man said: | the S M S and the flood came together.", {
        pre: 0.2,
      }),
      L("In India, | one in three people say | warnings don't reach them."),
      L("A warning only works | when someone hears it, | understands it, and acts."),
    ],
    tail: 0.5,
  },
  // ================================================================ 4 · it can be fixed
  {
    id: "hope",
    chapter: "It can be fixed",
    tag: "It can be fixed",
    lead: 0.5,
    lines: [
      L("And yet, | this can be fixed."),
      L(
        "Since 1970, weather disasters have grown five-fold, | and deaths fell almost three-fold, | with better early warning and disaster management.",
        "Since nineteen seventy, weather disasters have grown five-fold, | and deaths fell almost three-fold, | with better early warning and disaster management.",
      ),
      L(
        "In 2019, Odisha moved one and a half million people | in a day, before Cyclone Fani. | 64 died. | In 1999, nearly 10,000 had.",
        "In twenty nineteen, Odisha moved one and a half million people | in a day, before Cyclone Fani. | Sixty-four died. | In nineteen ninety-nine, nearly ten thousand had.",
      ),
    ],
    tail: 0.3,
  },
  {
    id: "school",
    tag: "Nepal · 26 Aug 2026",
    lead: 0.2,
    lines: [
      L("This August, one phone call reached a school in Nepal | minutes before the flood."),
      L(
        "The head teacher rang the bell. | More than 900 students ran up the hill.",
        "The head teacher rang the bell. | More than nine hundred students ran up the hill.",
      ),
      L("A warning works | when it reaches a person, | in time, | in their own language.", undefined, { pre: 0.3 }),
    ],
    tail: 0.4,
  },
  // ================================================================ 5 · Pukaar, live
  {
    id: "pukaar",
    chapter: "Pukaar",
    tag: "Pukaar",
    lead: 0.6,
    lines: [L("That's why we built Pukaar."), L("The call that reaches the village | before the river does.")],
    tail: 0.6,
  },
  {
    id: "sweep",
    chapter: "How it works",
    tag: "Every 15 minutes",
    lead: 0.15,
    lines: [
      L(
        "Every 15 minutes, | Pukaar reads the rain and river forecast | for each village,",
        "Every fifteen minutes, | Pukaar reads the rain and river forecast | for each village,",
      ),
      L("and live river gauges | through AWS IoT Core."),
    ],
    tail: 0.2,
  },
  {
    id: "rules",
    tag: "Code decides",
    lead: 0.1,
    lines: [
      L(
        "Code sets the level, never a model: | India's rain bands, | and each village's own 40-year river record.",
        "Code sets the level, never a model: | India's rain bands, | and each village's own forty-year river record.",
      ),
    ],
    tail: 0.3,
  },
  {
    id: "draft",
    tag: "Drafting agent",
    lead: 0.1,
    lines: [
      L("An agent drafts the Hindi alert on Amazon Bedrock."),
      L("A checker rejects any number that isn't in the decision, | and a fixed template stands by."),
    ],
    tail: 0.2,
  },
  {
    id: "approve",
    tag: "Officer console",
    lead: 0.1,
    lines: [
      L("The district officer approves with one tap, | even from the lock screen."),
      L("No answer? | Step Functions moves on | to the next officer."),
    ],
    tail: 0.3,
  },
  {
    id: "voice",
    tag: "Amazon Polly · Hindi",
    lead: 0.1,
    // the real Polly MP3 starts 0.35 s after this line (compose.mjs); 7.4 s of it plays in the clear, the rest runs
    // on under the Telegram scene, ducked, and fades out
    lines: [L("Amazon Polly speaks it in Hindi.")],
    tail: 7.8,
  },
  {
    id: "telegram",
    tag: "Telegram",
    lead: 0.2,
    lines: [
      L("Every registered phone | gets that voice on Telegram, | with one button:"),
      L("मिल गया. | Got it.", "mil gaya. | Got it.", { pre: 0.15 }),
      L("Anyone who doesn't tap it | gets it again."),
    ],
    tail: 0.3,
  },
  {
    id: "stopwatch",
    tag: "Time to ear",
    lead: 0.1,
    lines: [L("A stopwatch times every alert, | from the river rising to the first person who heard it.")],
    tail: 0.3,
  },
  {
    id: "safe",
    chapter: "After the alert",
    tag: "Are you safe?",
    lead: 0.15,
    lines: [
      L("Then Pukaar asks: | are you safe?"),
      L("It shows the nearest open shelter, | a walking route, | and which roads are blocked."),
    ],
    tail: 0.3,
  },
  {
    id: "report",
    tag: "Village reports",
    lead: 0.1,
    lines: [
      L("Villagers report back by voice, photo or text, | even offline."),
      L("Bedrock Guardrails screen every word | before any agent reads it."),
    ],
    tail: 0.3,
  },
  // ================================================================ 6 · how deep AWS goes
  {
    id: "aws",
    chapter: "Built on AWS",
    tag: "Built on AWS",
    lead: 0.4,
    lines: [
      L("All of it is one serverless stack on AWS."),
      L("EventBridge wakes Lambda every fifteen minutes, | IoT Core brings in the gauges, | DynamoDB keeps one record of truth, | and Step Functions holds each alert until an officer taps approve."),
      L("Bedrock drafts behind Guardrails. | Polly speaks, Transcribe listens, | AppSync pushes it live, | Cognito signs officers in, | S3 keeps the audio, | and CloudWatch watches it all."),
    ],
    tail: 0.3,
  },
  {
    id: "trust",
    tag: "Checked · audited · open",
    lead: 0.1,
    lines: [
      L("Cedar policy checks every action | and writes it to an audit log."),
      L(
        `${f.stack.alarms} CloudWatch alarms watch the stack,`,
        `${sayInt(f.stack.alarms)} CloudWatch alarms watch the stack,`,
      ),
      L("and every alert is published as CAP, | the standard India's national alert system uses."),
    ],
    tail: 0.4,
  },
  // ================================================================ 7 · what's next
  {
    id: "next",
    chapter: "What's next",
    tag: "What's next",
    lead: 0.3,
    lines: [
      L("We keep building, every week. | The river-gauge path already runs on AWS IoT Core, | so a reading at the bridge can raise the alarm on its own."),
      L("Next: IoT Core for LoRaWAN, | to reach bridges with no phone signal. | Greengrass, to sound a siren at the gauge itself. | And SageMaker, to learn each river's warning signs."),
      L(
        `Then calls and SMS to basic phones, | India's national alert system, | and from ${f.villages} villages to the Himalaya and Nepal.`,
        `Then calls and SMS to basic phones, | India's national alert system, | and from ${sayInt(f.villages)} villages to the Himalaya and Nepal.`,
      ),
      L("This is not a weekend project for us. | We want to build it to scale, | until every village on a Himalayan river | hears its warning in time.", undefined, { pre: 0.4 }),
    ],
    tail: 0.3,
  },
  // ================================================================ 8 · close
  {
    id: "close",
    chapter: "Close",
    tag: "Pukaar",
    lead: 0.6,
    lines: [
      L("The warning that night was a dog."),
      L("Next time, it should be a call, | in their own language, | that someone confirms they heard.", undefined, {
        pre: 0.35,
      }),
    ],
    tail: 6.5,
  },
];

const NUM = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
  "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"];
const TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];
export function sayInt(n) {
  if (n < 20) return NUM[n];
  if (n < 100) return TENS[Math.floor(n / 10)] + (n % 10 ? `-${NUM[n % 10]}` : "");
  return `${NUM[Math.floor(n / 100)]} hundred${n % 100 ? ` ${sayInt(n % 100)}` : ""}`;
}

export function scenes(f, live) {
  return SCENES(f).map((s) => {
    const out = { ...s, kind: "compose" };
    return out;
  });
}

/** The real Polly voice for the Gohar alert (video/live.mjs copies it). */
export async function probe() {
  const voice = join(ROOT, "video/.out/polly-gohar.mp3");
  if (!existsSync(voice)) throw new Error("no video/.out/polly-gohar.mp3: run node video/live.mjs first");
  const voiceDur = Number(
    execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", voice], { encoding: "utf8" }),
  );
  return { voice, voiceDur };
}

export const timing = { lead: 0.2, gap: 0.14, tail: 0.3, gapAfter: { ".": 0.55, "?": 0.7, ":": 0.42, ";": 0.4, ",": 0.32 } };
export const tts = { speed: 1.04, speed_max_cps: 20.5, max_cps: 21.5 };
export { compose } from "./lib/compose.mjs";
