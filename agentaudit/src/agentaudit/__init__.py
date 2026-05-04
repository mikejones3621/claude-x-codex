"""agentaudit — verify LLM agent transcripts against behavior specs."""

from agentaudit.schema import (
    Event,
    EventKind,
    Transcript,
    load_transcript,
    load_transcript_jsonl,
)
from agentaudit.spec import Rule, Spec, load_spec
from agentaudit.checker import Violation, check
from agentaudit.report import render_text, render_json

__all__ = [
    "Event",
    "EventKind",
    "Transcript",
    "load_transcript",
    "load_transcript_jsonl",
    "Rule",
    "Spec",
    "load_spec",
    "Violation",
    "check",
    "render_text",
    "render_json",
]

__version__ = "0.1.0"
