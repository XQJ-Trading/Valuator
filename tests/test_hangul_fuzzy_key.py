"""Tests for jamo-based name fuzzy keys (Hangul + ASCII)."""

from __future__ import annotations

from difflib import SequenceMatcher

from valuator.utils.hangul_fuzzy_key import jamo_fuzzy_key


def test_jamo_fuzzy_key_decomposes_hangul_syllables() -> None:
    a = jamo_fuzzy_key("엘에스일렉트릭")
    b = jamo_fuzzy_key("엘에스 일렉트릭")
    assert a == b
    assert len(a) > len("엘에스일렉트릭")


def test_jamo_fuzzy_key_similar_korean_names_score_high() -> None:
    """Spelling variants that differ in syllable form should align better in jamo space."""
    q = jamo_fuzzy_key("LS일렉트릭")
    ref = jamo_fuzzy_key("엘에스일렉트릭")
    assert SequenceMatcher(None, q, ref).ratio() >= 0.65


def test_ascii_only_matches_normalized_strip() -> None:
    assert jamo_fuzzy_key("LS Electric") == "LSELECTRIC"


def test_ls_electric_english_surface_forms_share_key() -> None:
    """Spacing, case, and punctuation do not change the ASCII-only key."""
    canonical = jamo_fuzzy_key("LS Electric")
    assert canonical == "LSELECTRIC"
    variants = (
        "ls electric",
        "LS  Electric",
        "LS-ELECTRIC",
        "ls.electric",
        "Ls ElEcTrIc",
        "  ls\t electric  ",
    )
    for surface in variants:
        assert jamo_fuzzy_key(surface) == canonical, surface


def test_ls_electric_mixed_english_korean_forms_align() -> None:
    """Latin brand + Hangul tail should share structure with full-Hangul name in jamo space."""
    latin_hangul = jamo_fuzzy_key("LS일렉트릭")
    english = jamo_fuzzy_key("LS Electric")
    hangul = jamo_fuzzy_key("엘에스일렉트릭")
    assert SequenceMatcher(None, latin_hangul, hangul).ratio() >= 0.65
    assert SequenceMatcher(None, english, hangul).ratio() < SequenceMatcher(
        None, latin_hangul, hangul
    ).ratio()


def test_ls_electric_korean_spelling_variants_near_canonical() -> None:
    """한글 표기 오타·약침(앨/엘, 애/에, 렉/랙 등)이 자모 키에서 정식 표기와 가깝게 남는다."""
    canonical = jamo_fuzzy_key("엘에스일렉트릭")
    variants = (
        "엘에스일렉트릭",
        "엘에스 일렉트릭",
        "앨에스일렉트릭",
        "엘애스일렉트릭",
        "앨애스일렉트릭",
        "엘에스일랙트릭",
    )
    for surface in variants:
        ratio = SequenceMatcher(None, canonical, jamo_fuzzy_key(surface)).ratio()
        assert ratio >= 0.85, surface
