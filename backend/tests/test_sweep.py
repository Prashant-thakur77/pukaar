from datetime import timedelta

from Pukaar.core import clock
from Pukaar.services import decision_engine as de
from Pukaar.services import external_data, replay
from Pukaar.store.models import Reading


def make_reading(village, at, peak):
    return Reading(village_id=village.id, at=clock.iso(at), rain_24h_mm=0.0, discharge_peak=peak,
                   discharge_forecast=[{"date": at.date().isoformat(), "value": peak}])


def test_sweep_window_is_deduplicated(repo, frozen, workflow):
    v = repo.get_village("thunag")
    fetch = lambda village, at: make_reading(village, at, 0.1)  # noqa: E731
    first = de.recompute_village(repo, v, now=frozen["now"], fetch=fetch, workflow=workflow, window_prefix="live")
    again = de.recompute_village(repo, v, now=frozen["now"] + timedelta(minutes=5), fetch=fetch, workflow=workflow,
                                 window_prefix="live")
    assert not first.skipped and again.skipped
    assert len(repo.list_readings("thunag")) == 1


def test_rise_creates_one_alert_and_starts_workflow(repo, frozen, workflow):
    v = repo.get_village("thunag")
    res = de.recompute_village(repo, v, now=frozen["now"], reading=make_reading(v, frozen["now"], v.thresholds.warning))
    assert res.rose and res.level == "warning"
    assert repo.get_village("thunag").open_alert_id == res.alert_id
    alert = repo.get_alert(res.alert_id)
    assert alert.status == "drafting" and alert.decision_trace["schema"] == "risk-rules-v1"

    v2 = repo.get_village("gohar")
    res2 = de.recompute_village(repo, v2, now=frozen["now"], reading=make_reading(v2, frozen["now"], v2.thresholds.watch),
                                workflow=workflow)
    assert workflow.started == [res2.alert_id]


def test_unchanged_level_sends_nothing_new(repo, frozen, workflow):
    v = repo.get_village("thunag")
    r = make_reading(v, frozen["now"], v.thresholds.watch)
    de.recompute_village(repo, v, now=frozen["now"], reading=r, workflow=workflow)
    de.recompute_village(repo, repo.get_village("thunag"), now=frozen["now"], reading=r, workflow=workflow)
    assert len(workflow.started) == 1


def test_rise_while_pending_escalates_the_same_alert(repo, frozen, workflow):
    v = repo.get_village("thunag")
    first = de.recompute_village(repo, v, now=frozen["now"], reading=make_reading(v, frozen["now"], v.thresholds.watch),
                                 workflow=workflow)
    repo.update_alert(first.alert_id, status="pending")
    second = de.recompute_village(repo, repo.get_village("thunag"), now=frozen["now"],
                                  reading=make_reading(v, frozen["now"], v.thresholds.critical), workflow=workflow)
    assert second.alert_id == first.alert_id and len(workflow.started) == 1
    alert = repo.get_alert(first.alert_id)
    assert alert.level == "critical" and alert.reasoning_model == "rule-fallback"
    assert [t.step for t in repo.list_timeline(alert.id)][-1] == "escalated"


def test_daily_cap_stops_new_alerts(repo, frozen, workflow):
    v = repo.get_village("thunag")
    for _ in range(6):
        repo.put_alert(repo_alert(v, frozen))
    res = de.recompute_village(repo, v, now=frozen["now"], reading=make_reading(v, frozen["now"], v.thresholds.watch),
                               workflow=workflow)
    assert res.alert_id is None and "daily cap" in res.note


def repo_alert(v, frozen):
    from Pukaar.core.ids import new_id
    from Pukaar.store.models import Alert

    stamp = clock.iso(frozen["now"])
    return Alert(id=new_id("alr"), village_id=v.id, village_name=v.name, village_name_hi=v.name_hi, level="watch",
                 status="closed", created_at=stamp, updated_at=stamp)


def test_replay_writes_are_labelled_and_reset_removes_them(repo, frozen, workflow):
    replay.start(repo, "himachal_2023_07")
    v = repo.get_village("sujanpur")
    hour = external_data.replay_hours("himachal_2023_07")[60]
    reading = external_data.replay_reading("himachal_2023_07", v, hour)
    assert reading.replay and reading.source == "replay:himachal_2023_07"
    repo.put_reading(reading)
    res = de.recompute_village(repo, v, now=hour, reading=reading, workflow=workflow, replay=True)
    alert = repo.get_alert(res.alert_id)
    assert alert.replay and alert.decision_trace["replay"]
    replay.reset(repo)
    assert repo.get_alert(alert.id) is None
    assert all(not r.replay for r in repo.list_readings("sujanpur"))
    assert repo.get_village("sujanpur").level == "normal"


def test_backtest_reports_crossings_and_misses(repo):
    july = {r["village_id"]: r for r in replay.backtest("himachal_2023_07", repo.list_villages())}
    assert july["sujanpur"]["first_critical"] is not None
    mandi = {r["village_id"]: r for r in replay.backtest("mandi_2025", repo.list_villages())}
    assert mandi["thunag"]["outcome"] == "never crossed"


def test_one_failing_village_does_not_stop_the_sweep(repo, frozen, workflow):
    def fetch(village, at):
        if village.id == "gohar":
            raise RuntimeError("upstream down")
        return make_reading(village, at, 0.0)

    results = de.sweep_all(repo, now=frozen["now"], fetch=fetch, workflow=workflow)
    notes = {r.village_id: r.note for r in results}
    assert notes["gohar"].startswith("error") and notes["thunag"] == ""


def _finish_replay(repo, frozen, minutes_ago):
    replay.start(repo, "himachal_2023_07")
    repo.update_village("sujanpur", level="critical", calm_sweeps=0, replay=False)
    st = repo.get_replay()
    st.active, st.updated_at = False, clock.iso(frozen["now"] - timedelta(minutes=minutes_ago))
    repo.put_replay(st)


def test_live_sweep_clears_a_replay_finished_over_30_minutes_ago(repo, frozen, workflow):
    _finish_replay(repo, frozen, minutes_ago=31)
    de.sweep_all(repo, now=frozen["now"], fetch=lambda v, at: make_reading(v, at, 0.0), workflow=workflow)
    assert repo.get_replay().scenario is None
    assert repo.get_village("sujanpur").level == "normal"


def test_live_sweep_keeps_a_recently_finished_replay(repo, frozen, workflow):
    _finish_replay(repo, frozen, minutes_ago=10)
    de.sweep_all(repo, now=frozen["now"], fetch=lambda v, at: make_reading(v, at, 0.0), workflow=workflow)
    assert repo.get_replay().scenario == "himachal_2023_07"
    assert repo.get_village("sujanpur").level == "critical"  # hysteresis still holding the replay level
