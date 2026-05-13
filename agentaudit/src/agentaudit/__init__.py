"""agentaudit — verify LLM agent transcripts against behavior specs."""

from agentaudit.schema import (
    Event,
    EventKind,
    Transcript,
    load_transcript,
    load_transcript_jsonl,
)
from agentaudit.spec import Rule, Spec, load_spec
from agentaudit.checker import JudgeFinding, Violation, check
from agentaudit.report import render_text, render_json
from agentaudit.watch import (
    Decision,
    evaluate_event,
    read_history,
    run_hook_mode,
    run_replay,
    run_stream_mode,
)

__all__ = [
    "Event",
    "EventKind",
    "Transcript",
    "load_transcript",
    "load_transcript_jsonl",
    "Rule",
    "Spec",
    "load_spec",
    "JudgeFinding",
    "Violation",
    "check",
    "render_text",
    "render_json",
    "Decision",
    "evaluate_event",
    "read_history",
    "run_hook_mode",
    "run_replay",
    "run_stream_mode",
]

__version__ = "0.2.0"
