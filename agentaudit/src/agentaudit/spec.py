"""Behavior spec format.

A spec is a Markdown document describing rules an agent must follow.
Each rule is introduced by an H2 (`## rule-id: human-readable name`)
followed by a fenced code block tagged `agentaudit` containing key/value
pairs in TOML-ish format. Rule bodies after the code block are treated
as human-readable rationale and surfaced in violation reports.

Example:

    ## no-secret-leak: never print API keys to outputs

    ```agentaudit
    type = forbid_pattern
    severity = high
    pattern = "(?i)(?:api[_-]?key|secret|token)\\s*[:=]\\s*['\"]?[A-Za-z0-9_\\-]{16,}"
    scope = "tool_result,message"
    ```

    Outputs that include API keys or comparable credentials must be
    redacted before being shown to the user or written to disk.

Supported `type` values are described in `agentaudit.rules`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_RULE_HEADER = re.compile(r"^##\s+([a-z0-9][a-z0-9_\-]*)\s*:\s*(.+?)\s*$", re.MULTILINE)
_FENCE = re.compile(r"```agentaudit\s*\n(.*?)\n```", re.DOTALL)


@dataclass
class Rule:
    id: str
    name: str
    type: str
    severity: str = "medium"
    params: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""

    @property
    def severity_rank(self) -> int:
        return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(
            self.severity.lower(), 2
        )


@dataclass
class Spec:
    name: str
    rules: list[Rule] = field(default_factory=list)
    source: str | None = None


def _parse_kv_block(text: str) -> dict[str, Any]:
    """Tiny TOML-ish parser. Accepts key = value, with quoted strings,
    bare ints, floats, true/false, and lists [a, b, c]."""
    out: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"spec: expected `key = value`, got: {raw_line!r}")
        key, _, value = line.partition("=")
        out[key.strip()] = _parse_value(value.strip())
    return out


def _parse_value(s: str) -> Any:
    if not s:
        return ""
    if s[0] in ("'", '"'):
        # quoted string; allow simple backslash escapes
        quote = s[0]
        if not s.endswith(quote) or len(s) < 2:
            raise ValueError(f"spec: unterminated string: {s!r}")
        inner = s[1:-1]
        return bytes(inner, "utf-8").decode("unicode_escape")
    if s.startswith("[") and s.endswith("]"):
        body = s[1:-1].strip()
        if not body:
            return []
        return [_parse_value(part.strip()) for part in _split_top_level(body, ",")]
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s  # bare token, treat as string


def _split_top_level(s: str, sep: str) -> list[str]:
    out, buf, depth, in_quote = [], [], 0, ""
    for ch in s:
        if in_quote:
            buf.append(ch)
            if ch == in_quote:
                in_quote = ""
            continue
        if ch in ("'", '"'):
            in_quote = ch
            buf.append(ch)
            continue
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return out


def parse_spec(text: str, *, name: str = "spec") -> Spec:
    """Parse a Markdown spec into a Spec object."""
    rules: list[Rule] = []
    headers = list(_RULE_HEADER.finditer(text))
    for i, h in enumerate(headers):
        rule_id = h.group(1)
        rule_name = h.group(2).strip()
        section_start = h.end()
        section_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        section = text[section_start:section_end]
        fence = _FENCE.search(section)
        if not fence:
            raise ValueError(
                f"spec: rule {rule_id!r} is missing an `agentaudit` code block"
            )
        params = _parse_kv_block(fence.group(1))
        rule_type = params.pop("type", None)
        if not rule_type:
            raise ValueError(f"spec: rule {rule_id!r} is missing `type`")
        severity = str(params.pop("severity", "medium"))
        rationale = section[fence.end():].strip()
        rules.append(
            Rule(
                id=rule_id,
                name=rule_name,
                type=str(rule_type),
                severity=severity,
                params=params,
                rationale=rationale,
            )
        )
    return Spec(name=name, rules=rules)


def load_spec(path: str | Path) -> Spec:
    p = Path(path)
    spec = parse_spec(p.read_text(encoding="utf-8"), name=p.stem)
    spec.source = str(p)
    return spec
