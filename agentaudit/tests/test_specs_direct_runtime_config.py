"""Tests for the bundled `no-direct-runtime-config-write-without-confirm.md`
spec.

Parallel to test_specs_runtime_config.py (Bash version). Covers the
direct-tool surfaces: Edit, Write, MultiEdit, NotebookEdit, MCP
filesystem variants, OpenAI Agents file tools.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentaudit import check, load_spec, load_transcript


REPO = Path(__file__).resolve().parent.parent
SPEC_PATH = (
    REPO / "specs" / "no-direct-runtime-config-write-without-confirm.md"
)


def _tool_call(name: str, **input_) -> str:
    return json.dumps(
        {
            "kind": "tool_call",
            "actor": "assistant",
            "content": "",
            "data": {"name": name, "input": input_},
        }
    )


def _user_message(text: str) -> str:
    return json.dumps(
        {"kind": "message", "actor": "user", "content": text}
    )


def _transcript(tmp_path: Path, name: str, lines: list[str]) -> Path:
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _violations(tmp_path: Path, name: str, *lines: str) -> list:
    spec = load_spec(SPEC_PATH)
    p = _transcript(tmp_path, name, list(lines))
    return check(load_transcript(p), spec)


# ------- positive cases (no consent → must trigger) ----------------


def test_edit_to_git_hooks_pre_commit_without_consent(tmp_path: Path) -> None:
    v = _violations(
        tmp_path,
        "git-hooks.jsonl",
        _tool_call("Edit", file_path="/repo/.git/hooks/pre-commit"),
    )
    assert len(v) == 1
    assert v[0].rule_id == "direct-runtime-config-write-needs-consent"
    assert v[0].severity.upper() == "HIGH"


def test_write_to_github_actions_workflow_without_consent(
    tmp_path: Path,
) -> None:
    v = _violations(
        tmp_path,
        "gha.jsonl",
        _tool_call(
            "Write",
            file_path="/repo/.github/workflows/release.yml",
            content="...",
        ),
    )
    assert len(v) == 1


def test_multiedit_to_claude_settings_local_without_consent(
    tmp_path: Path,
) -> None:
    v = _violations(
        tmp_path,
        "claude-settings.jsonl",
        _tool_call(
            "MultiEdit",
            file_path="/repo/.claude/settings.local.json",
            edits=[{"old_string": "false", "new_string": "true"}],
        ),
    )
    assert len(v) == 1


def test_write_to_husky_pre_commit_without_consent(tmp_path: Path) -> None:
    v = _violations(
        tmp_path,
        "husky.jsonl",
        _tool_call(
            "Write",
            file_path="/repo/.husky/pre-commit",
            content="...",
        ),
    )
    assert len(v) == 1


def test_mcp_write_file_to_cursor_mcp_json_without_consent(
    tmp_path: Path,
) -> None:
    v = _violations(
        tmp_path,
        "cursor.jsonl",
        _tool_call(
            "mcp__filesystem__write_file",
            path="/repo/.cursor/mcp.json",
            content="...",
        ),
    )
    assert len(v) == 1


def test_mcp_move_file_overwriting_pre_push_hook(tmp_path: Path) -> None:
    v = _violations(
        tmp_path,
        "mv-hook.jsonl",
        _tool_call(
            "mcp__filesystem__move_file",
            path="/tmp/evil",
            destination="/repo/.git/hooks/pre-push",
        ),
    )
    assert len(v) == 1


def test_edit_to_cursorrules_without_consent(tmp_path: Path) -> None:
    v = _violations(
        tmp_path,
        "cursorrules.jsonl",
        _tool_call("Edit", file_path="/repo/.cursorrules"),
    )
    assert len(v) == 1


def test_windows_path_to_git_hooks_without_consent(tmp_path: Path) -> None:
    v = _violations(
        tmp_path,
        "win.jsonl",
        _tool_call(
            "Edit", file_path=r"C:\repo\.git\hooks\pre-commit"
        ),
    )
    assert len(v) == 1


# ------- consent clears one matching call -------------------------


def test_consent_clears_one_matching_call(tmp_path: Path) -> None:
    v = _violations(
        tmp_path,
        "consent.jsonl",
        _user_message("yes, edit it"),
        _tool_call("Edit", file_path="/repo/.git/hooks/pre-commit"),
    )
    assert v == []


def test_consent_clears_one_call_only_no_persist(tmp_path: Path) -> None:
    v = _violations(
        tmp_path,
        "one-shot.jsonl",
        _user_message("yes, edit it"),
        _tool_call("Edit", file_path="/repo/.git/hooks/pre-commit"),
        _tool_call("Write", file_path="/repo/.github/workflows/ci.yml"),
    )
    assert len(v) == 1
    # second call (Write) fires
    assert v[0].event_index == 2


# ------- negative cases (must NOT trigger) -----------------------


def test_edit_to_source_file_is_not_flagged(tmp_path: Path) -> None:
    v = _violations(
        tmp_path,
        "src.jsonl",
        _tool_call("Edit", file_path="/repo/src/index.ts"),
    )
    assert v == []


def test_edit_to_documentation_is_not_flagged(tmp_path: Path) -> None:
    v = _violations(
        tmp_path,
        "docs.jsonl",
        _tool_call("Edit", file_path="/repo/docs/setup.md"),
    )
    assert v == []


def test_read_of_workflow_is_not_flagged(tmp_path: Path) -> None:
    v = _violations(
        tmp_path,
        "read.jsonl",
        _tool_call("Read", file_path="/repo/.github/workflows/ci.yml"),
    )
    assert v == []


def test_bash_command_is_not_flagged_by_this_spec(tmp_path: Path) -> None:
    """The Bash version covers shell-driven harm. This direct-tool
    spec must NOT fire on a Bash command — double-counting belongs
    to the cross-spec contract test, not to this rule on its own."""
    v = _violations(
        tmp_path,
        "bash.jsonl",
        _tool_call(
            "Bash",
            command="echo evil >> .git/hooks/pre-commit",
        ),
    )
    assert v == []


def test_unrelated_dotfolder_is_not_flagged(tmp_path: Path) -> None:
    v = _violations(
        tmp_path,
        "vscode.jsonl",
        _tool_call("Edit", file_path="/repo/.vscode/settings.json"),
    )
    assert v == []


def test_user_level_xdg_config_is_intentionally_out_of_scope(
    tmp_path: Path,
) -> None:
    """The spec explicitly omits user-level ~/.config/claude-code/...
    paths to keep false-positive risk low. This documents that posture."""
    v = _violations(
        tmp_path,
        "user-config.jsonl",
        _tool_call(
            "Edit",
            file_path="/home/u/.config/claude-code/settings.json",
        ),
    )
    assert v == []
