"""Auto-discovery of checks and replay validators.

- ``lumen_verify/checks/<name>.py`` defines ``CHECK = Check(name, evaluate)``.
- ``lumen_verify/validators/<domain>.py`` defines ``VALIDATOR = Validator(name, validate)``.

Adding a check or validator is adding one file.
"""

import importlib
import pkgutil
from types import ModuleType
from typing import Iterable

from .trace import Check, Validator


def _modules(package: ModuleType) -> list[ModuleType]:
    return [
        importlib.import_module(f"{package.__name__}.{info.name}")
        for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda i: i.name)
        if not info.name.startswith("_")
    ]


def discover_checks(extra: Iterable[Check] = ()) -> dict[str, Check]:
    from . import checks

    found: dict[str, Check] = {}
    for check in [m.CHECK for m in _modules(checks)] + list(extra):
        if check.name in found:
            raise ValueError(f"duplicate check {check.name!r}")
        found[check.name] = check
    return found


def discover_validators(extra: Iterable[Validator] = ()) -> list[Validator]:
    from . import validators

    return [m.VALIDATOR for m in _modules(validators)] + list(extra)
