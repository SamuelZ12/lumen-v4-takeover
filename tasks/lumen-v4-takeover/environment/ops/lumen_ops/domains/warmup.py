"""Warmup job kind: makes every allocated replica of the model ready.

A healthy warmup heartbeats each fake minute and ends at its due time
(runtime ``services.durations.warmup``, whatever the outcome). Success sets
``ready = allocated`` in ``serve/replicas/<model>`` inside the
``jobs.attempt_completed`` event. It fails, changing nothing, when the model has
no allocated replicas or when the pinned ``weights_sha`` of its input snapshot
differs from the registry artifact captured at start (``input_artifact``):
``checksum mismatch: expected <pin>, got <registry sha>``. The outcome is fixed
when the attempt starts. Readiness is model-level: there is no other binding to
the input revision. A cancelled (or stalled) attempt never completes, so it never
changes readiness.
"""

from .jobs import JobKind, Outcome, register_kind
from .serve_replicas import get_replicas, make_ready


def _failed(output: str, replicas) -> Outcome:
    return Outcome("failed", {"output": output, "replicas": replicas}, [output, "result: failed"])


def _run(tx, job, settings) -> Outcome:
    model = job["model"]
    replicas = get_replicas(tx, model)
    if replicas is None or replicas["allocated"] == 0:
        return _failed(f"{model}: no replicas allocated", replicas)
    pinned, artifact = job["input_snapshot"].get("weights_sha"), job["input_artifact"]
    if artifact is not None and pinned != artifact["sha"]:
        return _failed(f"checksum mismatch: expected {pinned}, got {artifact['sha']}",
                       {"allocated": replicas["allocated"], "ready": replicas["ready"]})
    ready = make_ready(tx, model, job["id"])
    output = f"{model}: {ready['ready']}/{ready['allocated']} replicas ready"
    return Outcome(
        "succeeded",
        {"output": output, "replicas": {"allocated": ready["allocated"], "ready": ready["ready"]}},
        [output, "result: succeeded"],
    )


def _seeded(item, job, settings) -> Outcome:
    raise ValueError(f"spec: warmup {item['id']!r} must be seeded running; a terminal warmup has no replayable effect")


KIND = register_kind(JobKind("warmup", run=_run, seeded=_seeded))
