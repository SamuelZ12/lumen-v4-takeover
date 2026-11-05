"""Declarative CLI command registry.

Each module in :mod:`lumen_cli.commands` may define:

- ``PROGRAMS``: ``{"clock": "help text"}`` for top-level executables it introduces;
- ``GROUPS``: ``{("serve", "config"): "help text"}`` for intermediate command groups;
- ``COMMANDS``: a list of :class:`Command` leaves.

Several modules may add leaves under the same program or group, so domains
(config, traffic, replicas, ...) extend ``serve`` without editing each other.
"""

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class Arg:
    """A positional (``name``) or option (``--name``) argument passed through to the API."""

    name: str
    help: str
    choices: tuple[str, ...] | None = None
    required: bool = False
    flag: bool = False  # store_true option
    metavar: str | None = None

    @property
    def is_option(self) -> bool:
        return self.name.startswith("--")

    @property
    def dest(self) -> str:
        return self.name.lstrip("-").replace("-", "_")


@dataclass(frozen=True)
class Command:
    path: tuple[str, ...]  # e.g. ("clock", "wait")
    api: str  # sidecar command name, e.g. "clock.wait"
    help: str
    args: tuple[Arg, ...] = ()
    description: str | None = None
    render: Callable[[dict[str, Any]], str] | None = None
    # Client-side step from parsed args to API args, for work that must happen
    # in the main container (e.g. reading a local file). Default: pass through.
    prepare: Callable[[dict[str, Any]], dict[str, Any]] | None = None


@dataclass
class Catalog:
    programs: dict[str, str] = field(default_factory=dict)
    groups: dict[tuple[str, ...], str] = field(default_factory=dict)
    commands: list[Command] = field(default_factory=list)

    def add_module(self, module: Any) -> None:
        for name, help_text in getattr(module, "PROGRAMS", {}).items():
            if name in self.programs:
                raise ValueError(f"program {name!r} declared twice")
            self.programs[name] = help_text
        self.groups.update(getattr(module, "GROUPS", {}))
        self.commands.extend(getattr(module, "COMMANDS", []))

    def for_program(self, program: str) -> list[Command]:
        return [c for c in self.commands if c.path[0] == program]


def discover(extra_modules: Iterable[Any] = ()) -> Catalog:
    from . import commands

    catalog = Catalog()
    for info in pkgutil.iter_modules(commands.__path__):
        if not info.name.startswith("_"):
            catalog.add_module(importlib.import_module(f"{commands.__name__}.{info.name}"))
    for module in extra_modules:
        catalog.add_module(module)
    return catalog
