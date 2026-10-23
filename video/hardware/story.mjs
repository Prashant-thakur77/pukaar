// The hardware explainer's script: what is said, in which scene, and which frames become stills.
//
// Every fact here comes from the repository: devices, parts and prices from docs/hardware/ALARM.md and
// docs/hardware/README.md; the loop from README.md and docs/RESILIENCE.md; Pandoh July 2023 from docs/SCORING.md
// (the replay's alert 19 h ahead, the get-ready outlook at least 48 h ahead). The hardware is designed and
// simulated, never tested on a board or in the field, so the film says "how it will work".
//
// A line: `text` is the caption ("|" marks where the caption changes), `say` (optional) is what Polly reads when it
// must differ (Devanagari inside an English sentence, rupee amounts), `lang` "hi" for a Hindi line.
// A scene: `chapter` (the top-left title, when a new chapter starts), `minDur`, `lead`, `tail`, `gap`.

export const VOICE = { id: "Kajal", engine: "neural", enRate: "96%", hiRate: "90%" };

const L = (text, opts = {}) => ({ text, ...opts });

export const SCENES = [
  {
    id: "valley",
    chapter: "Pandoh, Mandi",
    n: 1,
    lead: 1.6,
    minDur: 14.8,
    lines: [
      L("This is Pandoh, in Mandi district, Himachal Pradesh. | The Beas river runs past its market, below the Pandoh dam."),
      L("In July 2023, | the Beas rose into this market."),
    ],
  },
  {
    id: "problem",
    chapter: "The problem",
    n: 2,
    minDur: 12.5,
    lines: [
      L("When we replayed that week through Pukaar, | the first alert came nineteen hours before the flood."),
      L("But a warning only helps | if it reaches every home, | and people act on it."),
    ],
  },
  {
    id: "dev-intro",
    chapter: "Meet the devices",
    n: 3,
    minDur: 5,
    lines: [L("Here is the hardware we have designed for a village like Pandoh. | Each piece is simple.")],
  },
  {
    id: "dev-gauge",
    lines: [
      L("On the bridge, a river gauge. | A radar looks down at the water | and measures its level from above, like a bat."),
      L("A solar panel and a battery | keep it running for about a week without sun."),
    ],
  },
  {
    id: "dev-rain",
    lines: [
      L("On the hillside above the village, a rain gauge. | Inside, a tiny seesaw tips with every bit of rain."),
      L("It counts rain where it falls, | which is how cloudbursts are caught."),
    ],
  },
  {
    id: "dev-siren",
    lines: [
      L("In the village, a siren pole. | It plays a siren, then a spoken Hindi message."),
      L("And it listens to itself, | to prove it actually sounded."),
    ],
  },
  {
    id: "dev-box",
    lines: [
      L("In the pradhan's house, an alarm box. | Turn the key, and hold the big button for three seconds."),
      L("The siren sounds, | and the district officer is told at once."),
    ],
  },
  {
    id: "dev-radio",
    lines: [L("The devices also talk by radio, called LoRa: | a walkie-talkie for machines | that works when mobile networks fail.")],
  },
  {
    id: "dev-cloud",
    lines: [
      L("Normally, readings travel through the mobile tower | to Pukaar's brain, in the cloud."),
      L("It checks rain, river and reports | every fifteen minutes."),
    ],
  },
  {
    id: "dev-cost",
    lines: [
      L("For one village, all of this costs about 1.6 lakh rupees to set up, | and about ₹30,000 a year to run.", {
        say: "For one village, all of this costs about one point six lakh rupees to set up, | and about thirty thousand rupees a year to run.",
      }),
    ],
    tail: 0.8,
  },
  {
    id: "rain",
    chapter: "The rain begins",
    n: 4,
    minDur: 14.5,
    lines: [
      L("Now, the rain begins. | The seesaw in the rain gauge tips faster and faster."),
      L("Every fifteen minutes, Pukaar reads the forecast, | the rain gauge and the river gauge."),
    ],
  },
  {
    id: "rise",
    chapter: "The river rises",
    n: 5,
    minDur: 17.5,
    lines: [
      L("The river starts to rise. | The gauge measures it again and again."),
      L("A level counts only when two of the last three readings agree, | so one bad reading cannot cause a false alarm."),
      L("The readings go up through the tower, | and Pukaar raises Pandoh to Critical."),
    ],
  },
  {
    id: "approve",
    chapter: "The officer decides",
    n: 6,
    minDur: 15,
    lines: [
      L("Pukaar drafts a Hindi alert, | and shows the district officer the evidence: | the rain, the river and the gauge."),
      L("The officer holds a button to approve. | A person, not a machine, decides."),
    ],
  },
  {
    id: "hear",
    chapter: "Everyone hears it",
    n: 7,
    minDur: 29,
    lines: [
      L("Then every enrolled phone in Pandoh | gets the alert, spoken in Hindi."),
      L("ख़तरा! पंडोह में बाढ़ आ रही है। | अभी ऊँची जगह जाएँ।", { lang: "hi", pre: 0.3 }),
      L("People press “मिल गया”, which means “got it”. | On a keypad phone, they press 1.", {
        say: "People press, mil gaya, which means, got it. | On a keypad phone, they press one.",
        pre: 0.3,
      }),
      L("Anyone who has not confirmed | gets the alert again."),
      L("The siren sounds, then speaks. | It hears its own sound, and reports: verified."),
    ],
  },
  {
    id: "outage",
    chapter: "When the network fails",
    n: 8,
    minDur: 21.5,
    lines: [
      L("Now imagine the storm knocks out the mobile tower."),
      L("The river gauge does not need it. | It radios the siren directly."),
      L("If the cloud has been silent for ten minutes, | and two of three readings are critical, | the siren sounds on its own."),
      L("The river talks to the village.", { pre: 0.4 }),
    ],
    tail: 1.0,
  },
  {
    id: "move",
    chapter: "Moving to safe ground",
    n: 9,
    minDur: 12.5,
    lines: [
      L("Families walk up to the safe place on higher ground, | taking children, the elderly and the sick with them."),
      L("A neighbour is asked to check | on anyone who needs help."),
    ],
  },
  {
    id: "flow",
    chapter: "The whole flow",
    n: 10,
    minDur: 13,
    lines: [
      L("The whole flow, in one picture: | rain and river, Pukaar checks, | an officer approves, | phones and sirens warn, | people confirm, | and help reaches anyone who did not."),
    ],
    tail: 1.6,
  },
  {
    id: "real",
    chapter: "Real today, and next",
    n: 11,
    minDur: 12,
    lines: [
      L("What is real today: | the software loop is live on AWS. | The hardware is designed and simulated, | and ready for a bench test."),
    ],
    tail: 3.2,
  },
];

// Stills for the slide deck: [file name, scene id, where (seconds into the scene, or "L<i>+dt" from line i), description]
export const STILLS = [
  ["01-valley-wide", "valley", "L0+3", "The full schematic valley at night: the Beas, Pandoh dam upstream, the market, houses, bridge, tower and safe ground"],
  ["02-valley-july-2023", "valley", "L1+1.5", "Title caption: Pandoh, Mandi. July 2023, the Beas rose into the market"],
  ["03-problem-reach", "problem", "L1+2.5", "The problem: a warning existed (19 h ahead in the replay), but did it reach every home?"],
  ["04-devices-overview", "dev-intro", "L0+2.5", "All five device types placed in the valley, labelled"],
  ["05-river-gauge", "dev-gauge", "L0+5.5", "Close-up: the river gauge on the bridge, its radar looking down at the water"],
  ["06-river-gauge-parts", "dev-gauge", "L1+1.5", "River gauge parts: radar sensor, solar panel, battery, small computer with mobile modem, cost"],
  ["07-rain-gauge", "dev-rain", "L0+4", "Close-up: the rain gauge on the hillside, with the tipping seesaw inside"],
  ["08-rain-gauge-parts", "dev-rain", "L1+1.5", "Rain gauge: counts rain where it falls; parts and cost"],
  ["09-siren-pole", "dev-siren", "L0+3", "Close-up: the siren and loudspeaker pole with horns, solar panel, battery box and radio antenna"],
  ["10-siren-verified", "dev-siren", "L1+1.5", "The siren listens to itself to prove it sounded; parts and cost"],
  ["11-pradhan-box", "dev-box", "L0+4", "Close-up: the pradhan's alarm box, key and big button"],
  ["12-pradhan-box-hold", "dev-box", "L1+0.8", "Holding the button for 3 seconds; the officer is told at once"],
  ["13-lora-radio", "dev-radio", "L0+3.5", "LoRa radio links between devices, drawn as dotted lines"],
  ["14-tower-cloud", "dev-cloud", "L1+1", "The mobile tower and Pukaar's brain in the cloud, checking every 15 minutes"],
  ["15-cost", "dev-cost", "L0+3", "Cost for one village: about ₹1.6 lakh to set up and about ₹30,000 a year"],
  ["16-rain-begins", "rain", "L0+3", "The rain begins; the rain gauge's seesaw tips faster"],
  ["17-every-15-min", "rain", "L1+2", "Every 15 minutes the cloud reads the forecast, the rain gauge and the river gauge"],
  ["18-river-rises", "rise", "L1+2", "The river rises; the gauge counts a level only when 2 of the last 3 readings agree"],
  ["19-critical", "rise", "L2+4.2", "Readings go up through the tower; Pukaar raises Pandoh to Critical"],
  ["20-officer-evidence", "approve", "L0+4", "The district officer's phone: the evidence and the Hindi draft"],
  ["21-officer-approve", "approve", "L1+1.4", "Hold to approve: a person, not a machine, decides"],
  ["22-phones-hindi", "hear", "L1+1", "Villagers' phones: the spoken Hindi alert, मिल गया on a smartphone, press 1 on a keypad phone"],
  ["23-confirmations", "hear", "L3+1", "Phones light up across the houses; confirmations rise; those who did not confirm get it again"],
  ["24-siren-verified", "hear", "L4+2.6", "The siren sounds with sound rings and reports: verified"],
  ["25-network-down", "outage", "L1+1.5", "The tower goes dark; the river gauge radios the siren directly over LoRa"],
  ["26-edge-autonomy", "outage", "L2+3.5", "The siren sounds on its own when the cloud is silent and 2 of 3 readings are critical"],
  ["27-safe-ground", "move", "L1+2", "People walk uphill to the safe place on higher ground"],
  ["28-flow-diagram", "flow", "end-1.2", "The whole flow in one picture"],
  ["29-real-today", "real", "end-1.5", "What is real today and what is next"],
];
