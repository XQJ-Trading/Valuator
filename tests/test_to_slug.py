"""to_slug is used for browse dirs and CLI session folder names."""

from valuator.session.browse_tree import to_slug


def test_preserves_hangul_and_uses_underscores_for_whitespace() -> None:
    assert to_slug("달러 분석 요청") == "달러_분석_요청"


def test_truncates_to_max_length() -> None:
    long_ko = "달러는 당분간 어떻게 될지 초단기적부터 중장기적 관점으로 분석하고 달러를 언제팔면 좋을지"
    out = to_slug(long_ko, max_length=40)
    assert len(out) <= 40
    assert out.startswith(
        "달러는_당분간_어떻게_될지_초단기적부터_중장기적_관점으로_분석"
    )
