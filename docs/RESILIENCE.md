# Resilience

What happens when each part fails, and what Pukaar deliberately does not
handle. Each line names the code or test that shows it.

## Failure layers

| Fails | What happens | Where |
|---|---|---|
| Bedrock (timeout, throttling, 5xx) | The whole call is retried once in `us-west-2`; if that fails too the method returns `None` | `llm/bedrock.py`, `tests/test_llm_and_drafting.py` |
| Bedrock (access denied, bad output) | No failover (it would fail the same way); `None`, then the rule fallback | same |
| Model down while drafting | The fixed Hindi template from `templates/hi.py` goes out; the alert records `reasoning_model = "rule-fallback"` and the console shows it | `services/drafting.py`, `test_model_outage_still_alerts` |
| Model draft invents a number, place or tone | The draft checker rejects it and the fixed template is used; the reason is stored on the alert | `check_draft`, `test_checker_rejects_invented_numbers_places_and_tone` |
| Model down for reports | The keyword parser's result stands (`parser_source = "rules"`) | `services/report_structuring.py` |
| Model down for Ask Pukaar | A keyword router calls the same read-only tools and says no model was used | `services/analyst.py` |
| Transcribe fails | The audio stays in S3, the report keeps its keyword reading and the flag `transcription_unavailable`; it is never dropped | `services/reports.py`, `test_report_without_text_keeps_audio_and_waits_for_transcript` |
| Polly fails | Generative engine, then neural; if both fail the alert goes out as text | `voice/polly.py` |
| Telegram fails for one person | That delivery is `failed` with the error; others still go; the recall step retries once | `delivery/dispatch.py` |
| Telegram says 429 (too many requests) | The worker pauses for `retry_after` and tries again; a send that does not fit in the step is put back unsent (`deferred`, "queued, not sent"), never marked sent, and the next pass sends it after the wait | `delivery/telegram.py`, `test_429_past_the_time_budget_is_queued_unsent_then_sent_next_pass` |
| A delivery batch runs twice, or a worker dies mid-batch | Each send is claimed by a conditional write first (once per round), so nobody gets two; a dead batch is reported unfinished and run again by the next pass; it never fails the run | `Repo.claim_delivery`, `test_a_retried_or_doubled_batch_never_sends_twice`, `tests/test_asl.py` |
| One village's sweep throws while the others run at once | Its result is an error and its level is held; the other villages, evaluated concurrently, are not touched | `sweep_all`, `test_one_village_error_stays_its_own_and_never_a_false_normal` |
| The duty officer sleeps through Web Push and Telegram | The nudge phones an officer who has not opened the link (voice on, number set); "1" sends the link again, nothing approves; with voice off the record says the call was not possible | `delivery/officer_call.py`, `tests/test_officer_wake.py` |
| Telegram token cannot be read (SSM throttled or down) | Every real recipient's delivery is `failed` with the reason, counted in `DeliveryFailed` (alarmed); it is never sent to the stub channel and counted as sent. The stub channel is only for replays and demo recipients marked `stub` | `delivery/dispatch.py`, `test_unreadable_token_is_a_failed_delivery_not_a_stub` |
| Open-Meteo fails for one village | That village's level is held (never lowered), it is marked `stale` and then `data unavailable`, and the others continue. No complete forecast for 45 minutes emits `VillageDataStale` for that village (alarmed) | `sweep_all`, `test_fetch_failure_marks_the_village_and_holds_the_level` |
| Open-Meteo leaves rain or discharge out | Unknown, never 0 mm: the last complete values are carried forward for 4 sweeps (`stale`), then the village is `data unavailable`. Neither counts as a calm sweep, so missing data never walks a level down | `decision_engine._data_quality`, `test_missing_rain_is_carried_forward_then_unavailable_and_never_walks_the_level_down` |
| A Warning is declined or expires while the level holds | After a 30-minute cooldown (`PUKAAR_REASK_COOLDOWN_MINUTES`) the sweep starts a new approval; its trace names the earlier alert and its outcome | `decision_engine.reask_due`, `test_expired_warning_is_asked_again_after_the_cooldown_while_the_level_holds` |
| A replay runs during a real event | It works on its own copies of the villages: live levels, live alerts and the live sweep carry on, and reset removes replay items only | `services/replay.py`, `test_live_alert_and_level_survive_replay_start_run_and_reset` |
| A gauge simulator sends readings | Stored and shown, labelled simulated; never sets a live level or starts an alert | `risk_rules.assess`, `test_simulated_gauge_never_raises_a_live_village` |
| A sweep runs twice for the same 15 minutes | The second claim of the window fails its conditional put and does nothing | `claim_sweep`, `test_sweep_window_is_deduplicated` |
| Sweep Lambda crashes | No retry (a retry could double-alert); the event goes to the DLQ; the heartbeat alarm fires when no sweep completes for 30 minutes | `infra/template.yaml` |
| No officer answers | The next officer is asked; when the list runs out, a critical alert is sent with the fixed template and flagged `auto_sent_unapproved` only if `CriticalAutoSend=true` (off unless set; it needs DDMA sign-off; a Cedar policy allows only this); otherwise it expires and the sweep asks again, and anything lower expires | `infra/approval.asl.json`, `test_critical_auto_send_is_flagged_unapproved`, `test_warning_cannot_auto_send` |
| Approval arrives late or twice | Conditional update on `token_version`: HTTP 409 with a Hindi and English page; nothing changes | `decide`, `test_late_or_repeated_approval_is_rejected` |
| Any workflow task throws | `Catch States.ALL` -> Failsafe: the fixed template goes to every recipient, status `failsafe` | `step_failsafe`, `tests/test_asl.py` |
| Failsafe or Close itself fails | Both swallow errors and return, so an execution always ends | `test_failsafe_and_close_survive_an_unknown_alert` |
| Audit table write fails | The decision becomes a deny: nothing happens without an audit row | `authorize`, `test_no_audit_means_no_permission` |
| Village keeps rising during approval | The pending alert is escalated in place, not duplicated | `test_rise_while_pending_escalates_the_same_alert` |
| Phone offline when reporting | The report waits in IndexedDB and is sent when the connection returns | `frontend/src/lib/idb.ts` |
| A script floods the report page | Every report is kept; over 5 from one source or 30 from one village in 10 minutes they are held for an officer, never auto-verified or sent to a model, and `ReportSurge` is alarmed | `services/report_guard.py`, `tests/test_report_abuse.py` |
| Two forged reports from one phone or network | They never verify each other; each says why ("same network"), and an officer decides | `report_guard.not_independent`, `test_forged_pair_from_one_ip_does_not_verify_or_raise_the_level` |
| The report salt cannot be read | Sources are left unknown and no report auto-verifies (fail closed); `ReportSaltMissing` is counted | `report_guard.make_source`, `test_missing_salt_fails_closed` |

## Deliberately not handled

- **No SMS or voice-call channel.** Telegram is the only live channel. A
  villager without Telegram depends on the pradhan passing the alert on.
- **No multi-region deployment.** Only the model call fails over between
  regions; the table, workflow and API live in `us-east-1`.
- **Coordinates are unverified.** Village points come from GeoNames and are
  marked `coords_verified: false`. River cells were chosen against
  OpenStreetMap and the model's own routing (`data/river_cells.json`): the
  Beas cells for Pandoh and Sujanpur are checked; for Thunag, Janjehli and
  Gohar GloFAS has no channel larger than one cell on their khads, so their
  river signal stays weak (`cell_verified: false`).
- **Global models miss cloudbursts.** In the Mandi 30 June 2025 replay the
  archived forecasts and river discharge never crossed for four of five
  villages. Pukaar does not claim to predict such events; verified villager
  reports are the path that raises a level then.
- **Report spam beyond the app's limits.** Each source (a salted IP hash) and
  each village has its own report limit, the excess is held for an officer, and
  two reports verify each other only from different phones on different
  networks with plausible GPS (docs/SECURITY.md). The shared API Gateway
  throttle on `POST /reports` can still be filled by a large botnet; per-client
  limits at the edge need AWS WAF in front of the API.
- **Officer impersonation through a forwarded link.** A one-tap link works
  for whoever holds it for 30 minutes, once. The console path needs a Cognito
  sign-in.
