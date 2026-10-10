# Demo video script (2:41)

The narration of [docs/media/pukaar-demo.mp4](../media/pukaar-demo.mp4) (161.2 s, 1920×1080), rendered by `node video/record.mjs demo` from [video/demo.mjs](../../video/demo.mjs); this file is written by the same run, so the times and words below are the video's own. Timed captions: [pukaar-demo.srt](../media/pukaar-demo.srt).

Every number is read at render time: the Mandi 2025 figures and the 3G load time from README.md, the Gohar story from frontend/src/data/story-gohar-2023.json (built by the real rules), the alarm and execution counts from the AWS account, and the proof scene's output straight from the AWS CLI. The live scenes are the deployed site during a labelled replay on AWS; replay alerts go to test phones only. The voice is Chatterbox TTS (open source) with its own built-in synthetic voice; the Hindi alert is the real Amazon Polly (Kajal, hi-IN) MP3. 439 words in 161 s (163 words a minute).

## Chapters

```
0:00 The problem
0:18 What Pukaar does
0:27 The night the river rose
0:45 Live on AWS
0:52 The officer approves
1:10 The village hears
1:47 Architecture
2:26 Limits and close
```

## Video description

```
Pukaar (पुकार): a flood-warning loop for Himalayan villages, built on AWS. A forecast becomes a spoken Hindi alert on every phone in the village, approved by a district officer in one tap.

Live: https://main.d15r7ktz99l46x.amplifyapp.com
Code: https://github.com/Prashant-thakur77/pukaar

0:00 The problem
0:18 What Pukaar does
0:27 The night the river rose
0:45 Live on AWS
0:52 The officer approves
1:10 The village hears
1:47 Architecture
2:26 Limits and close

Voice: Chatterbox TTS (open source) with its built-in synthetic voice. Hindi alert: Amazon Polly (Kajal).
Music: synthesised for this video by video/narration/music.py (CC0). Stock footage: Pexels (Pexels License), credits in docs/media/CREDITS.md.
```

## 0:00 to 0:07 · Pukaar

Screen: Kinetic type on the app's night blue; each phrase lands as it is said, key words marked in marigold, then the wordmark.

> A mountain stream can flood a village in hours, often at night.
>
> The forecast sees it coming. The village never hears it.
>
> That's Pukaar.

## 0:07 to 0:18 · The problem

Screen: Stock footage (Pexels License; credits in docs/media/CREDITS.md): storm clouds over Himalayan ridges, a river in flood, a landslide scar, storms from orbit, a hill village.

> On the night of 30 June 2025, cloudbursts hit Mandi district: at least 10 dead, 34 missing.
>
> Forecasts exist, but they are numbers on a website, not a warning anyone hears.

## 0:18 to 0:27 · Pukaar

Screen: The wordmark, the one-liner, and who it is for, appearing as they are said.

> Pukaar turns a forecast into a spoken Hindi alert on every phone in the village.
>
> A district officer approves it in one tap, and villagers confirm they heard it.

## 0:27 to 0:45 · Back-test

Screen: The live landing page: the 3D Beas valley (heightmap from AWS Open Data Terrain Tiles) with the water rising as the page scrolls, then 'the night the river rose': Gohar, July 2023, replayed through the real rules, the chart drawing itself step by step.

> Here's Gohar, in Mandi, July 2023, replayed through Pukaar's real rules.
>
> The river forecast passes its own 90th percentile: Watch.
>
> Rain passes 64.5 millimetres with the river high: Warning.
>
> Then 115.6: Critical.
>
> 72 hours before the river's peak day.

## 0:45 to 0:53 · Live on AWS

Screen: /live on the deployed site during a labelled replay on AWS: the 3D terrain map of the five villages turning to their levels, the counters and the acknowledgement funnel.

> Now the same night, running live on AWS.
>
> Every 15 minutes, EventBridge wakes a Lambda that sets each village's level by rule, never by a model.

## 0:53 to 1:11 · Officer console

Screen: The officer console signed in as a demo officer (Cognito): the pending Gohar critical alert with its Hindi draft, the rule-fallback label, then Approve and the confirmation.

> The officer on duty sees the Hindi draft. Step Functions has paused, waiting for one tap.
>
> The model only fills a fixed template, and a checker rejects any number not in the decision trace.
>
> Bedrock access is still pending on this account, so it says rule-fallback, and the alert still goes out.
>
> Approve.

## 1:11 to 1:29 · The village hears

Screen: The Gohar village page after approval: the alert delivered, the Listen button playing the real Polly (Kajal, hi-IN) MP3, the time-to-ear stopwatch and the deliveries.

> Amazon Polly speaks it in Hindi:
>
> Every phone gets the voice and one button: मिल गया, got it.
>
> Pukaar times each alert, from the river rising to the first person who heard it.
>
> In a replay, it goes to test phones only.

## 1:29 to 1:38 · Audit log

Screen: The audit page (officer view): the officer's approval allowed by a Cedar policy, and a village pradhan's attempt to approve refused, each with the policy and reason; recorded from the live stack.

> Every decision lands in an audit log: Cedar allowed the officer's approval,
>
> and refused a village pradhan who tried, with the policy and the reason.

## 1:38 to 1:47 · Villager report

Screen: The live villager report page in a phone frame (390 px): Hindi first, one big record button, works offline.

> Villagers report back by voice, photo or text, from any phone, even offline.
>
> On slow 3G, the page is ready in 4.6 seconds.

## 1:47 to 2:14 · Architecture

Screen: A three.js model of the stack: each AWS service lifts and glows as it is named, pulses running along the real request path, everything else dimmed.

> The whole loop is serverless on AWS.
>
> EventBridge Scheduler runs the sweep Lambda, with no retries and a dead-letter queue.
>
> One DynamoDB table, with conditional writes, so an alert is never sent twice.
>
> Step Functions waits for the officer; no answer moves to the next one.
>
> Bedrock drafts through Strands, Polly speaks, and the audio lands in S3.
>
> Telegram delivers it, and the tap comes back through API Gateway.
>
> Cognito signs officers in, Cedar checks every action, and 9 CloudWatch alarms watch it all.

## 2:14 to 2:26 · Live proof

Screen: Real output captured from the AWS account at render time: the approval state machine's latest executions, the Polly MP3s in S3, and the live /health check.

> This is live: 40 approval workflows so far, 36 succeeded.
>
> Polly's Hindi audio in S3, and the health check, right now.
>
> Nothing runs between requests: no servers, no database instance.

## 2:26 to 2:34 · Not done yet

Screen: Two honest limits, each with what Pukaar does about it.

> In our 2025 back-test, the global forecasts missed the Mandi cloudburst.
>
> So a verified villager report can raise a level on its own.

## 2:34 to 2:41 · Pukaar

Screen: End card: the callback line, the wordmark, the live URL, the repository and what it runs on.

> The river will still rise. Now the village hears first.
