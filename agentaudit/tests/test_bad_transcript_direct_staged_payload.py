"""Cross-spec contract test for
`examples/bad-transcript-direct-staged-payload.jsonl`.

Locks the v0.9.0 slice-2 proof:

1. The staged-payload rule fires on every staged chain in the fixture.
2. The earlier direct dangerous-content rules stay silent because the
   file-write events contain only encoded blobs, not single-event shell
   payloads.
3. The v0.5.0 direct path-side specs stay silent because the paths are
   ordinary temp/scripts paths, not credential/config/instruction files.
4. The Bash-only specs stay silent because the consume step uses local
   decode/source flows only and never hits the older dangerous Bash
   surfaces like `curl`, `wget`, or destructive shell.
"""

from __future__ import annotations

from pathlib import Path

from agentaudit import check, load_spec, load_transcript

REPO = Path(__file__).resolve().parent.parent
SPECS = REPO / "src" / "agentaudit" / "specs"
FIXTURE = REPO / "examples" / "bad-transcript-direct-staged-payload.jsonl"


V090_STAGED_RULE = "staged-payload-needs-consent"
EARLIER_DIRECT_RULES = (
    "direct-piped-network-shell-content-needs-consent",
    "direct-nc-listener-content-needs-consent",
    "direct-obfuscated-dangerous-shell-content-needs-consent",
    "direct-encoded-dangerous-shell-content-needs-consent",
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
        if any(rule.type == "judge" for rule in spec.rules):
            continue
        out[spec_file.name] = check(tx, spec)
    return out


def test_v090_staged_rule_fires_three_times() -> None:
    per_spec = _violations_per_spec()
    fired = [
        v
        for v in per_spec["no-multi-stage-staged-payload.md"]
        if v.rule_id == V090_STAGED_RULE
    ]
    assert len(fired) == 3, (
        f"expected 3 staged-rule fires, got {len(fired)} "
        f"(events: {[v.event_index for v in fired]})"
    )


def test_earlier_direct_dangerous_rules_stay_silent() -> None:
    per_spec = _violations_per_spec()
    for v in per_spec["no-direct-dangerous-shell-content.md"]:
        assert v.rule_id not in EARLIER_DIRECT_RULES, (
            f"earlier direct rule {v.rule_id} fired on staged fixture "
            f"event {v.event_index}: {v.evidence}"
        )


def test_v050_path_side_specs_stay_silent() -> None:
    per_spec = _violations_per_spec()
    for name in V050_PATH_SPECS:
        assert per_spec[name] == [], (
            f"{name} fired on v0.9.0 fixture (events: "
            f"{[v.event_index for v in per_spec[name]]})"
        )


def test_bash_only_specs_stay_silent() -> None:
    per_spec = _violations_per_spec()
    for name in BASH_ONLY_SPECS:
        assert per_spec[name] == [], (
            f"{name} fired on v0.9.0 fixture (events: "
            f"{[v.event_index for v in per_spec[name]]})"
        )


def test_total_violations_is_exactly_three() -> None:
    per_spec = _violations_per_spec()
    total = sum(len(vs) for vs in per_spec.values())
    assert total == 3, (
        f"expected exactly 3 violations on v0.9.0 staged fixture, got {total}"
    )


def test_every_violation_is_high_severity() -> None:
    per_spec = _violations_per_spec()
    for vs in per_spec.values():
        for v in vs:
            assert v.severity.lower() == "high", v
