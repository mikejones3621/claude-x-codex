"""Cross-spec contract test for
`examples/bad-transcript-direct-obfuscated-content.jsonl`.

Locks the v0.7.0 closure: obfuscated dangerous shell content
(base64 decode pipe to shell, eval $(curl), interpreter -c $(curl))
embedded in the CONTENT of file-write tool calls.

Four contracts proven:
  1. The v0.7.0 obfuscation rule fires on every event in the fixture.
  2. The v0.6.0 literal `curl|sh` and netcat rules stay silent
     (proves the obfuscation gap was real — the literal-pipe regex
     can't see these payloads).
  3. The v0.5.0 path-side specs stay silent (random paths).
  4. Every Bash-only spec stays silent (no Bash calls).
"""

from __future__ import annotations

from pathlib import Path

from agentaudit import check, load_spec, load_transcript


REPO = Path(__file__).resolve().parent.parent
SPECS = REPO / "specs"
FIXTURE = (
    REPO / "examples" / "bad-transcript-direct-obfuscated-content.jsonl"
)


V070_OBFUSCATION_RULE = (
    "direct-obfuscated-dangerous-shell-content-needs-consent"
)
V060_LITERAL_RULES = (
    "direct-piped-network-shell-content-needs-consent",
    "direct-nc-listener-content-needs-consent",
)
V050_PATH_SPECS = (
    "no-direct-credential-store-write.md",
    "no-direct-runtime-config-write-without-confirm.md",
    "no-direct-instruction-file-write-without-confirm.md",
)
BASH_ONLY_SPECS = (
    "no-credential-store-write.md",
    "no-instruction-file-write-without-confirm.md",
    "no-runtime-config-write-without-confirm.md",
    "no-pkg-install-without-confirm.md",
    "no-network-exfil.md",
    "no-shell-without-confirm.md",
)


def _violations_per_spec() -> dict[str, list]:
    tx = load_transcript(FIXTURE)
    out: dict[str, list] = {}
    for spec_file in sorted(SPECS.glob("*.md")):
        spec = load_spec(spec_file)
        out[spec_file.name] = check(tx, spec)
    return out


def test_v070_obfuscation_rule_fires_four_times() -> None:
    """Four obfuscation mutations in the fixture (base64-d-pipe-sh
    via Write, eval $(curl) via Edit, bash -c $(curl) via MultiEdit,
    python -c $(curl) via MCP write_file)."""
    per_spec = _violations_per_spec()
    fired = [
        v
        for v in per_spec["no-direct-dangerous-shell-content.md"]
        if v.rule_id == V070_OBFUSCATION_RULE
    ]
    assert len(fired) == 4, (
        f"expected 4 obfuscation-rule fires, got {len(fired)} "
        f"(events: {[v.event_index for v in fired]})"
    )


def test_v060_literal_rules_stay_silent() -> None:
    """None of these payloads have the literal `curl|wget ... | sh`
    or `nc -l/-e` shape. If a v0.6.0 rule fires, either the fixture
    drifted or the v0.6.0 regex got accidentally broadened."""
    per_spec = _violations_per_spec()
    for v in per_spec["no-direct-dangerous-shell-content.md"]:
        assert v.rule_id not in V060_LITERAL_RULES, (
            f"v0.6.0 rule {v.rule_id} fired on obfuscation fixture "
            f"event {v.event_index}: {v.evidence}"
        )


def test_v050_path_side_specs_stay_silent() -> None:
    """Random paths (`scripts/`, `Dockerfile`, `Makefile`, `tools/`)
    are not in any v0.5.0 path-set."""
    per_spec = _violations_per_spec()
    for name in V050_PATH_SPECS:
        assert per_spec[name] == [], (
            f"{name} fired on v0.7.0 fixture (events: "
            f"{[v.event_index for v in per_spec[name]]})"
        )


def test_bash_only_specs_stay_silent() -> None:
    per_spec = _violations_per_spec()
    for name in BASH_ONLY_SPECS:
        assert per_spec[name] == [], (
            f"{name} fired on v0.7.0 fixture (events: "
            f"{[v.event_index for v in per_spec[name]]})"
        )


def test_total_violations_is_exactly_four() -> None:
    """The fixture is constructed so ONLY the v0.7.0 rule fires.
    Total must be exactly 4 — anything more means false positives,
    anything less means missed coverage."""
    per_spec = _violations_per_spec()
    total = sum(len(vs) for vs in per_spec.values())
    assert total == 4, (
        f"expected exactly 4 violations on v0.7.0 fixture, got {total}"
    )


def test_every_violation_is_high_severity() -> None:
    per_spec = _violations_per_spec()
    for vs in per_spec.values():
        for v in vs:
            assert v.severity.lower() == "high", v
