"""Weights registry consistency across replay.

- Baseline: every registry document is well-formed with only published artifacts
  (valid ``sha256:`` checksums) and one ``published`` history entry per artifact;
  every scheduled yank is an unfired anchored record naming a published artifact
  of its model, with a reason, an actor and a well-formed artifact to publish.
- A registry document changes only in the accepted scheduler event
  ``registry.artifact_yanked`` that fires its model's scheduled yank, exactly at
  anchor + delay and once (``incidents.scheduled_event_problems``; a yank still
  missing after its due time is an integrity error). That event yanks exactly the
  planned version at the event time with the planned reason, appends the planned
  artifact as published at the event time, appends the two matching history
  entries, and its payload names them.
- No scheduled yank appears after the baseline.
"""

from ..incidents import scheduled_event_problems
from ..serve import SCHEMA
from ..trace import Trace, Validator
from ..weights import (
    ARTIFACT_FIELDS, HISTORY_FIELDS, PUBLISHED, REGISTRY_PREFIX, SCHEDULED_PREFIX, YANK_EVENT, YANKED, ref,
)


def _valid_sha(value) -> bool:
    try:
        SCHEMA["weights_sha"](value)
    except ValueError:
        return False
    return True


def _baseline_doc(model, doc):
    if not isinstance(doc, dict) or set(doc) != {"model", "artifacts", "history"} or doc["model"] != model:
        yield f"baseline: registry document of {model} is malformed"
        return
    for artifact in doc["artifacts"]:
        if (not isinstance(artifact, dict) or set(artifact) != ARTIFACT_FIELDS or artifact["status"] != PUBLISHED
                or not _valid_sha(artifact["sha"]) or artifact["yanked_at"] is not None):
            yield f"baseline: registry artifact {artifact!r} of {model} is malformed or not published"
            return
    expected = [(a["published_at"], "published", a["version"], a["sha"], None) for a in doc["artifacts"]]
    history = doc["history"]
    if (not all(isinstance(h, dict) and set(h) == HISTORY_FIELDS for h in history)
            or [(h["ts"], h["action"], h["version"], h["sha"], h["reason"]) for h in history] != expected):
        yield f"baseline: registry history of {model} does not list its published artifacts"


def _baseline_plan(key, plan, state):
    model = plan.get("model") if isinstance(plan, dict) else None
    published = (plan or {}).get("publish")
    versions = {a["version"] for a in (state.get(REGISTRY_PREFIX + str(model)) or {}).get("artifacts", [])}
    if (model is None or key != SCHEDULED_PREFIX + model or plan.get("version") not in versions
            or not isinstance(plan.get("reason"), str) or not isinstance(plan.get("actor"), str)
            or not isinstance(published, dict) or set(published) != {"version", "sha"}
            or not _valid_sha(published["sha"]) or published["version"] in versions):
        yield f"baseline: scheduled yank {key} is malformed"


def _yanked(doc, plan, ts):
    artifacts = [
        {**a, "status": YANKED, "yanked_at": ts, "reason": plan["reason"]} if a["version"] == plan["version"] else a
        for a in doc["artifacts"]
    ]
    (yanked,) = [a for a in artifacts if a["version"] == plan["version"]]
    new = {**plan["publish"], "status": PUBLISHED, "published_at": ts, "yanked_at": None, "reason": None}
    history = [
        *doc["history"],
        {"ts": ts, "actor": plan["actor"], "action": YANKED, "version": yanked["version"], "sha": yanked["sha"],
         "reason": plan["reason"]},
        {"ts": ts, "actor": plan["actor"], "action": PUBLISHED, "version": new["version"], "sha": new["sha"],
         "reason": None},
    ]
    return {"model": doc["model"], "artifacts": [*artifacts, new], "history": history}, yanked, new


def _step_problems(step, baseline_plans):
    event, seq = step.event, step.seq
    accepted = event["outcome"] == "accepted"
    is_yank = accepted and event["type"] == YANK_EVENT and event["actor"] == "scheduler"
    changed = [d for d in event["delta"] if d["key"].startswith(REGISTRY_PREFIX)]
    for d in event["delta"]:
        if d["key"].startswith(SCHEDULED_PREFIX) and d["key"] not in baseline_plans:
            yield f"seq {seq}: {event['type']} created scheduled yank {d['key']}"
    if accepted and event["type"] == YANK_EVENT and len(changed) != 1:
        yield f"seq {seq}: {YANK_EVENT} must change exactly one registry document, changed {len(changed)}"
    for change in changed:
        model = change["key"][len(REGISTRY_PREFIX):]
        plan_key = SCHEDULED_PREFIX + model
        fired = any(d["key"] == plan_key for d in event["delta"])
        if not (is_yank and fired and plan_key in baseline_plans):
            yield f"seq {seq}: {event['type']} changed registry document {change['key']}"
            continue
        plan = baseline_plans[plan_key]
        if not isinstance(change["before"], dict):
            yield f"seq {seq}: yank of {model} without a registry document"
            continue
        expected, yanked, new = _yanked(change["before"], plan, step.ts)
        if change["after"] != expected:
            yield f"seq {seq}: yank of {model} does not match its scheduled plan"
        payload = event["payload"]
        if (payload.get("model"), payload.get("yanked"), payload.get("published"), payload.get("reason"),
                payload.get("actor")) != (model, ref(yanked), ref(new), plan["reason"], plan["actor"]):
            yield f"seq {seq}: {YANK_EVENT} payload does not match the yank"


def validate(trace: Trace):
    baseline = trace.initial_state
    for key in sorted(k for k in baseline if k.startswith(REGISTRY_PREFIX)):
        yield from _baseline_doc(key[len(REGISTRY_PREFIX):], baseline[key])
    plans = {k: baseline[k] for k in sorted(baseline) if k.startswith(SCHEDULED_PREFIX)}
    for key, plan in plans.items():
        yield from _baseline_plan(key, plan, baseline)
        yield from scheduled_event_problems(trace, key, YANK_EVENT)
    for step in trace.steps:
        yield from _step_problems(step, plans)


VALIDATOR = Validator("registry", validate)
