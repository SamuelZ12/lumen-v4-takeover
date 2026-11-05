"""Serving config and traffic consistency across replay.

- Every state: layer values are schema-valid, each model's stored effective
  record equals the recomputed merge and revision, traffic is a whole-number
  split of 100% between two models.
- Config documents and effective records change only through accepted
  ``serve.config_key_set`` / ``serve.config_key_removed`` events, each changing
  exactly the one entry its payload names, with payload old/new values and
  before/after effective identities matching the replayed states, and one
  history entry citing the event.
- Traffic changes only through accepted ``serve.traffic_set`` events whose
  payload old/new shares match, starting a new interval at the event time,
  with one history entry citing the event.
"""

from ..trace import Trace, Validator
from ..serve import (
    BASE_PREFIX,
    CONFIG_HISTORY_KEY,
    EFFECTIVE_PREFIX,
    OVERRIDE_KEY,
    TRAFFIC_HISTORY_KEY,
    TRAFFIC_KEY,
    effective,
    layer_entries,
    models,
)

CONFIG_EVENTS = {"serve.config_key_set", "serve.config_key_removed"}
CONFIG_KEYS = {CONFIG_HISTORY_KEY, OVERRIDE_KEY}


def _is_config_key(key: str) -> bool:
    return key in CONFIG_KEYS or key.startswith(BASE_PREFIX) or key.startswith(EFFECTIVE_PREFIX)


def _identity(record):
    return {"snapshot": record["snapshot"], "revision": record["revision"]}


def _state_problems(where: str, state: dict):
    names = models(state)
    for model in names:
        try:
            record = effective(state, model)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            yield f"{where}: invalid config for {model}: {error}"
            continue
        if state.get(EFFECTIVE_PREFIX + model) != record:
            yield f"{where}: stored effective config of {model} does not match its layers"
    stray = sorted(
        k for k in state
        if k.startswith(EFFECTIVE_PREFIX) and k[len(EFFECTIVE_PREFIX):] not in names
    )
    if stray:
        yield f"{where}: effective records without a base config: {stray}"
    override = state.get(OVERRIDE_KEY) or {"entries": {}}
    orphans = sorted(set(override["entries"]) - set(names))
    if orphans:
        yield f"{where}: override sections for unknown models {orphans}"
    traffic = state.get(TRAFFIC_KEY)
    if traffic is not None:
        shares = traffic.get("shares")
        if (
            not isinstance(shares, dict)
            or len(shares) != 2
            or not all(isinstance(s, int) and not isinstance(s, bool) and 0 <= s <= 100 for s in shares.values())
            or sum(shares.values()) != 100
        ):
            yield f"{where}: traffic shares {shares!r} are not a whole-number 100% split"


def _appended(before: dict, after: dict, key: str):
    old, new = before.get(key) or [], after.get(key) or []
    if len(new) != len(old) + 1 or new[: len(old)] != old:
        return None
    return new[-1]


def _config_event(step):
    event, payload = step.event, step.event["payload"]
    model, layer, key = payload.get("model"), payload.get("layer"), payload.get("key")
    seq = step.seq
    if model not in models(step.before) or layer not in ("base", "prod_override"):
        yield f"seq {seq}: config event for unknown model/layer {model!r}/{layer!r}"
        return
    before_entries = layer_entries(step.before, layer, model)
    after_entries = layer_entries(step.after, layer, model)
    old = before_entries.get(key, {}).get("value")
    new = after_entries.get(key, {}).get("value")
    if (old, new) != (payload.get("old"), payload.get("new")) or old == new and key in after_entries:
        yield f"seq {seq}: payload old/new {payload.get('old')!r}/{payload.get('new')!r} != layer change {old!r}/{new!r}"
    if event["type"] == "serve.config_key_removed" and key in after_entries:
        yield f"seq {seq}: removal left {key!r} in the {layer} layer"
    others_before = {k: v for k, v in before_entries.items() if k != key}
    others_after = {k: v for k, v in after_entries.items() if k != key}
    if others_before != others_after:
        yield f"seq {seq}: config event changed entries other than {key!r}"
    for other_layer in ("base", "prod_override"):
        for other_model in models(step.after):
            if (other_layer, other_model) != (layer, model) and layer_entries(
                step.before, other_layer, other_model
            ) != layer_entries(step.after, other_layer, other_model):
                yield f"seq {seq}: config event changed {other_layer} layer of {other_model}"
    try:
        before_identity = _identity(effective(step.before, model))
        after_identity = _identity(effective(step.after, model))
    except (ValueError, KeyError, TypeError):
        return  # reported by the state check
    if payload.get("effective_before") != before_identity:
        yield f"seq {seq}: effective_before does not match the replayed state"
    if payload.get("effective_after") != after_identity:
        yield f"seq {seq}: effective_after does not match the replayed state"
    entry = _appended(step.before, step.after, CONFIG_HISTORY_KEY)
    if entry is None or entry.get("seq") != seq or entry.get("ts") != step.ts or entry.get("key") != key:
        yield f"seq {seq}: config change has no matching history entry"


def _traffic_event(step):
    payload, seq = step.event["payload"], step.seq
    before, after = step.before.get(TRAFFIC_KEY), step.after.get(TRAFFIC_KEY)
    if payload.get("old") != before["shares"] or payload.get("new") != after["shares"]:
        yield f"seq {seq}: traffic payload old/new do not match the replayed shares"
    if after.get("since") != step.ts:
        yield f"seq {seq}: new traffic interval does not start at the event time"
    entry = _appended(step.before, step.after, TRAFFIC_HISTORY_KEY)
    if entry is None or entry.get("seq") != seq or entry.get("new") != after["shares"]:
        yield f"seq {seq}: traffic change has no matching history entry"


def validate(trace: Trace):
    yield from _state_problems("baseline", trace.initial_state)
    for step in trace.steps:
        event = step.event
        changed = {d["key"] for d in event["delta"]}
        yield from _state_problems(f"seq {step.seq}", step.after)
        config_changed = any(_is_config_key(k) for k in changed)
        traffic_changed = bool(changed & {TRAFFIC_KEY, TRAFFIC_HISTORY_KEY})
        accepted = event["outcome"] == "accepted"
        if config_changed:
            if not (accepted and event["type"] in CONFIG_EVENTS):
                yield f"seq {step.seq}: {event['type']} changed serving config"
            else:
                yield from _config_event(step)
        if traffic_changed:
            if not (accepted and event["type"] == "serve.traffic_set"):
                yield f"seq {step.seq}: {event['type']} changed traffic"
            else:
                yield from _traffic_event(step)
        elif accepted and event["type"] == "serve.traffic_set":
            yield f"seq {step.seq}: accepted traffic change without a state change"
        if accepted and event["type"] in CONFIG_EVENTS and not config_changed:
            yield f"seq {step.seq}: accepted config change without a state change"


VALIDATOR = Validator("serve", validate)
