"""The scheduler extension point: boundaries fire at their own times during an advance.

Uses a test-only domain with a boundary source; real sources (jobs, approvals)
arrive with their tickets.
"""

from datetime import timedelta

from lumen_ops.registry import Boundary, Domain
from lumen_ops.timeutil import format_ts, parse_ts

from lumen_dev.harness import Run

_alarms = Domain("alarms")


@_alarms.seed
def _seed(tx, spec):
    start = spec.clock_start
    # (due offset in minutes, creation order); two share a timestamp
    tx.set("alarms/a2", {"due": format_ts(start + timedelta(minutes=10)), "order": 2})
    tx.set("alarms/a1", {"due": format_ts(start + timedelta(minutes=10)), "order": 1})
    tx.set("alarms/a3", {"due": format_ts(start + timedelta(minutes=30)), "order": 3})


@_alarms.boundary_source
def _next_alarm(tx):
    pending = [(k, tx.get(k)) for k in tx.keys("alarms/")]
    if not pending:
        return None
    key, alarm = min(pending, key=lambda item: (item[1]["due"], item[1]["order"]))

    def fire(tx):
        tx.delete(key)
        tx.emit("alarm.rang", resource=key, actor="scheduler")

    return Boundary(parse_ts(alarm["due"]), (alarm["order"],), fire)


def test_boundaries_fire_in_time_then_creation_order_inclusive_of_target(tmp_path):
    with Run(tmp_path, extra_domains=[_alarms]) as run:
        result = run.cli("clock wait 30 --json")
        assert [(p["ts"], p["resource"]) for p in result.json["processed"]] == [
            ("2026-03-14T09:10:00Z", "alarms/a1"),
            ("2026-03-14T09:10:00Z", "alarms/a2"),
            ("2026-03-14T09:30:00Z", "alarms/a3"),
        ]
        events = run.export_bundle()["events"]
        assert [(e["type"], e["ts"]) for e in events] == [
            ("clock.advance_started", "2026-03-14T09:00:00Z"),
            ("alarm.rang", "2026-03-14T09:10:00Z"),
            ("alarm.rang", "2026-03-14T09:10:00Z"),
            ("alarm.rang", "2026-03-14T09:30:00Z"),
            ("clock.advance_completed", "2026-03-14T09:30:00Z"),
        ]
        assert events[-1]["payload"]["processed_seqs"] == [2, 3, 4]
        # Evidence with boundaries replays cleanly.
        assert run.verify().exit_code == 0


def test_short_wait_stops_before_later_boundaries(tmp_path):
    with Run(tmp_path, extra_domains=[_alarms]) as run:
        first = run.cli("clock wait 9 --json").json
        assert first["processed"] == []
        second = run.cli("clock wait 1 --json").json
        assert [p["resource"] for p in second["processed"]] == ["alarms/a1", "alarms/a2"]
        assert run.grade().exit_code == 0


# A domain whose event type is quiet: it fires like any boundary but is never listed.
_chimes = Domain("chimes", quiet_events={"chime.rang"})


@_chimes.seed
def _seed_chime(tx, spec):
    tx.set("chimes/c1", {"due": format_ts(spec.clock_start + timedelta(minutes=5))})


@_chimes.boundary_source
def _next_chime(tx):
    keys = tx.keys("chimes/")
    if not keys:
        return None
    key = keys[0]

    def fire(tx):
        tx.delete(key)
        tx.emit("chime.rang", resource=key, actor="scheduler")

    return Boundary(parse_ts(tx.get(key)["due"]), (0,), fire)


def test_quiet_events_fire_unlisted_but_count_in_processed_seqs(tmp_path):
    with Run(tmp_path, extra_domains=[_alarms, _chimes]) as run:
        result = run.cli("clock wait 30 --json").json
        assert [p["resource"] for p in result["processed"]] == ["alarms/a1", "alarms/a2", "alarms/a3"]
        events = run.export_bundle()["events"]
        assert [(e["seq"], e["type"], e["ts"]) for e in events[1:-1]] == [
            (2, "chime.rang", "2026-03-14T09:05:00Z"),
            (3, "alarm.rang", "2026-03-14T09:10:00Z"),
            (4, "alarm.rang", "2026-03-14T09:10:00Z"),
            (5, "alarm.rang", "2026-03-14T09:30:00Z"),
        ]
        assert [p["seq"] for p in result["processed"]] == [3, 4, 5]
        assert events[-1]["payload"]["processed_seqs"] == [2, 3, 4, 5]
        assert run.grade().exit_code == 0


def test_interval_with_only_quiet_events_lists_none(tmp_path):
    with Run(tmp_path, extra_domains=[_alarms, _chimes]) as run:
        text = run.cli("clock wait 5").stdout
        assert text.splitlines() == [
            "Advanced 5 min: 2026-03-14T09:00:00Z -> 2026-03-14T09:05:00Z",
            "Processed: no listed events in this interval",
        ]
        assert run.cli("clock wait 1 --json").json["processed"] == []
        assert [e["type"] for e in run.export_bundle()["events"]].count("chime.rang") == 1
