// Pukaar role policies. Default is deny; forbid overrides permit.
// Principals: Pukaar::Officer, Pukaar::Pradhan, Pukaar::System, Pukaar::Agent.
// Resources:  Pukaar::Village, Pukaar::Alert, Pukaar::Report, Pukaar::Tool, Pukaar::App.
// Context:    level, approved, all_officers_timed_out, replay, channel, village_id.

@id("officer-operate")
@desc("Officers run the console: approve or decline alerts, triage reports, issue directives, run replays, read the audit trail and ask the analyst.")
permit (
  principal is Pukaar::Officer,
  action in [
    Pukaar::Action::"view_console", Pukaar::Action::"approve", Pukaar::Action::"decline",
    Pukaar::Action::"view_reports", Pukaar::Action::"set_report_state", Pukaar::Action::"issue_directive",
    Pukaar::Action::"start_replay", Pukaar::Action::"read_audit", Pukaar::Action::"ask_analyst",
    Pukaar::Action::"health_deep"
  ],
  resource
);

@id("pradhan-own-village")
@desc("A pradhan sees the console and the reports of their own villages only.")
permit (
  principal is Pukaar::Pradhan,
  action in [Pukaar::Action::"view_console", Pukaar::Action::"view_reports"],
  resource
)
when { context.village_id == "" || principal.village_ids.contains(context.village_id) };

@id("system-deliver-approved")
@desc("The system delivers an alert only after an officer approved it.")
permit (
  principal is Pukaar::System,
  action == Pukaar::Action::"deliver",
  resource is Pukaar::Alert
)
when { context.approved == true };

@id("system-critical-auto-send")
@desc("The system may send without approval only a critical alert after every officer timed out; it is flagged as unapproved.")
permit (
  principal is Pukaar::System,
  action in [Pukaar::Action::"auto_send", Pukaar::Action::"deliver"],
  resource is Pukaar::Alert
)
when { context.level == "critical" && context.all_officers_timed_out == true };

@id("system-failsafe")
@desc("When the workflow itself fails, the system sends the fixed safety template so a broken pipeline never means silence.")
permit (
  principal is Pukaar::System,
  action == Pukaar::Action::"failsafe",
  resource is Pukaar::Alert
);

@id("agent-read-only-tools")
@desc("Model agents may call only read-only tools from the allowlist.")
permit (
  principal is Pukaar::Agent,
  action == Pukaar::Action::"use_tool",
  resource in Pukaar::ToolGroup::"read_only"
);

@id("no-replay-to-phones")
@desc("Replay alerts never reach real phones; they go to the stub channel only.")
forbid (
  principal,
  action in [Pukaar::Action::"deliver", Pukaar::Action::"auto_send", Pukaar::Action::"failsafe"],
  resource
)
when { context.replay == true && context.channel == "telegram" };

@id("agents-never-send")
@desc("A model agent can never approve, send or change a level.")
forbid (
  principal is Pukaar::Agent,
  action in [
    Pukaar::Action::"approve", Pukaar::Action::"decline", Pukaar::Action::"deliver",
    Pukaar::Action::"auto_send", Pukaar::Action::"failsafe", Pukaar::Action::"issue_directive"
  ],
  resource
);
