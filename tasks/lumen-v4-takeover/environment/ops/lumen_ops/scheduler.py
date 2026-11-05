"""The single fake-clock scheduler shared by every CLI.

Only an advance moves time. An advance logs ``clock.advance_started`` at the
old time, then fires every scheduled boundary up to and including the target
in ``(ts, order)`` order, each at its own timestamp, then logs
``clock.advance_completed`` at the target. Nothing is ever backdated.

Boundary ``order`` convention (comparable across domains): ``(created_seq,
rank, id)`` where ``created_seq`` is the seq of the event that scheduled the
item (``Tx.next_seq`` when it is created; 0 for seeded items), ``rank`` orders
several boundaries of one item at the same time (jobs: heartbeat 0 before
completion 1) and ``id`` makes the order total. Equal timestamps therefore
fire in creation order. Sources are re-queried after every fire, so a fire may
schedule or cancel later boundaries.
"""

from datetime import datetime
from typing import Any

from . import CLOCK_KEY
from .timeutil import format_ts

ADVANCE_REASONS = ("clock_wait", "job_runtime")


def _next_boundary(tx):
    candidates = [b for source in tx.registry.boundary_sources if (b := source(tx)) is not None]
    return min(candidates, key=lambda b: (b.ts, b.order), default=None)


def advance(tx, target: datetime, *, reason: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Advance the fake clock to ``target`` processing intervening boundaries."""
    if reason not in ADVANCE_REASONS:
        raise ValueError(f"reason must be one of {ADVANCE_REASONS}")
    start = tx.now()
    if target < start:
        raise ValueError("cannot advance the clock backwards")
    span = {"from": format_ts(start), "target": format_ts(target), "reason": reason, **(payload or {})}
    tx.emit("clock.advance_started", resource="clock", payload=span)

    fired_seqs: list[int] = []
    processed: list[dict[str, Any]] = []
    while (boundary := _next_boundary(tx)) is not None and boundary.ts <= target:
        if boundary.ts < tx.now():
            raise RuntimeError(f"boundary {boundary.order} is in the past")
        tx.set(CLOCK_KEY, {"now": format_ts(boundary.ts)})
        emitted = len(tx.events)
        boundary.fire(tx)
        fired = tx.events[emitted:]
        if not fired:
            raise RuntimeError(f"boundary {boundary.order} fired without emitting an event")
        fired_seqs.extend(e["seq"] for e in fired)
        processed.extend(
            {"seq": e["seq"], "ts": e["ts"], "type": e["type"], "resource": e["resource"], "job_id": e["job_id"],
             "summary": tx.registry.summarize(e)}
            for e in fired
            if e["type"] not in tx.registry.quiet_events
        )

    tx.set(CLOCK_KEY, {"now": format_ts(target)})
    tx.emit(
        "clock.advance_completed",
        resource="clock",
        payload={**span, "final": format_ts(target), "processed_seqs": fired_seqs},
    )
    return {"from": span["from"], "now": format_ts(target), "reason": reason, "processed": processed}
