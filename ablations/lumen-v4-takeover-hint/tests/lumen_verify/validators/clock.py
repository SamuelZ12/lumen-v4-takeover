"""Fake-clock consistency: only advances move time, and they never backdate.

An advance is ``clock.advance_started`` at the old time (target and reason,
no time change), then only scheduler events at their own boundary times, then
``clock.advance_completed`` at the target. No other event may change the clock.
"""

from .. import CLOCK_KEY
from ..bundle import parse_ts
from ..trace import Trace, Validator

REASONS = {"clock_wait", "job_runtime"}


def validate(trace: Trace):
    open_span = None  # payload of the advance in progress
    for step in trace.steps:
        event, payload = step.event, step.event["payload"]
        moved = any(d["key"] == CLOCK_KEY for d in event["delta"])
        kind = event["type"]
        if event["outcome"] != "accepted":
            if open_span is not None:
                yield f"seq {step.seq}: {event['outcome']} event inside a clock advance"
            continue
        if kind == "clock.advance_started":
            if open_span is not None:
                yield f"seq {step.seq}: advance started while another is in progress"
            if moved:
                yield f"seq {step.seq}: advance_started must not move the clock"
            if payload.get("reason") not in REASONS:
                yield f"seq {step.seq}: advance reason {payload.get('reason')!r} not in {sorted(REASONS)}"
            if payload.get("from") != step.ts:
                yield f"seq {step.seq}: advance_started 'from' {payload.get('from')!r} is not its ts"
            target = parse_ts(payload.get("target"))
            if target is None or target < parse_ts(step.ts):
                yield f"seq {step.seq}: advance target {payload.get('target')!r} is invalid"
                target = None
            open_span = {"target": payload.get("target") if target else step.ts}
        elif kind == "clock.advance_completed":
            if open_span is None:
                yield f"seq {step.seq}: advance_completed without advance_started"
                continue
            if step.ts != open_span["target"] or payload.get("final") != open_span["target"]:
                yield f"seq {step.seq}: advance completed at {step.ts}, target was {open_span['target']}"
            open_span = None
        elif open_span is not None:
            if event["actor"] != "scheduler":
                yield f"seq {step.seq}: {event['actor']} event inside a clock advance"
            if parse_ts(step.ts) > parse_ts(open_span["target"]):
                yield f"seq {step.seq}: scheduler event after the advance target"
        elif moved:
            yield f"seq {step.seq}: {kind} moved the fake clock outside an advance"
    if open_span is not None:
        yield "log ends inside an unfinished clock advance"


VALIDATOR = Validator("clock", validate)
