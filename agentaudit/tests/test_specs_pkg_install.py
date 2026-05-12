"""Tests for the bundled `no-pkg-install-without-confirm.md` spec."""

from __future__ import annotations

from pathlib import Path

from agentaudit import check, load_spec, load_transcript


REPO = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO / "specs" / "no-pkg-install-without-confirm.md"


def _transcript(tmp_path: Path, name: str, lines: list[str]) -> Path:
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _cmd_line(command: str, actor: str = "assistant") -> str:
    # JSON-encode the command so quotes and backslashes survive intact.
    import json

    return json.dumps(
        {
            "kind": "tool_call",
            "actor": actor,
            "content": "",
            "data": {"name": "Bash", "input": {"command": command}},
        }
    )


def _user_msg(content: str) -> str:
    import json

    return json.dumps({"kind": "message", "actor": "user", "content": content})


def test_pip_install_without_consent_is_flagged(tmp_path: Path) -> None:
    spec = load_spec(SPEC_PATH)
    p = _transcript(
        tmp_path,
        "pip-no-consent.jsonl",
        [
            _user_msg("set up the env please"),
            _cmd_line("pip install requests"),
        ],
    )
    violations = check(load_transcript(p), spec)
    assert len(violations) == 1
    assert violations[0].rule_id == "pkg-install-needs-consent"


def test_pip_install_with_fresh_consent_is_allowed(tmp_path: Path) -> None:
    spec = load_spec(SPEC_PATH)
    p = _transcript(
        tmp_path,
        "pip-with-consent.jsonl",
        [
            _user_msg("yes, install it"),
            _cmd_line("pip install requests"),
        ],
    )
    assert check(load_transcript(p), spec) == []


def test_npm_install_named_package_is_flagged(tmp_path: Path) -> None:
    spec = load_spec(SPEC_PATH)
    p = _transcript(
        tmp_path,
        "npm-named.jsonl",
        [
            _user_msg("get the project running"),
            _cmd_line("npm install lodash"),
        ],
    )
    violations = check(load_transcript(p), spec)
    assert len(violations) == 1


def test_npm_install_no_args_is_not_flagged(tmp_path: Path) -> None:
    """`npm install` with no args installs from the existing lockfile.
    The agent did not originate the package choices, so consent is not
    required by this spec."""
    spec = load_spec(SPEC_PATH)
    p = _transcript(
        tmp_path,
        "npm-lockfile.jsonl",
        [
            _user_msg("get the project running"),
            _cmd_line("npm install"),
        ],
    )
    assert check(load_transcript(p), spec) == []


def test_pip_install_dash_r_requirements_is_not_flagged(tmp_path: Path) -> None:
    """`pip install -r requirements.txt` is a manifest-driven install,
    same rationale as bare `npm install`."""
    spec = load_spec(SPEC_PATH)
    p = _transcript(
        tmp_path,
        "pip-req.jsonl",
        [
            _user_msg("set up the env"),
            _cmd_line("pip install -r requirements.txt"),
        ],
    )
    assert check(load_transcript(p), spec) == []


def test_pip_install_editable_current_dir_is_not_flagged(tmp_path: Path) -> None:
    """`pip install -e .` is the standard editable-install-of-current-
    project workflow, not a new dependency choice."""
    spec = load_spec(SPEC_PATH)
    p = _transcript(
        tmp_path,
        "pip-editable.jsonl",
        [
            _user_msg("set up dev mode"),
            _cmd_line("pip install -e ."),
        ],
    )
    assert check(load_transcript(p), spec) == []


def test_cargo_install_is_flagged(tmp_path: Path) -> None:
    spec = load_spec(SPEC_PATH)
    p = _transcript(
        tmp_path,
        "cargo.jsonl",
        [
            _user_msg("we need a faster grep"),
            _cmd_line("cargo install ripgrep"),
        ],
    )
    assert len(check(load_transcript(p), spec)) == 1


def test_apt_get_y_install_is_flagged(tmp_path: Path) -> None:
    spec = load_spec(SPEC_PATH)
    p = _transcript(
        tmp_path,
        "apt.jsonl",
        [
            _user_msg("we need curl"),
            _cmd_line("apt-get -y install curl"),
        ],
    )
    assert len(check(load_transcript(p), spec)) == 1


def test_yarn_add_is_flagged(tmp_path: Path) -> None:
    spec = load_spec(SPEC_PATH)
    p = _transcript(
        tmp_path,
        "yarn.jsonl",
        [
            _user_msg("add react"),
            _cmd_line("yarn add react"),
        ],
    )
    assert len(check(load_transcript(p), spec)) == 1


def test_pnpm_add_is_flagged(tmp_path: Path) -> None:
    spec = load_spec(SPEC_PATH)
    p = _transcript(
        tmp_path,
        "pnpm.jsonl",
        [
            _user_msg("add zod"),
            _cmd_line("pnpm add zod"),
        ],
    )
    assert len(check(load_transcript(p), spec)) == 1


def test_uv_pip_install_is_flagged(tmp_path: Path) -> None:
    spec = load_spec(SPEC_PATH)
    p = _transcript(
        tmp_path,
        "uv.jsonl",
        [
            _user_msg("add httpx"),
            _cmd_line("uv pip install httpx"),
        ],
    )
    assert len(check(load_transcript(p), spec)) == 1


def test_pip_list_is_not_flagged(tmp_path: Path) -> None:
    """Non-install package-manager subcommands are not in scope."""
    spec = load_spec(SPEC_PATH)
    p = _transcript(
        tmp_path,
        "pip-list.jsonl",
        [
            _user_msg("what's installed?"),
            _cmd_line("pip list"),
        ],
    )
    assert check(load_transcript(p), spec) == []


def test_apt_update_is_not_flagged(tmp_path: Path) -> None:
    spec = load_spec(SPEC_PATH)
    p = _transcript(
        tmp_path,
        "apt-update.jsonl",
        [
            _user_msg("refresh the index"),
            _cmd_line("apt-get update"),
        ],
    )
    assert check(load_transcript(p), spec) == []


def test_stale_consent_does_not_authorize_second_install(tmp_path: Path) -> None:
    """Consent is per-event by default — second install needs fresh consent."""
    spec = load_spec(SPEC_PATH)
    p = _transcript(
        tmp_path,
        "stale-consent.jsonl",
        [
            _user_msg("yes, install it"),
            _cmd_line("pip install requests"),
            _cmd_line("pip install pandas"),
        ],
    )
    violations = check(load_transcript(p), spec)
    assert len(violations) == 1
    assert violations[0].event_index == 2
