from __future__ import annotations

from pathlib import Path

from server.session_viewer_api import _browse_outline_rows


def _write_browse_node(path: Path, task_id: str) -> None:
    path.mkdir(parents=True)
    (path / "README.md").write_text(
        "\n".join(
            [
                f"# {path.name}",
                "",
                f"- task_id: {task_id}",
                "- state: done",
                "- task_type: leaf",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_browse_outline_rows_sort_and_label_by_task_id_prefix(tmp_path: Path) -> None:
    browse = tmp_path / "S-browse" / "browse"
    root = browse / "삼성전자_분석"
    _write_browse_node(root, "root")
    _write_browse_node(root / "valuation_method", "root.1")
    _write_browse_node(root / "financial_analysis", "root.0")
    _write_browse_node(root / "valuation_method" / "pbr_multiple_based", "root.1.1")
    _write_browse_node(root / "valuation_method" / "dcf", "root.1.0")

    rows = _browse_outline_rows(browse, "S-browse/browse", 0)

    assert [(row["depth"], row["title"]) for row in rows] == [
        (0, "삼성전자 분석"),
        (1, "[1] financial analysis"),
        (1, "[2] valuation method"),
        (2, "[2.1] dcf"),
        (2, "[2.2] pbr multiple based"),
    ]
