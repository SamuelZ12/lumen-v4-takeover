"""Notification consistency: receipts are append-only and only delivery events create them.

- ``notify/receipts/<id>`` changes only in ``notify.delivery_recorded``, from
  absent to a receipt whose ID matches its key and equals the event payload;
  each delivery event creates exactly one receipt.
- ``notify/changelog/<campaign>`` changes only in ``notify.changelog_published``
  and is never removed.
- Seeded campaigns never change.
"""

from ..notify import CAMPAIGNS_PREFIX as CAMPAIGNS, CHANGELOG_PREFIX as CHANGELOG, RECEIPTS_PREFIX as RECEIPTS
from ..trace import Trace, Validator


def validate(trace: Trace):
    for step in trace.steps:
        event = step.event
        kind = event["type"]
        receipts = [d for d in event["delta"] if d["key"].startswith(RECEIPTS)]
        for change in event["delta"]:
            key = change["key"]
            if key.startswith(CAMPAIGNS):
                yield f"seq {step.seq}: {kind} changed seeded campaign {key}"
            elif key.startswith(CHANGELOG):
                if kind != "notify.changelog_published" or change["after"] is None:
                    yield f"seq {step.seq}: {kind} changed changelog {key} outside a publication"
        if kind == "notify.delivery_recorded":
            if len(receipts) != 1:
                yield f"seq {step.seq}: delivery event must create exactly one receipt, changed {len(receipts)}"
                continue
            change = receipts[0]
            receipt = change["after"]
            if change["before"] is not None or not isinstance(receipt, dict):
                yield f"seq {step.seq}: delivery changed existing receipt {change['key']}"
            elif change["key"] != RECEIPTS + str(receipt.get("receipt_id")) or event["payload"] != receipt:
                yield f"seq {step.seq}: delivery payload disagrees with receipt {change['key']}"
        elif receipts:
            yield f"seq {step.seq}: {kind} changed receipt(s) {[d['key'] for d in receipts]} outside a delivery"


VALIDATOR = Validator("notify", validate)
