"""Fake clock through the public CLI."""

START = "2026-03-14T09:00:00Z"


def test_clock_now_reports_seeded_start(run):
    result = run.cli("clock now --json")
    assert result.exit_code == 0, result.stderr
    assert result.json["now"] == START


def test_clock_wait_advances_fake_time(run):
    result = run.cli("clock wait 30 --json")
    assert result.exit_code == 0, result.stderr
    assert result.json["now"] == "2026-03-14T09:30:00Z"
    assert run.cli("clock now --json").json["now"] == "2026-03-14T09:30:00Z"


def test_clock_wait_logs_started_at_old_time_and_completed_at_target(run):
    run.cli("clock wait 45")
    events = run.export_bundle()["events"]
    started, completed = events[-2], events[-1]

    assert started["type"] == "clock.advance_started"
    assert started["ts"] == START
    assert started["payload"]["target"] == "2026-03-14T09:45:00Z"
    assert started["payload"]["reason"] == "clock_wait"
    assert started["delta"] == []

    assert completed["type"] == "clock.advance_completed"
    assert completed["ts"] == "2026-03-14T09:45:00Z"
    assert completed["payload"]["final"] == "2026-03-14T09:45:00Z"
    assert completed["delta"] == [
        {"key": "clock", "before": {"now": START}, "after": {"now": "2026-03-14T09:45:00Z"}}
    ]


def test_events_carry_the_envelope(run):
    run.cli("clock wait 5")
    bundle = run.export_bundle()
    for event in bundle["events"]:
        assert event["schema_version"] == 1
        assert event["run_id"] == bundle["metadata"]["run_id"]
        assert event["actor"] == "agent"
        assert event["outcome"] == "accepted"
        assert event["resource"] == "clock"
        assert event["request_id"]
        assert "job_id" in event
    assert [e["seq"] for e in bundle["events"]] == [1, 2]


def test_human_output_shows_the_same_time(run):
    result = run.cli("clock now")
    assert result.exit_code == 0
    assert START in result.stdout


def test_reads_cost_no_time_and_log_nothing(run):
    run.cli("clock now")
    run.cli("clock now --json")
    bundle = run.export_bundle()
    assert bundle["events"] == []
    assert bundle["final"]["ts"] == START
