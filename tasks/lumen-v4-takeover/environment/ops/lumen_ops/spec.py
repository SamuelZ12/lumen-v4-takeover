"""Load the sanitized spec file (``spec.yaml``) that seeds the sidecar."""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .timeutil import format_ts, parse_offset, parse_ts

TOP_LEVEL_SECTIONS = ("clock", "services", "patch", "policy", "handoff", "expected")


@dataclass(frozen=True)
class Spec:
    data: dict[str, Any]
    sha256: str

    @property
    def clock_start(self) -> datetime:
        return parse_ts(self.data["clock"]["start"])

    def at(self, value: str) -> str:
        """Resolve an absolute or start-relative (``-5h20m``) time to a timestamp string."""
        if value[:1] in "+-":
            return format_ts(self.clock_start + parse_offset(value))
        return format_ts(parse_ts(value))


def load_spec(path: str | Path) -> Spec:
    raw = Path(path).read_bytes()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: spec must be a mapping")
    missing = [name for name in TOP_LEVEL_SECTIONS if name not in data]
    if missing:
        raise ValueError(f"{path}: missing spec sections {missing}")
    parse_ts(data["clock"]["start"])
    return Spec(data=data, sha256=hashlib.sha256(raw).hexdigest())
