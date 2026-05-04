"""Generic pass-through adapter for files already in the canonical schema."""

from __future__ import annotations

from pathlib import Path

from agentaudit.adapters import register
from agentaudit.schema import Transcript, load_transcript


def load(path: Path) -> Transcript:
    return load_transcript(path)


register("generic", load)
