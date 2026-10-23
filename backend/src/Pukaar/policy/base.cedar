// Pukaar role policies. Default is deny; forbid overrides permit.
// Principals: Pukaar::Officer, Pukaar::Pradhan, Pukaar::System, Pukaar::Agent,
//             Pukaar::StateOperator (SDMA: reads every district; acts only where assigned or rostered),
//             Pukaar::DDMAHead (their districts: reads reports and metrics, changes district settings).
// Resources:  Pukaar::Village, Pukaar::Alert, Pukaar::Report, Pukaar::RollCall, Pukaar::Tool, Pukaar::App,
//             Pukaar::Device (a siren, pradhan box, relay, rain node or gauge).
// Context:    level, approved, all_officers_timed_out, replay, channel, village_id,
//             district / scoped / in_scope (services/scope.py: from the records, never from the request).

@id("officer-operate")
@desc("Officers run the console: approve, decline, edit or snooze pending alerts, triage reports, see who an alert reached, issue directives, update the shelter ledger, run replays, read the audit trail, ask the analyst and tick any village's early-action checklist.")
permit (
  principal is Pukaar::Officer,
  action in [
    Pukaar::Action::"view_console", Pukaar::Action::"approve", Pukaar::Action::"decline",
    Pukaar::Action::"edit_alert", Pukaar::Action::"snooze_alert",
    Pukaar::Action::"view_reports", Pukaar::Action::"view_recipients", Pukaar::Action::"set_report_state",
    Pukaar::Action::"issue_directive",
    Pukaar::Action::"start_replay", Pukaar::Action::"read_audit", Pukaar::Action::"ask_analyst",
    Pukaar::Action::"health_deep", Pukaar::Action::"dev_link", Pukaar::Action::"tick_checklist", Pukaar::Action::"set_shelter_status"
  ],
  resource
);

// A request that names no village never matches: a list route asks once for each of the pradhan's own
// villages (api/auth.py Allowed), and an alert or report is checked against the village on its record.
@id("pradhan-own-village")
@desc("A pradhan sees the console, the reports and who an alert reached for their own villages only.")
permit (
  principal is Pukaar::Pradhan,
  action in [Pukaar::Action::"view_console", Pukaar::Action::"view_reports", Pukaar::Action::"view_recipients"],
  resource
)
when { context.village_id != "" && principal.village_ids.contains(context.village_id) };

@id("pradhan-own-checklist")
@desc("A pradhan ticks the early-action checklist of their own village only.")
permit (
  principal is Pukaar::Pradhan,
  action == Pukaar::Action::"tick_checklist",
  resource is Pukaar::Village
)
when { context.village_id != "" && principal.village_ids.contains(context.village_id) };

@id("pradhan-own-shelters")
@desc("A pradhan updates the shelter ledger (open, standby, full, closed) for their own villages only.")
permit (
  principal is Pukaar::Pradhan,
  action == Pukaar::Action::"set_shelter_status",
  resource is Pukaar::Village
)
when { context.village_id != "" && principal.village_ids.contains(context.village_id) };

@id("officer-roadblocks")
@desc("Officers mark a road or bridge on any village's evacuation routes blocked, renew the block or clear it.")
permit (
  principal is Pukaar::Officer,
  action == Pukaar::Action::"block_road",
  resource is Pukaar::Village
);

@id("pradhan-own-roadblocks")
@desc("A pradhan marks roads on their own village's evacuation routes blocked, renews or clears them; never another village's.")
permit (
  principal is Pukaar::Pradhan,
  action == Pukaar::Action::"block_road",
  resource is Pukaar::Village
)
when { context.village_id != "" && principal.village_ids.contains(context.village_id) };

@id("officer-recipient-role")
@desc("Officers make a registered person of any village a relay (pradhan, gauge reader, task force) or a villager again; audited.")
permit (
  principal is Pukaar::Officer,
  action == Pukaar::Action::"set_recipient_role",
  resource is Pukaar::Village
);

@id("pradhan-own-recipient-role")
@desc("A pradhan names the relays (pradhan, gauge reader, task force) among their own village's registered people only.")
permit (
  principal is Pukaar::Pradhan,
  action == Pukaar::Action::"set_recipient_role",
  resource is Pukaar::Village
)
when { context.village_id != "" && principal.village_ids.contains(context.village_id) };

@id("system-deliver-approved")
@desc("The system delivers an alert only after an officer approved it.")
permit (
  principal is Pukaar::System,
  action == Pukaar::Action::"deliver",
  resource is Pukaar::Alert
)
when { context.approved == true };

@id("system-critical-auto-send")
@desc("The system may send without approval only a critical alert after every officer timed out; it is flagged as unapproved. Configurable (PUKAAR_CRITICAL_AUTO_SEND), and keeping it on needs DDMA sign-off.")
permit (
  principal is Pukaar::System,
  action in [Pukaar::Action::"auto_send", Pukaar::Action::"deliver"],
  resource is Pukaar::Alert
)
when { context.level == "critical" && context.all_officers_timed_out == true };

@id("system-failsafe")
@desc("When the workflow fails on a critical or already-approved alert, the system sends the fixed safety template so a broken pipeline never means silence.")
permit (
  principal is Pukaar::System,
  action == Pukaar::Action::"failsafe",
  resource is Pukaar::Alert
)
when { context.level == "critical" || context.approved == true };

@id("agent-read-only-tools")
@desc("Model agents may call only read-only tools from the allowlist.")
permit (
  principal is Pukaar::Agent,
  action == Pukaar::Action::"use_tool",
  resource in Pukaar::ToolGroup::"read_only"
);

@id("no-replay-to-phones")
@desc("Replay alerts never reach real phones, by Telegram or by voice call, and neither does their all-clear; they go to the stub channel only.")
forbid (
  principal,
  action in [Pukaar::Action::"deliver", Pukaar::Action::"auto_send", Pukaar::Action::"failsafe", Pukaar::Action::"all_clear"],
  resource
)
when { context.replay == true && context.channel != "stub" };

@id("agents-never-send")
@desc("A model agent can never approve, edit or send an alert, change a level, change the shelter ledger, mark a road blocked, or sound, stop, test or change a siren.")
forbid (
  principal is Pukaar::Agent,
  action in [
    Pukaar::Action::"approve", Pukaar::Action::"decline", Pukaar::Action::"edit_alert", Pukaar::Action::"deliver",
    Pukaar::Action::"auto_send", Pukaar::Action::"failsafe", Pukaar::Action::"issue_directive",
    Pukaar::Action::"open_rollcall", Pukaar::Action::"remind_rollcall", Pukaar::Action::"set_shelter_status",
    Pukaar::Action::"block_road", Pukaar::Action::"sound_siren", Pukaar::Action::"stop_siren",
    Pukaar::Action::"test_siren", Pukaar::Action::"manage_device", Pukaar::Action::"pour_test"
  ],
  resource
);

@id("officer-rollcall")
@desc("Officers open a safety roll-call for any village, read its board and remind the people who have not answered.")
permit (
  principal is Pukaar::Officer,
  action in [Pukaar::Action::"open_rollcall", Pukaar::Action::"view_rollcall", Pukaar::Action::"remind_rollcall"],
  resource
);

@id("pradhan-rollcall-own-village")
@desc("A pradhan opens, reads and sends reminders for the safety roll-call of their own villages only.")
permit (
  principal is Pukaar::Pradhan,
  action in [Pukaar::Action::"open_rollcall", Pukaar::Action::"view_rollcall", Pukaar::Action::"remind_rollcall"],
  resource
)
when { context.village_id != "" && principal.village_ids.contains(context.village_id) };

@id("system-rollcall-after-alert")
@desc("The system opens a safety roll-call after a warning or critical alert reached the village.")
permit (
  principal is Pukaar::System,
  action == Pukaar::Action::"open_rollcall",
  resource
)
when { context.level == "warning" || context.level == "critical" };

@id("officer-gauge-thresholds")
@desc("Only a district officer accepts new river-gauge stage thresholds (a proposal learned from the gauge's own record, or values set by hand), and confirms or adjusts a villager's staff gauge reading.")
permit (
  principal is Pukaar::Officer,
  action in [
    Pukaar::Action::"view_gauge_proposal", Pukaar::Action::"set_gauge_thresholds",
    Pukaar::Action::"manage_staff_gauge", Pukaar::Action::"confirm_staff_reading"
  ],
  resource
);

@id("pradhan-own-gauges")
@desc("A pradhan reads the threshold proposal of their own village's gauge and sets up its staff gauge reference points; they cannot accept thresholds or confirm readings.")
permit (
  principal is Pukaar::Pradhan,
  action in [Pukaar::Action::"view_gauge_proposal", Pukaar::Action::"manage_staff_gauge"],
  resource is Pukaar::Village
)
when { context.village_id != "" && principal.village_ids.contains(context.village_id) };

@id("agents-never-set-thresholds")
@desc("A model agent can never change a gauge threshold, a staff gauge or a reading's confirmation.")
forbid (
  principal is Pukaar::Agent,
  action in [
    Pukaar::Action::"set_gauge_thresholds", Pukaar::Action::"manage_staff_gauge",
    Pukaar::Action::"confirm_staff_reading"
  ],
  resource
);

@id("no-replay-rollcall")
@desc("A replay never opens a roll-call or asks a real phone whether they are safe.")
forbid (
  principal,
  action in [Pukaar::Action::"open_rollcall", Pukaar::Action::"remind_rollcall"],
  resource
)
when { context.replay == true };

@id("officer-after-action")
@desc("Officers read the after-action report of any alert.")
permit (
  principal is Pukaar::Officer,
  action == Pukaar::Action::"view_after_action",
  resource is Pukaar::Alert
);

@id("officer-alert-outcome")
@desc("After a live alert closes, an officer records whether it was real (real flood, no flood, unknown); it feeds the false-alarm rate per rule. A pradhan or an agent cannot.")
permit (
  principal is Pukaar::Officer,
  action == Pukaar::Action::"set_alert_outcome",
  resource is Pukaar::Alert
);

@id("staff-own-push")
@desc("Officers and pradhans turn on Web Push approval alerts for their own account, remove their own phones and send themselves a test notification.")
permit (
  principal,
  action == Pukaar::Action::"subscribe_push",
  resource is Pukaar::App
)
when { principal is Pukaar::Officer || principal is Pukaar::Pradhan };

@id("pradhan-after-action-own-village")
@desc("A pradhan reads the after-action report only for alerts in their own villages.")
permit (
  principal is Pukaar::Pradhan,
  action == Pukaar::Action::"view_after_action",
  resource is Pukaar::Alert
)
when { context.village_id != "" && principal.village_ids.contains(context.village_id) };

// The judge accounts' password is published in the README so anyone can try the console. Whatever
// group they are in, they may act on replay alerts only: nothing they do can reach a real phone,
// change what a real alert says, or change a live village's shelters, roads or checklist, or the
// live duty roster (there is no replay roster, so the roster is never theirs to edit).
// Nor may they read villagers' data that is not a replay's: the report feed (exact GPS, words,
// transcripts, photo and voice links, names), who an alert reached (names, chat ids, call ids), the
// roll-call board (names) and the after-action report (first names). Their report feed is served
// with replay reports only (api/auth.py Allowed with replay_reads).
// context.replay comes from the record itself (api/auth.py resource_facts), never from the request.
@id("public-demo-accounts-replay-only")
@desc("Public demo account (judge, judge_pradhan; its password is published): it may act on replay alerts only, never on a live alert or a live village, and may read villagers' data from replays only.")
forbid (
  principal,
  action in [
    Pukaar::Action::"approve", Pukaar::Action::"decline", Pukaar::Action::"edit_alert", Pukaar::Action::"snooze_alert",
    Pukaar::Action::"issue_directive", Pukaar::Action::"send_drill", Pukaar::Action::"set_shelter_status", Pukaar::Action::"block_road",
    Pukaar::Action::"open_rollcall", Pukaar::Action::"remind_rollcall", Pukaar::Action::"tick_checklist",
    Pukaar::Action::"set_report_state", Pukaar::Action::"set_gauge_thresholds",
    Pukaar::Action::"manage_staff_gauge", Pukaar::Action::"confirm_staff_reading", Pukaar::Action::"dev_link",
    Pukaar::Action::"deliver", Pukaar::Action::"auto_send", Pukaar::Action::"failsafe",
    Pukaar::Action::"edit_roster", Pukaar::Action::"take_over_duty", Pukaar::Action::"set_alert_outcome",
    Pukaar::Action::"view_reports", Pukaar::Action::"view_recipients", Pukaar::Action::"view_rollcall",
    Pukaar::Action::"view_after_action", Pukaar::Action::"set_recipient_role"
  ],
  resource
)
when {
  [Pukaar::Officer::"judge", Pukaar::Pradhan::"judge",
   Pukaar::Officer::"judge_pradhan", Pukaar::Pradhan::"judge_pradhan"].contains(principal) &&
  context.replay != true
};

@id("officer-roster")
@desc("Officers read the district duty roster, edit the week and take over a shift; the handover is written to the audit trail. A pradhan cannot.")
permit (
  principal is Pukaar::Officer,
  action in [Pukaar::Action::"view_roster", Pukaar::Action::"edit_roster", Pukaar::Action::"take_over_duty"],
  resource is Pukaar::App
);

@id("system-all-clear")
@desc("When an alert is stood down (the village is back to normal, or an officer issued the all-clear), the system tells everyone it contacted for that alert, on the same channels.")
permit (
  principal is Pukaar::System,
  action == Pukaar::Action::"all_clear",
  resource is Pukaar::Alert
);

// -- district scope (services/scope.py) and the state and district roles ------------------------------
// After the public demo accounts' and the replay forbids, so a refusal names theirs first (guard.py sorts by file order).
@id("staff-own-district")
@desc("An officer or a state operator acts only on villages of the districts they are assigned to (their scope, the village's officer list, their sign-in's villages) or rostered on from yesterday to tomorrow; a replay is a rehearsal and is not held to a district.")
forbid (
  principal,
  action in [
    Pukaar::Action::"approve", Pukaar::Action::"decline", Pukaar::Action::"edit_alert", Pukaar::Action::"snooze_alert",
    Pukaar::Action::"set_report_state", Pukaar::Action::"issue_directive", Pukaar::Action::"tick_checklist",
    Pukaar::Action::"set_shelter_status", Pukaar::Action::"block_road", Pukaar::Action::"set_recipient_role",
    Pukaar::Action::"open_rollcall", Pukaar::Action::"remind_rollcall", Pukaar::Action::"set_gauge_thresholds",
    Pukaar::Action::"manage_staff_gauge", Pukaar::Action::"confirm_staff_reading", Pukaar::Action::"set_alert_outcome",
    Pukaar::Action::"edit_roster", Pukaar::Action::"take_over_duty", Pukaar::Action::"sound_siren",
    Pukaar::Action::"stop_siren", Pukaar::Action::"test_siren", Pukaar::Action::"manage_device", Pukaar::Action::"pour_test",
    Pukaar::Action::"send_drill", Pukaar::Action::"change_settings"
  ],
  resource
)
when {
  (principal is Pukaar::Officer || principal is Pukaar::StateOperator) &&
  context.scoped == true && context.in_scope != true && context.replay != true
};

@id("state-operator-read")
@desc("A state (SDMA) operator reads every district: the console, reports, who an alert reached, roll-calls, after-action reports, the audit trail, the roster and the devices.")
permit (
  principal is Pukaar::StateOperator,
  action in [
    Pukaar::Action::"view_console", Pukaar::Action::"view_reports", Pukaar::Action::"view_recipients",
    Pukaar::Action::"view_rollcall", Pukaar::Action::"view_after_action", Pukaar::Action::"read_audit",
    Pukaar::Action::"view_roster", Pukaar::Action::"view_devices", Pukaar::Action::"view_gauge_proposal",
    Pukaar::Action::"health_deep", Pukaar::Action::"ask_analyst"
  ],
  resource
);

@id("state-operator-act-where-assigned")
@desc("A state operator approves, declines or edits alerts, triages reports, issues directives and runs roll-calls only in a district they are assigned to or rostered on; never sirens or devices.")
permit (
  principal is Pukaar::StateOperator,
  action in [
    Pukaar::Action::"approve", Pukaar::Action::"decline", Pukaar::Action::"edit_alert", Pukaar::Action::"snooze_alert",
    Pukaar::Action::"set_report_state", Pukaar::Action::"issue_directive", Pukaar::Action::"open_rollcall",
    Pukaar::Action::"remind_rollcall", Pukaar::Action::"set_alert_outcome", Pukaar::Action::"block_road",
    Pukaar::Action::"set_shelter_status"
  ],
  resource
)
when { context.scoped == true && context.in_scope == true };

@id("ddma-head-own-district")
@desc("A DDMA head reads the console, reports, roll-calls, after-action reports, the roster and the devices of their own districts.")
permit (
  principal is Pukaar::DDMAHead,
  action in [
    Pukaar::Action::"view_console", Pukaar::Action::"view_reports", Pukaar::Action::"view_rollcall",
    Pukaar::Action::"view_after_action", Pukaar::Action::"view_roster", Pukaar::Action::"view_devices"
  ],
  resource
)
when { context.district != "" && principal.district_ids.contains(context.district) };

@id("ddma-head-district-settings")
@desc("A DDMA head changes their own district's settings (critical auto-send) and its duty roster; audited.")
permit (
  principal is Pukaar::DDMAHead,
  action in [Pukaar::Action::"change_settings", Pukaar::Action::"edit_roster"],
  resource
)
when { context.district != "" && principal.district_ids.contains(context.district) };

// -- the alarm layer: sirens, pradhan boxes, relays (services/sirens.py, api/routers/devices.py) ----------------
// policy/guard.py fills every context key these read, so a missing key never turns into an evaluation error:
// pattern (W1, C1, A1, T1, D1), src, drill, critical_auto_send, machine_evidence_critical,
// second_officer_distinct, device_simulated, device_village_id, kind (silent | audible), hour_ist (0-23),
// village_alert_open, started_by_self, change.
@id("system-sound-siren-approved")
@desc("Sirens sound for an officer-approved Warning or Critical, or the flagged critical auto-send. The Critical pattern (C1) needs machine evidence at Critical or a second officer; without either the alert sounds the Warning pattern (W1), never silence.")
permit (
  principal is Pukaar::System,
  action == Pukaar::Action::"sound_siren",
  resource is Pukaar::Alert
)
when {
  (context.level == "warning" || context.level == "critical") &&
  (context.approved == true ||
   (context.level == "critical" && context.all_officers_timed_out == true && context.critical_auto_send == true)) &&
  (context.pattern == "W1" ||
   (context.pattern == "C1" && context.level == "critical" &&
    (context.machine_evidence_critical == true || context.second_officer_distinct == true)))
};

@id("system-sound-siren-failsafe")
@desc("A broken workflow never means silence: the failsafe sounds the sirens for a critical or already-approved alert, under the same rule for the Critical pattern.")
permit (
  principal is Pukaar::System,
  action == Pukaar::Action::"sound_siren",
  resource is Pukaar::Alert
)
when {
  context.src == "failsafe" && (context.level == "critical" || context.approved == true) &&
  (context.pattern == "W1" ||
   (context.pattern == "C1" && context.level == "critical" &&
    (context.machine_evidence_critical == true || context.second_officer_distinct == true)))
};

@id("system-drill-pattern")
@desc("An officer-approved drill plays the drill pattern (D1) only, through test_siren, never sound_siren.")
permit (
  principal is Pukaar::System,
  action == Pukaar::Action::"test_siren",
  resource is Pukaar::Alert
)
when { context.drill == true && context.pattern == "D1" && context.approved == true };

@id("system-propagate-pradhan-siren")
@desc("A pradhan's local siren trigger (box key and hold) may be passed on to the other sirens of the same village only.")
permit (
  principal is Pukaar::System,
  action == Pukaar::Action::"sound_siren",
  resource is Pukaar::Village
)
when {
  context.src == "pradhan_box" && context.village_id != "" && context.device_village_id == context.village_id &&
  (context.pattern == "W1" || context.pattern == "C1")
};

@id("system-scheduled-test")
@desc("The weekly self-test is silent; an audible scheduled test runs only between 09:00 and 18:00 IST and never while the village has an open alert.")
permit (
  principal is Pukaar::System,
  action == Pukaar::Action::"test_siren",
  resource is Pukaar::Device
)
when {
  context.kind == "silent" ||
  (context.kind == "audible" && context.hour_ist >= 9 && context.hour_ist < 18 && context.village_alert_open == false)
};

@id("officer-manual-siren")
@desc("An officer sounds a village's sirens by hand (an evacuation): a Warning alone, a Critical only with a second, different officer (the two-person rule).")
permit (
  principal is Pukaar::Officer,
  action == Pukaar::Action::"sound_siren",
  resource is Pukaar::Village
)
when { context.level == "warning" || (context.level == "critical" && context.second_officer_distinct == true) };

@id("officer-stop-view-devices")
@desc("Officers stop a sounding siren and see every device and its health.")
permit (
  principal is Pukaar::Officer,
  action in [Pukaar::Action::"stop_siren", Pukaar::Action::"view_devices"],
  resource
);

@id("officer-test-siren")
@desc("Officers test a siren: a silent test at any time, an audible one only between 09:00 and 18:00 IST.")
permit (
  principal is Pukaar::Officer,
  action == Pukaar::Action::"test_siren",
  resource is Pukaar::Device
)
when { context.kind == "silent" || (context.kind == "audible" && context.hour_ist >= 9 && context.hour_ist < 18) };

@id("officer-manage-device")
@desc("Officers change a device's settings; turning on edge autonomy needs a second, different officer.")
permit (
  principal is Pukaar::Officer,
  action == Pukaar::Action::"manage_device",
  resource is Pukaar::Device
)
when { context.change != "autonomy_enable" || context.second_officer_distinct == true };

@id("pradhan-view-own-devices")
@desc("A pradhan sees the devices of their own villages only.")
permit (
  principal is Pukaar::Pradhan,
  action == Pukaar::Action::"view_devices",
  resource
)
when { context.village_id != "" && principal.village_ids.contains(context.village_id) };

@id("pradhan-siren-own-village")
@desc("A pradhan sounds the sirens of their own village only, at Warning or Critical (as with the box key and hold in the field).")
permit (
  principal is Pukaar::Pradhan,
  action == Pukaar::Action::"sound_siren",
  resource is Pukaar::Village
)
when {
  context.village_id != "" && principal.village_ids.contains(context.village_id) &&
  (context.level == "warning" || context.level == "critical")
};

@id("pradhan-stop-own-trigger")
@desc("A pradhan stops only a siren they started themselves, in their own village.")
permit (
  principal is Pukaar::Pradhan,
  action == Pukaar::Action::"stop_siren",
  resource is Pukaar::Village
)
when { context.village_id != "" && principal.village_ids.contains(context.village_id) && context.started_by_self == true };

@id("staff-pour-test")
@desc("An officer, or the pradhan of the village, opens a rain-gauge pour-test window (a measured cup into the funnel).")
permit (
  principal,
  action == Pukaar::Action::"pour_test",
  resource is Pukaar::Device
)
when {
  principal is Pukaar::Officer ||
  (principal is Pukaar::Pradhan && context.village_id != "" && principal.village_ids.contains(context.village_id))
};

@id("no-replay-sirens")
@desc("A replay never sounds or tests a real siren; only a labelled simulator may answer a replay.")
forbid (
  principal,
  action in [Pukaar::Action::"sound_siren", Pukaar::Action::"test_siren"],
  resource
)
when { context.replay == true && context.device_simulated == false };

@id("drill-never-real-pattern")
@desc("A drill never sounds a warning pattern: drills go through test_siren with the drill pattern (D1).")
forbid (
  principal,
  action == Pukaar::Action::"sound_siren",
  resource
)
when { context.drill == true };

@id("external-cap-never-sounds")
@desc("An external CAP alert (SACHET, IMD, BBMB) is evidence only and never sounds a siren.")
forbid (
  principal,
  action == Pukaar::Action::"sound_siren",
  resource
)
when { context.src == "external_cap" };

@id("public-demo-accounts-never-act-on-sirens")
@desc("Public demo account (judge, judge_pradhan): it may see the devices but never sound, stop, test or change a siren, live or in a replay.")
forbid (
  principal,
  action in [
    Pukaar::Action::"sound_siren", Pukaar::Action::"stop_siren", Pukaar::Action::"test_siren",
    Pukaar::Action::"manage_device", Pukaar::Action::"pour_test"
  ],
  resource
)
when {
  [Pukaar::Officer::"judge", Pukaar::Pradhan::"judge",
   Pukaar::Officer::"judge_pradhan", Pukaar::Pradhan::"judge_pradhan"].contains(principal)
};
