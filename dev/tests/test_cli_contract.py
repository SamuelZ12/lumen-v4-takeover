"""CLI error contract.

Usage/schema errors exit 2, missing resources/state conflicts exit 3, errors
are atomic (no state or time change), every command has --help and --json.
"""

import json

import pytest

from lumen_cli.registry import Arg, Command, discover
from lumen_ops.errors import NotFound, StateError
from lumen_ops.registry import Domain

from lumen_dev.harness import Run

START = "2026-03-14T09:00:00Z"


def _final_state(run):
    return run.export_bundle()["final"]["state"]


@pytest.mark.parametrize("minutes", ["-5", "1.5", "abc", "", "٣", pytest.param("5" * 5000, id="5000-digits")])
def test_bad_wait_is_a_usage_error_and_changes_nothing(run, minutes):
    before = _final_state(run)
    result = run.cli(["clock", "wait", minutes, "--json"])
    assert result.exit_code == 2
    assert result.json["error"]["code"] == "E_BAD_DURATION"
    assert _final_state(run) == before


def test_rejected_wait_is_logged_without_a_delta(run):
    run.cli("clock wait -5")
    events = run.export_bundle()["events"]
    assert len(events) == 1
    assert events[0]["type"] == "clock.wait"
    assert events[0]["outcome"] == "rejected"
    assert events[0]["delta"] == []
    assert events[0]["payload"]["error"]["code"] == "E_BAD_DURATION"


def test_human_error_goes_to_stderr(run):
    result = run.cli("clock wait nope")
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "E_BAD_DURATION" in result.stderr


def test_argparse_usage_errors_exit_2_without_reaching_the_sidecar(run):
    for argv in ["clock", "clock wait", "clock frobnicate", "clock now extra", "clock wait 1 --bogus"]:
        result = run.cli(argv)
        assert result.exit_code == 2, argv
    assert run.export_bundle()["events"] == []


def test_usage_error_with_json_prints_json(run):
    result = run.cli("clock frobnicate --json")
    assert result.exit_code == 2
    assert result.json["error"]["code"] == "E_USAGE"


def _leaf_commands():
    catalog = discover()
    return [c.path for c in catalog.commands]


@pytest.mark.parametrize("path", _leaf_commands(), ids=" ".join)
def test_every_command_has_help_and_json(run, path):
    result = run.cli([*path, "--help"])
    assert result.exit_code == 0
    assert "--json" in result.stdout


@pytest.mark.parametrize("program", sorted(discover().programs))
def test_every_program_has_help(run, program):
    result = run.cli([program, "--help"])
    assert result.exit_code == 0
    assert "usage:" in result.stdout


def _command_groups():
    return sorted({c.path[:i] for c in discover().commands for i in range(2, len(c.path))})


@pytest.mark.parametrize("path", _command_groups(), ids=" ".join)
def test_every_command_group_has_help(run, path):
    """Group help lists each subcommand's one-line help (e.g. `serve traffic set`'s "<n>% of traffic")."""
    result = run.cli([*path, "--help"])
    assert result.exit_code == 0
    assert "usage:" in result.stdout


# A test-only domain proves the exit-3 plumbing and atomicity of failed mutations.
_probe = Domain("probe")


@_probe.command("probe.touch_then_fail", mutating=True, resource="probe")
def _touch_then_fail(tx, args):
    tx.set("clock", {"now": "2026-03-14T10:00:00Z"})
    tx.emit("probe.touched", resource="probe")
    if args["mode"] == "missing":
        raise NotFound("no such probe")
    raise StateError("probe busy", code="E_PROBE_BUSY")


class _ProbeCli:
    PROGRAMS = {"probe": "test-only program"}
    COMMANDS = [
        Command(("probe", "fail"), "probe.touch_then_fail", "fail after writing", args=(Arg("mode", "missing|busy"),))
    ]


@pytest.mark.parametrize("mode,code", [("missing", "E_NOT_FOUND"), ("busy", "E_PROBE_BUSY")])
def test_not_found_and_state_errors_exit_3_atomically(tmp_path, mode, code):
    with Run(tmp_path, extra_domains=[_probe], extra_cli_modules=[_ProbeCli]) as run:
        result = run.cli(["probe", "fail", mode, "--json"])
        assert result.exit_code == 3
        assert result.json["error"]["code"] == code
        bundle = run.export_bundle()
        assert bundle["final"]["ts"] == START  # the write before the error was rolled back
        assert [(e["type"], e["outcome"]) for e in bundle["events"]] == [("probe.touch_then_fail", "rejected")]
