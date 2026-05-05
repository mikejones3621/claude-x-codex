"""Judge-backed rule registration.

The actual judge callable is injected at runtime through `agentaudit.check`.
This module only registers the `judge` rule type so it appears in discovery
surfaces such as `agentaudit list-rules`.
"""

from __future__ import annotations

from typing import Iterable

from agentaudit.checker import Violation
from agentaudit.rules import register
from agentaudit.schema import Transcript
from agentaudit.spec import Rule


def _unsupported(rule: Rule, transcript: Transcript) -> Iterable[Violation]:
    raise ValueError(
        "judge rules require check(..., judge=...) or check_rule(..., judge=...)"
    )
    yield rule, transcript  # pragma: no cover


register("judge", _unsupported)
