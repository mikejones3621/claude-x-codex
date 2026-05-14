"""Cross-spec contract test for
`examples/bad-transcript-direct-encoded-content.jsonl`.

Locks the v0.8.0 closure: hex/octal/xxd/gzip-encoded dangerous shell
payloads embedded in the CONTENT of file-write tool calls. Four
contracts proven:

  1. The v0.8.0 encoded rule fires on every event in the fixture.
  2. The v0.6.0 literal-pipe + nc rules stay silent (none of these
     payloads match the literal `curl|sh` or `nc -l/-e` shape).
  3. The v0.7.0 obfuscation rule stays silent (these payloads use a
     different encoding family — neither base64+pipe, eval-$(curl),
     nor interpreter -c $(curl)).
  4. The v0.5.0 path-side specs + every Bash-only spec stay silent.
"""

from __future__ import annotations

from pathlib import Path

from agentaudit import check, load_spec, load_transcript


REPO = Path(__file__).resolve().parent.parent
SPECS = REPO / "specs"
FIXTURE = (
    REPO / "examples" / "bad-transcript-direct-encoded-content.jsonl"
)


V080_ENCODED_RULE = (
    "direct-encoded-dangerous-shell-content-needs-consent"
)
EARLIER_DANGEROUS_RULES = (
    "direct-piped-network-shell-content-needs-consent",
    "direct-nc-listener-content-needs-consent",
    "direct-obfuscated-dangerous-shell-content-needs-consent",
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


def test_v080_encoded_rule_fires_four_times() -> None:
    per_spec = _violations_per_spec()
    fired = [
        v
        for v in per_spec["no-direct-dangerous-shell-content.md"]
        if v.rule_id == V080_ENCODED_RULE
    ]
    assert len(fired) == 4, (
        f"expected 4 encoded-rule fires, got {len(fired)} "
        f"(events: {[v.event_index for v in fired]})"
    )


def test_earlier_dangerous_rules_stay_silent() -> None:
    """The fixture deliberately uses encoding patterns the v0.6.0 +
    v0.7.0 rules cannot see. If any earlier rule fires, the fixture
    or one of those rules drifted."""
    per_spec = _violations_per_spec()
    for v in per_spec["no-direct-dangerous-shell-content.md"]:
        assert v.rule_id not in EARLIER_DANGEROUS_RULES, (
            f"earlier rule {v.rule_id} fired on v0.8.0 fixture "
            f"event {v.event_index}: {v.evidence}"
        )


def test_v050_path_side_specs_stay_silent() -> None:
    per_spec = _violations_per_spec()
    for name in V050_PATH_SPECS:
        assert per_spec[name] == [], (
            f"{name} fired on v0.8.0 fixture (events: "
            f"{[v.event_index for v in per_spec[name]]})"
        )


def test_bash_only_specs_stay_silent() -> None:
    per_spec = _violations_per_spec()
    for name in BASH_ONLY_SPECS:
        assert per_spec[name] == [], (
            f"{name} fired on v0.8.0 fixture (events: "
            f"{[v.event_index for v in per_spec[name]]})"
        )


def test_total_violations_is_exactly_four() -> None:
    per_spec = _violations_per_spec()
    total = sum(len(vs) for vs in per_spec.values())
    assert total == 4, (
        f"expected exactly 4 violations on v0.8.0 fixture, got {total}"
    )


def test_every_violation_is_high_severity() -> None:
    per_spec = _violations_per_spec()
    for vs in per_spec.values():
        for v in vs:
            assert v.severity.lower() == "high", v
