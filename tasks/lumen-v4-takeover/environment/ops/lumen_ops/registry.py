"""Domain registry. Each module in :mod:`lumen_ops.domains` defines ``DOMAIN``, or only
``KIND`` when all it adds is a job kind (registered with ``jobs.register_kind`` on import).

Adding a domain (config, traffic, jobs, approvals, ...) means adding one file;
nothing central is edited. A domain contributes:

- seeders: ``fn(tx, spec)`` writing its initial state keys (no events);
- commands: ``fn(tx, args) -> dict`` exposed on the public API;
- boundary sources: ``fn(tx) -> Boundary | None`` giving its earliest
  scheduled transition, processed by :func:`lumen_ops.scheduler.advance`;
- event summaries: ``fn(event) -> str``, a neutral one-line description of a
  scheduled event type, listed by ``clock wait`` / ``jobs wait``;
- quiet event types (``quiet_events``): scheduled events that fire and are
  recorded like any other but are never listed by ``clock wait`` / ``jobs wait``.
"""

import importlib
import pkgutil
from dataclasses import dataclass, field
from datetime import datetime
from types import ModuleType
from typing import Any, Callable, Iterable

Handler = Callable[[Any, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class Boundary:
    """One scheduled transition. Ties at ``ts`` break on ``order`` (stable creation order)."""

    ts: datetime
    order: tuple
    fire: Callable[[Any], None]


@dataclass(frozen=True)
class Command:
    name: str
    handler: Handler
    mutating: bool
    resource: str


@dataclass
class Domain:
    name: str
    seed_order: int = 100
    seeders: list[Callable] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)
    boundary_sources: list[Callable] = field(default_factory=list)
    summaries: dict[str, Callable[[dict[str, Any]], str]] = field(default_factory=dict)
    quiet_events: frozenset[str] | set[str] = frozenset()

    def seed(self, fn: Callable) -> Callable:
        self.seeders.append(fn)
        return fn

    def command(self, name: str, *, mutating: bool, resource: str) -> Callable[[Handler], Handler]:
        def decorate(fn: Handler) -> Handler:
            self.commands.append(Command(name, fn, mutating, resource))
            return fn

        return decorate

    def boundary_source(self, fn: Callable) -> Callable:
        self.boundary_sources.append(fn)
        return fn

    def summary(self, event_type: str) -> Callable:
        def decorate(fn: Callable[[dict[str, Any]], str]) -> Callable:
            self.summaries[event_type] = fn
            return fn

        return decorate


class Registry:
    def __init__(self, domains: Iterable[Domain]):
        self.domains = sorted(domains, key=lambda d: (d.seed_order, d.name))
        self.commands: dict[str, Command] = {}
        for domain in self.domains:
            for command in domain.commands:
                if command.name in self.commands:
                    raise ValueError(f"duplicate command {command.name!r}")
                self.commands[command.name] = command
        self.summaries: dict[str, Callable] = {}
        for domain in self.domains:
            for event_type, fn in domain.summaries.items():
                if event_type in self.summaries:
                    raise ValueError(f"duplicate summary for {event_type!r}")
                self.summaries[event_type] = fn
        self.quiet_events = frozenset().union(*(domain.quiet_events for domain in self.domains))

    @property
    def seeders(self) -> list[Callable]:
        return [fn for domain in self.domains for fn in domain.seeders]

    @property
    def boundary_sources(self) -> list[Callable]:
        return [fn for domain in self.domains for fn in domain.boundary_sources]

    def summarize(self, event: dict[str, Any]) -> str | None:
        fn = self.summaries.get(event["type"])
        return None if fn is None else fn(event)


def _domain_modules(package: ModuleType) -> list[ModuleType]:
    return [
        importlib.import_module(f"{package.__name__}.{info.name}")
        for info in pkgutil.iter_modules(package.__path__)
        if not info.name.startswith("_")
    ]


def discover(extra: Iterable[Domain] = ()) -> Registry:
    from . import domains

    found = []
    for module in _domain_modules(domains):
        if hasattr(module, "DOMAIN"):
            found.append(module.DOMAIN)
        elif not hasattr(module, "KIND"):
            raise ValueError(f"{module.__name__} defines neither DOMAIN nor KIND")
    return Registry([*found, *extra])
