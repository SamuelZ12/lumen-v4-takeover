"""Replay every event from the seq-0 baseline and reconcile with the final snapshot.

Each delta's ``before`` must equal the replayed value (``null`` = absent);
applying ``after`` gives the next state. After each event the replayed clock
must equal the event's ``ts``. Domain validators then check cross-event
consistency (references, pairing). The reconstructed state must equal the
final snapshot exactly. Any mismatch is an :class:`IntegrityError`.
"""

from typing import Any, Iterable

from . import CLOCK_KEY
from .trace import IntegrityError, Step, Trace, Validator


def _fmt(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 120 else text[:117] + "..."


def replay(bundle: dict[str, Any], validators: Iterable[Validator] = ()) -> Trace:
    trace = Trace(run_id=bundle["metadata"]["run_id"], baseline=bundle["baseline"], final=bundle["final"])
    state = dict(bundle["baseline"]["state"])
    problems: list[str] = []
    for event in bundle["events"]:
        before = state
        after = dict(state)
        for change in event["delta"]:
            key = change["key"]
            if after.get(key) != change["before"]:
                problems.append(
                    f"seq {event['seq']}: delta before for {key!r} is {_fmt(change['before'])}, "
                    f"replayed state has {_fmt(after.get(key))}"
                )
            if change["after"] is None:
                after.pop(key, None)
            else:
                after[key] = change["after"]
        clock = after.get(CLOCK_KEY)
        if not isinstance(clock, dict) or clock.get("now") != event["ts"]:
            problems.append(f"seq {event['seq']}: event ts {event['ts']} != replayed clock {_fmt(clock)}")
        if problems:
            raise IntegrityError(problems)
        trace.steps.append(Step(event=event, before=before, after=after))
        state = after

    for validator in validators:
        problems.extend(f"{validator.name}: {p}" for p in validator.validate(trace))

    if state != bundle["final"]["state"]:
        differing = sorted(
            key for key in state.keys() | bundle["final"]["state"].keys()
            if state.get(key) != bundle["final"]["state"].get(key)
        )
        problems.append(f"final snapshot does not match replayed state; differing keys {differing[:20]}")
    if problems:
        raise IntegrityError(problems)
    return trace
