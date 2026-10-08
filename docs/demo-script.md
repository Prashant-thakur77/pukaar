# Demo script

## Goal

Show that Pukaar and Pukaar are not separate demos. They are two evidence
sources feeding one municipal decision center.

## Run

Backend:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_decision_engine.py
```

Full backend validation:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```

## Scenario 1: only Pukaar

1. Create or select a calibrated site.
2. Run a fixed-node analysis with `/api/node/analyze` or
   `/api/sites/{site_id}/sample-node-analysis`.
3. Open the generated alert.
4. Explain: the decision trace shows node evidence, critical-line status,
   temporal weight, and whether the node alone reached yellow/orange/red.

## Scenario 2: only Pukaar

1. Submit an offline volunteer report: "el agua paso la marca critica y la ruta
   esta cortada".
2. Pukaar persists `VolunteerReport` and `ParsedObservation`.
3. The central engine opens or escalates an incident from human evidence.
4. Explain: a critical human report can escalate without waiting for hydromet,
   but the trace marks the source and rules explicitly.

## Scenario 3: Pukaar + Pukaar corroborated

1. Add a medium/high node observation within the evidence window.
2. Add a medium/high volunteer report in the same site.
3. Recompute `/api/alerts/recompute`.
4. Explain: two medium signals from different sources escalate more than either
   source alone. The trace includes `corroboration_sources` and
   `two_medium_sources_escalate_to_orange` when applicable.

## Scenario 4: hydromet context

1. Refresh hydromet or insert a snapshot with heavy rain and rising discharge.
2. Recompute the alert.
3. Explain: hydromet can corroborate local evidence but does not erase strong
   local observations if the forecast feed is quiet.

## Scenario 5: connectivity loss and sync

1. Generate evidence while edge is offline.
2. Confirm `/api/sync/status` shows pending items.
3. Run `POST /api/sync/flush`.
4. Run it again.
5. Explain: the second flush does not duplicate evidence or alerts. Queue items
   track attempts, errors, and synced timestamps.

## Operator story

Use:

- `GET /api/sites/{site_id}/operator-summary` for dashboard state.
- `GET /api/incidents/{incident_id}/timeline` for escalation history.
- `POST /api/incidents/{incident_id}/ack` for operator acknowledgement.
- `POST /api/incidents/{incident_id}/close` for manual closure with reason.
- `POST /api/alerts/{alert_id}/export-sinagir` for institutional export.

## Limits to state clearly

- This is SINAGIR-ready/SINAME-ready JSON export, not official live integration.
- Actuators are replaceable stubs in CI and demos unless deployment hardware is
  configured.
- Scoring thresholds are auditable and tested, but still calibration inputs for
  municipal deployment.
