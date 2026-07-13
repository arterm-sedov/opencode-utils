"""Agent registry — auto-discovers adapter modules in this package."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from .base import AgentAdapter  # noqa: F401 — re-export for convenience

_registry: dict[str, type[AgentAdapter]] = {}


def _discover() -> None:
    """Import every *.py sibling so their AgentAdapter subclasses register."""
    package_dir = Path(__file__).parent
    for finder, name, _ispkg in pkgutil.iter_modules([str(package_dir)]):
        if name in ("base", "detector", "__init__"):
            continue
        importlib.import_module(f".{name}", package=__name__)


def get_adapter(name: str) -> type[AgentAdapter] | None:
    """Return the adapter class for *name*, or None if not found."""
    _discover()
    return _registry.get(name)


def all_adapters() -> dict[str, type[AgentAdapter]]:
    """Return a copy of the full adapter registry."""
    _discover()
    return dict(_registry)


def register(adapter_cls: type[AgentAdapter]) -> None:
    """Register an adapter class (called by subclasses at import time)."""
    _registry[adapter_cls.name] = adapter_cls
