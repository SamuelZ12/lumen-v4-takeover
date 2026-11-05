"""Serving state as the verifier reads it from replayed snapshots.

Independent of the sidecar: effective config is recomputed from the layer
documents (``base`` then ``prod_override``, last wins) with schema-normalized
values, and its revision is the sha256 of the canonical snapshot JSON.
"""

import math
import re
from typing import Any

from .canonical import sha256_of

V4 = "lumen-v4"
LAYERS = ("base", "prod_override")
BASE_PREFIX = "serve/config/base/"
OVERRIDE_KEY = "serve/config/prod_override"
EFFECTIVE_PREFIX = "serve/effective/"
CONFIG_HISTORY_KEY = "serve/config/history"
TRAFFIC_KEY = "serve/traffic"
TRAFFIC_HISTORY_KEY = "serve/traffic/history"


def _threshold(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"safety_filter_threshold {value!r} is not a number")
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"safety_filter_threshold {value!r} outside 0-1")
    return value


def _region(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"region {value!r} is not a nonempty string")
    return value


def _timeout(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"generation_timeout_s {value!r} is not a positive integer")
    return value


_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


def _weights_sha(value: Any) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"weights_sha {value!r} is not sha256: plus 64 lowercase hex digits")
    return value


SCHEMA = {"safety_filter_threshold": _threshold, "region": _region, "generation_timeout_s": _timeout,
          "weights_sha": _weights_sha}


def models(state: dict[str, Any]) -> list[str]:
    return sorted(key[len(BASE_PREFIX):] for key in state if key.startswith(BASE_PREFIX))


def layer_entries(state: dict[str, Any], layer: str, model: str) -> dict[str, Any]:
    if layer == "base":
        doc = state.get(BASE_PREFIX + model)
        return doc["entries"] if doc else {}
    doc = state.get(OVERRIDE_KEY) or {"entries": {}}
    return doc["entries"].get(model, {})


def effective(state: dict[str, Any], model: str) -> dict[str, Any]:
    """``{"model", "snapshot", "sources", "revision"}``; raises ``ValueError`` on schema-invalid layers."""
    snapshot: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for layer in LAYERS:
        for key, entry in layer_entries(state, layer, model).items():
            if key not in SCHEMA:
                raise ValueError(f"{layer} layer of {model} has unknown key {key!r}")
            snapshot[key] = SCHEMA[key](entry["value"])
            sources[key] = layer
    return {"model": model, "snapshot": snapshot, "sources": sources, "revision": sha256_of(snapshot)}


def share(state: dict[str, Any], model: str) -> int:
    traffic = state.get(TRAFFIC_KEY) or {"shares": {}}
    return traffic["shares"].get(model, 0)
