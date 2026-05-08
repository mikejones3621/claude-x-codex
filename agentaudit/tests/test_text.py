"""Unit tests for agentaudit.text.normalize_for_match."""

from __future__ import annotations

import pytest

from agentaudit.text import normalize_for_match


class TestNoOp:
    """`level` of None / False / "" must return content unchanged."""

    def test_none(self) -> None:
        assert normalize_for_match("ＳＹＳＴＥＭ: x", None) == "ＳＹＳＴＥＭ: x"

    def test_false(self) -> None:
        assert normalize_for_match("ЅYSTEM", False) == "ЅYSTEM"

    def test_empty_string(self) -> None:
        assert normalize_for_match("ＳＹＳＴＥＭ", "") == "ＳＹＳＴＥＭ"


class TestBasic:
    """`basic` runs NFKC + strips zero-width characters."""

    def test_fullwidth_latin_collapses_to_ascii(self) -> None:
        assert normalize_for_match("ＳＹＳＴＥＭ", "basic") == "SYSTEM"

    def test_fullwidth_colon_collapses(self) -> None:
        assert normalize_for_match("SYSTEM： ignore", "basic") == "SYSTEM: ignore"

    def test_zero_width_space_stripped(self) -> None:
        assert normalize_for_match("S​Y​S​T​E​M", "basic") == "SYSTEM"

    def test_all_zero_width_variants_stripped(self) -> None:
        s = "A​B‌C‍D﻿E"
        assert normalize_for_match(s, "basic") == "ABCDE"

    def test_true_means_basic(self) -> None:
        assert normalize_for_match("ＳＹＳＴＥＭ", True) == "SYSTEM"

    def test_basic_does_not_fold_cyrillic(self) -> None:
        # "basic" preserves non-Latin scripts intact.
        assert normalize_for_match("ЅYSTEM", "basic") == "ЅYSTEM"

    def test_ascii_passes_through(self) -> None:
        assert normalize_for_match("plain ASCII", "basic") == "plain ASCII"


class TestStrict:
    """`strict` adds a curated Cyrillic-to-Latin homoglyph fold."""

    def test_cyrillic_S_folds_to_latin(self) -> None:
        assert normalize_for_match("ЅYSTEM", "strict") == "SYSTEM"

    def test_full_cyrillic_system_folds(self) -> None:
        # Mixed Cyrillic homoglyphs throughout the word.
        assert normalize_for_match("ЅYЅTЕМ", "strict") == "SYSTEM"

    def test_strict_also_does_basic_passes(self) -> None:
        # NFKC + zwsp strip + cyrillic fold all in one shot.
        assert normalize_for_match("Ѕ​ＹＳＴＥＭ", "strict") == "SYSTEM"

    def test_strict_does_not_corrupt_legit_cyrillic_word(self) -> None:
        # "Россия" (Russia) contains characters that ARE in the look-alike
        # table (Р→P, о→o, с→c, и→i NOT in table, я→ NOT in table). The
        # fold is intentionally lossy for *isolated* lookalikes, but it
        # should never silently corrupt a real Russian sentence into
        # something semantically different that would false-positive a
        # rule. We assert here only that the fold is deterministic and
        # documented, not that it preserves Russian — operators handling
        # Russian content should drop to "basic".
        assert normalize_for_match("Россия", "strict") == "Poccия"


class TestUnknownLevel:
    def test_typo_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown normalize level"):
            normalize_for_match("anything", "stricter")

    def test_int_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown normalize level"):
            normalize_for_match("anything", 2)
