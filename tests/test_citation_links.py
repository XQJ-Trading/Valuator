from valuator.session.citation_links import (
    apply_citation_links_to_tool_payload,
    link_inline_citations,
    split_lenticular_source_refs,
    strip_lenticular_source_refs_from_tool_payload,
)


def test_link_inline_citations_replaces_when_url_present() -> None:
    text = "See data [1] and [2]."
    sources = ("https://a.example", "https://b.example")
    out = link_inline_citations(text, sources)
    assert out == (
        "See data [1](https://a.example) and [2](https://b.example)."
    )


def test_link_inline_citations_skips_existing_markdown_link() -> None:
    text = "Already [1](https://old.example) and plain [2]."
    sources = ("https://a.example", "https://b.example")
    out = link_inline_citations(text, sources)
    assert "https://old.example" in out
    assert "[2](https://b.example)" in out


def test_link_inline_citations_skips_out_of_range_and_non_http() -> None:
    text = "A [1] B [99] C [2]"
    sources = ("https://one.example", "not-a-url", "")
    out = link_inline_citations(text, sources)
    assert "[1](https://one.example)" in out
    assert "[99]" in out
    assert "[2]" in out


def test_apply_citation_links_to_tool_payload_dict() -> None:
    meta = {"sources": ["https://x.example"]}
    payload = {"findings": "Ref [1].", "other": 1}
    out = apply_citation_links_to_tool_payload(payload, meta)
    assert out["findings"] == "Ref [1](https://x.example)."
    assert out["other"] == 1


def test_apply_citation_links_no_metadata_sources() -> None:
    payload = {"findings": "Ref [1]."}
    assert apply_citation_links_to_tool_payload(payload, {}) is payload


def test_split_lenticular_source_refs_removes_brackets_and_collects() -> None:
    text = '설명【https://a.example】 더【https://b.example】'
    cleaned, refs = split_lenticular_source_refs(text)
    assert "【" not in cleaned and "】" not in cleaned
    assert refs == ["https://a.example", "https://b.example"]


def test_strip_lenticular_source_refs_from_tool_payload_findings() -> None:
    payload, refs = strip_lenticular_source_refs_from_tool_payload(
        {"findings": '본문【https://x.example】', "other": 1}
    )
    assert isinstance(payload, dict)
    assert payload["findings"] == "본문"
    assert payload["other"] == 1
    assert refs == ["https://x.example"]


def test_strip_after_citation_links_matches_session_store_order() -> None:
    meta = {"sources": ["https://src.example"]}
    payload = {"findings": 'A [1]. B【https://u.example】'}
    linked = apply_citation_links_to_tool_payload(payload, meta)
    stripped, refs = strip_lenticular_source_refs_from_tool_payload(linked)
    assert refs == ["https://u.example"]
    assert stripped["findings"] == "A [1](https://src.example). B"
