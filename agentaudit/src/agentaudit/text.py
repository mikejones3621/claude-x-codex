"""Text normalisation helpers for rule evaluators.

This module exists so that pattern-based rules can opt into a small,
documented normalisation pipeline before regex matching, instead of
each spec author having to enumerate every Unicode confusable inside
their pattern.

The pipeline is intentionally small and explicit:

    normalize_for_match(content, level)

with two levels:

    "basic"  — NFKC normalisation (collapses fullwidth Latin, alternative
               punctuation, ligatures, etc. to their canonical forms)
               plus stripping of zero-width characters (U+200B / U+200C /
               U+200D / U+FEFF).

    "strict" — "basic" PLUS a tightly-scoped Cyrillic-to-Latin homoglyph
               fold for the small set of letters that visually pass for
               Latin in role tokens (`SYSTEM`, `Developer`, `Admin`,
               etc.). The table is curated, not generated, because a
               permissive fold over all Cyrillic would corrupt
               legitimate non-English content.

Higher levels are free to add more passes (e.g. Greek lookalikes,
right-to-left override stripping) as concrete attacks motivate them.
"""

from __future__ import annotations

import unicodedata


_ZERO_WIDTH = "​‌‍﻿"

# Cyrillic capitals/lowercase whose glyphs are visually indistinguishable
# from Latin letters in standard fonts. Curated, not generated: a
# permissive fold over all Cyrillic would corrupt legitimate Russian /
# Ukrainian / Bulgarian / etc. content. The set below is the standard
# "look-alike" table used by IDN homograph defences.
_CYRILLIC_TO_LATIN = str.maketrans(
    {
        # uppercase
        "А": "A",  # А
        "В": "B",  # В
        "С": "C",  # С
        "Е": "E",  # Е
        "Н": "H",  # Н
        "І": "I",  # І
        "Ј": "J",  # Ј
        "К": "K",  # К
        "М": "M",  # М
        "О": "O",  # О
        "Р": "P",  # Р
        "Ѕ": "S",  # Ѕ
        "Т": "T",  # Т
        "У": "Y",  # У
        "Х": "X",  # Х
        # lowercase
        "а": "a",  # а
        "в": "b",  # в (visually closer to Latin b in many fonts)
        "с": "c",  # с
        "е": "e",  # е
        "һ": "h",  # һ
        "і": "i",  # і
        "ј": "j",  # ј
        "к": "k",  # к
        "м": "m",  # м
        "о": "o",  # о
        "р": "p",  # р
        "ѕ": "s",  # ѕ
        "т": "t",  # т
        "у": "y",  # у
        "х": "x",  # х
    }
)


def normalize_for_match(content: str, level: str | bool | None) -> str:
    """Return a version of `content` suitable for regex matching.

    Parameters
    ----------
    content : str
        Event content as it appears in the transcript.
    level : str | bool | None
        - None / False / "" : no-op (return content unchanged).
        - True / "basic"    : NFKC normalisation + strip zero-width chars.
        - "strict"          : basic + Cyrillic-to-Latin homoglyph fold.

    Unknown levels raise `ValueError` so a typo in a spec fails loudly
    rather than silently disabling the protection.
    """
    if not level:
        return content
    if level is True or level == "basic":
        return _basic(content)
    if level == "strict":
        return _basic(content).translate(_CYRILLIC_TO_LATIN)
    raise ValueError(
        f"unknown normalize level: {level!r}; expected None/false, true/'basic', or 'strict'"
    )


def _basic(content: str) -> str:
    folded = unicodedata.normalize("NFKC", content)
    if any(c in folded for c in _ZERO_WIDTH):
        folded = folded.translate({ord(c): None for c in _ZERO_WIDTH})
    return folded
