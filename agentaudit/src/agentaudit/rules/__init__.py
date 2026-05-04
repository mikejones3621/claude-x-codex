"""Built-in rule evaluators.

A rule evaluator is a function `(rule, transcript) -> Iterable[Violation]`.
Evaluators are registered by `type` string. Users can add their own via
`agentaudit.rules.register`.
"""

from __future__ import annotations

from typing import Callable, Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from agentaudit.checker import Violation
    from agentaudit.schema import Transcript
    from agentaudit.spec import Rule


Evaluator = Callable[["Rule", "Transcript"], Iterable["Violation"]]

_REGISTRY: dict[str, Evaluator] = {}
_BUILTINS_LOADED = False


def register(name: str, evaluator: Evaluator) -> None:
    if name in _REGISTRY:
        raise ValueError(f"rule type already registered: {name!r}")
    _REGISTRY[name] = evaluator


def _ensure_builtins() -> None:
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    _BUILTINS_LOADED = True
    from agentaudit.rules import deterministic as _det  # noqa: F401


def get(name: str) -> Evaluator | None:
    _ensure_builtins()
    return _REGISTRY.get(name)


def known_types() -> list[str]:
    _ensure_builtins()
    return sorted(_REGISTRY)
