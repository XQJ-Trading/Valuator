from __future__ import annotations

from domain.query import QueryAnalysis
from valuator.core.agent.context_builder import build_task_context
from valuator.core.scheduler import Scheduler
from valuator.core.shared_state import SharedState
from valuator.core.task import ComplexTask
from valuator.evidence import EvidenceRow, SqliteEvidenceStore, stable_args_hash
from valuator.tools.base import ToolRegistry


def test_sqlite_evidence_store_round_trip_and_upsert(tmp_path) -> None:
    store = SqliteEvidenceStore(tmp_path / "evidence.db")
    row = EvidenceRow(
        session_id="session-1",
        tool_name="web_search_tool",
        stable_args_hash=stable_args_hash(
            "web_search_tool",
            {"query": "LS전선 경쟁사"},
        ),
        status="failed",
        value_summary="Search failed",
        value_ref="",
        task_id="root.0",
        unit_objective="경쟁사 확인",
        created_at="2026-04-16T10:00:00+09:00",
        updated_at="2026-04-16T10:00:00+09:00",
        stable_args={"query": "LS전선 경쟁사"},
    )

    store.record(row)
    looked_up = store.lookup(
        session_id="session-1",
        tool_name="web_search_tool",
        args={"query": "LS전선 경쟁사"},
    )

    assert looked_up is not None
    assert looked_up.status == "failed"
    assert looked_up.value_summary == "Search failed"

    updated = store.record(
        EvidenceRow(
            session_id="session-1",
            tool_name="web_search_tool",
            stable_args_hash=row.stable_args_hash,
            status="satisfied",
            value_summary="경쟁사 3곳 확인",
            value_ref="tasks/root.0/execution/result.md",
            task_id="root.1",
            unit_objective="경쟁사 확인",
            created_at="",
            updated_at="2026-04-16T10:05:00+09:00",
            stable_args={"query": "LS전선 경쟁사"},
        )
    )

    rows = store.list_for_session("session-1")

    assert len(rows) == 1
    assert rows[0].status == "satisfied"
    assert rows[0].value_summary == "경쟁사 3곳 확인"
    assert rows[0].task_id == "root.1"
    assert rows[0].created_at == row.created_at
    assert updated.created_at == row.created_at


def test_build_task_context_includes_session_evidence(tmp_path) -> None:
    store = SqliteEvidenceStore(tmp_path / "evidence.db")
    store.record(
        EvidenceRow(
            session_id="session-1",
            tool_name="opendart_financial_tool",
            stable_args_hash=stable_args_hash(
                "opendart_financial_tool",
                {"corp": "LS전선", "year_range": "2024", "fs_div": "CFS"},
            ),
            status="satisfied",
            value_summary="연결 재무제표 확보",
            value_ref="tasks/root.0/execution/result.md",
            task_id="root.0",
            unit_objective="2024 재무제표 수집",
            created_at="2026-04-16T10:00:00+09:00",
            updated_at="2026-04-16T10:00:00+09:00",
            stable_args={"corp": "LS전선", "year_range": "2024", "fs_div": "CFS"},
        )
    )

    scheduler = Scheduler(max_steps_per_task=10, concurrency=1)
    task = ComplexTask(id="root", description="root task")
    scheduler.register(task)

    ctx = build_task_context(
        task=task,
        query="LS전선 분석",
        scheduler=scheduler,
        analysis=QueryAnalysis(allowed_tools=["opendart_financial_tool"]),
        shared=SharedState(),
        tools=ToolRegistry(),
        evidence_store=store,
        evidence_session_id="session-1",
    )

    assert len(ctx.evidence) == 1
    assert ctx.evidence[0].tool_name == "opendart_financial_tool"
    assert ctx.evidence[0].value_summary == "연결 재무제표 확보"


def test_build_task_context_limits_evidence_to_task_scope(tmp_path) -> None:
    store = SqliteEvidenceStore(tmp_path / "evidence.db")
    rows = [
        ("root", "parent evidence"),
        ("root.0", "current evidence"),
        ("root.0.0", "descendant evidence"),
        ("root.1", "sibling evidence"),
    ]
    for index, (task_id, summary) in enumerate(rows):
        store.record(
            EvidenceRow(
                session_id="session-1",
                tool_name="web_search_tool",
                stable_args_hash=stable_args_hash(
                    "web_search_tool",
                    {"query": f"evidence-{index}"},
                ),
                status="satisfied",
                value_summary=summary,
                value_ref=f"tasks/{task_id}/execution/result.md",
                task_id=task_id,
                unit_objective="scope test",
                created_at="2026-04-16T10:00:00+09:00",
                updated_at="2026-04-16T10:00:00+09:00",
                stable_args={"query": f"evidence-{index}"},
            )
        )

    scheduler = Scheduler(max_steps_per_task=10, concurrency=1)
    root = ComplexTask(id="root", description="root task")
    child = ComplexTask(id="root.0", description="child task")
    descendant = ComplexTask(id="root.0.0", description="descendant task")
    sibling = ComplexTask(id="root.1", description="sibling task")
    root.add_child(child)
    child.add_child(descendant)
    root.add_child(sibling)
    scheduler.register(root)
    scheduler.register(child)
    scheduler.register(descendant)
    scheduler.register(sibling)

    ctx = build_task_context(
        task=child,
        query="scope test",
        scheduler=scheduler,
        analysis=QueryAnalysis(allowed_tools=["web_search_tool"]),
        shared=SharedState(),
        tools=ToolRegistry(),
        evidence_store=store,
        evidence_session_id="session-1",
    )

    assert [row.value_summary for row in ctx.evidence] == [
        "parent evidence",
        "current evidence",
        "descendant evidence",
    ]
