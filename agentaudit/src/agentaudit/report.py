"""Render violation lists for humans and machines."""

from __future__ import annotations

import json
from typing import Iterable

from agentaudit.checker import Violation


_SEVERITY_ORDER = ["critical", "high", "medium", "low"]


def render_text(violations: Iterable[Violation], *, color: bool = False) -> str:
    vs = list(violations)
    if not vs:
        return "OK — no violations."
    by_sev: dict[str, list[Violation]] = {s: [] for s in _SEVERITY_ORDER}
    for v in vs:
        by_sev.setdefault(v.severity.lower(), []).append(v)
    lines: list[str] = []
    total = len(vs)
    counts = ", ".join(
        f"{len(by_sev[s])} {s}" for s in _SEVERITY_ORDER if by_sev.get(s)
    )
    lines.append(f"FAIL — {total} violation(s): {counts}")
    lines.append("")
    for sev in _SEVERITY_ORDER:
        bucket = by_sev.get(sev) or []
        for v in bucket:
            tag = f"[{v.severity.upper():>8}]"
            head = f"{tag} {v.rule_id}: {v.rule_name}"
            lines.append(_paint(head, sev) if color else head)
            lines.append(f"           event #{v.event_index} (actor: {v.actor})")
            lines.append(f"           evidence: {v.evidence}")
            if v.details:
                detail = ", ".join(f"{k}={v.details[k]}" for k in sorted(v.details))
                lines.append(f"           details:  {detail}")
            if v.rationale:
                first_para = v.rationale.split("\n\n", 1)[0].strip()
                lines.append(f"           why:      {first_para}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_json(violations: Iterable[Violation]) -> str:
    vs = list(violations)
    counts: dict[str, int] = {}
    for v in vs:
        sev = v.severity.lower()
        counts[sev] = counts.get(sev, 0) + 1
    return json.dumps(
        {
            "ok": not vs,
            "summary": {
                "total": len(vs),
                "by_severity": counts,
            },
            "violations": [v.to_dict() for v in vs],
        },
        indent=2,
        sort_keys=True,
    )


_ANSI = {
    "critical": "\x1b[1;31m",
    "high": "\x1b[31m",
    "medium": "\x1b[33m",
    "low": "\x1b[36m",
}
_RESET = "\x1b[0m"


def _paint(text: str, severity: str) -> str:
    code = _ANSI.get(severity.lower(), "")
    return f"{code}{text}{_RESET}" if code else text
