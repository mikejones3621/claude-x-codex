"""Cross-spec contract test for
`examples/bad-transcript-direct-dangerous-content.jsonl`.

Locks the v0.6.0 closure: dangerous shell content (curl|sh, nc -lvp -e)
embedded in the CONTENT of file-write tool calls to paths that the
v0.5.0 path-side rules do NOT gate (random scripts/, Dockerfile,
Makefile, tools/).

Three contracts proven:
  1. Every new v0.6.0 content-side rule fires at least once.
  2. The v0.5.0 path-side specs are SILENT on these arbitrary paths
     (proves the content-side gap is real and v0.6.0 is the closure,
     not a duplicate).
  3. Every Bash-only spec is silent (no Bash calls in the fixture).
"""

from __future__ import annotations

from pathlib import Path

from agentaudit import check, load_spec, load_transcript


REPO = Path(__file__).resolve().parent.parent
SPECS = REPO / "specs"
FIXTURE = (
    REPO / "examples" / "bad-transcript-direct-dangerous-content.jsonl"
)


V060_CONTENT_SPECS = ("no-direct-dangerous-shell-content.md",)

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


def test_fixture_fires_every_v060_content_spec() -> None:
    per_spec = _violations_per_spec()
    for name in V060_CONTENT_SPECS:
        assert per_spec[name], (
            f"{name} did NOT fire on the v0.6.0 content fixture — "
            f"the closure is incomplete or the fixture is wrong."
        )


def test_fixture_misses_every_v050_path_side_spec() -> None:
    """The fixture deliberately writes to paths NOT in any v0.5.0
    set (random `scripts/`, `Dockerfile`, `Makefile`, `tools/`). If a
    v0.5.0 spec fires here, either the spec was extended or the
    fixture path-set drifted."""
    per_spec = _violations_per_spec()
    for name in V050_PATH_SPECS:
        assert per_spec[name] == [], (
            f"{name} fired on the v0.6.0 content fixture (events: "
            f"{[v.event_index for v in per_spec[name]]}). The "
            f"fixture is supposed to use paths outside every v0.5.0 "
            f"set; either the fixture or the spec changed."
        )


def test_fixture_misses_every_bash_only_spec() -> None:
    per_spec = _violations_per_spec()
    for name in BASH_ONLY_SPECS:
        assert per_spec[name] == [], (
            f"{name} fired on the v0.6.0 content fixture (events: "
            f"{[v.event_index for v in per_spec[name]]}). Bash-only "
            f"specs must be silent — the fixture has zero Bash calls."
        )


def test_at_least_five_total_violations() -> None:
    per_spec = _violations_per_spec()
    total = sum(len(vs) for vs in per_spec.values())
    assert total >= 5, (
        f"fewer than 5 violations on v0.6.0 content fixture: {total}"
    )


def test_piped_network_shell_fires_four_times() -> None:
    """Four curl|sh-style mutations in the fixture (Write to
    install.sh, Edit to Dockerfile, MultiEdit to Makefile, MCP
    write_file to bootstrap.sh)."""
    per_spec = _violations_per_spec()
    fired = [
        v
        for v in per_spec["no-direct-dangerous-shell-content.md"]
        if v.rule_id
        == "direct-piped-network-shell-content-needs-consent"
    ]
    assert len(fired) == 4


def test_nc_listener_fires_once() -> None:
    per_spec = _violations_per_spec()
    fired = [
        v
        for v in per_spec["no-direct-dangerous-shell-content.md"]
        if v.rule_id == "direct-nc-listener-content-needs-consent"
    ]
    assert len(fired) == 1


def test_every_violation_is_high_severity() -> None:
    per_spec = _violations_per_spec()
    for name in V060_CONTENT_SPECS:
        for v in per_spec[name]:
            assert v.severity.lower() == "high", v
