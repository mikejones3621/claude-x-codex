"""Adapters convert lab-specific transcript formats into the canonical schema."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from agentaudit.schema import Transcript

Loader = Callable[[Path], Transcript]

_ADAPTERS: dict[str, Loader] = {}


def register(name: str, loader: Loader) -> None:
    _ADAPTERS[name] = loader


def list_adapters() -> list[str]:
    return sorted(_ADAPTERS)


def load_with_adapter(name: str, path: str | Path) -> Transcript:
    loader = _ADAPTERS.get(name)
    if not loader:
        raise ValueError(
            f"unknown adapter {name!r}; known: {list_adapters()}"
        )
    return loader(Path(path))


from agentaudit.adapters import claude_code as _cc  # noqa: E402,F401
from agentaudit.adapters import openai_agents as _oa  # noqa: E402,F401
from agentaudit.adapters import generic as _gn  # noqa: E402,F401
