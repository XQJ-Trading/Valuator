from __future__ import annotations

import json
from pathlib import Path

from valuator.core.task import AtomicTask, ComplexTask
from valuator.core.types import TaskState
from valuator.runtime import final_output_text
from valuator.session import ValuatorSessionStore
from valuator.tools.base import ToolResult


def test_build_browse_tree_writes_markdown_first_tree_and_resolves_name_collisions(
    tmp_path: Path,
) -> None:
    store = ValuatorSessionStore(
        session_id="S-browse",
        query="이란 미국 전쟁 시나리오 분석",
        model="stub-model",
        created_at="2026-03-27T13:20:30.845896Z",
        root_dir=tmp_path,
    )
    root = ComplexTask(
        id="root",
        description="Valuation: [THINKING_LEVEL]\nhigh\n\n[QUERY]\n이란 미국 전쟁 시나리오 분석",
    )
    child_one = AtomicTask(
        id="root.0",
        description="시장 반응 조사",
        task_name="시장_반응",
        tool_hint="web_search_tool",
    )
    child_two = AtomicTask(
        id="root.1",
        description="원자재 반응 조사",
        task_name="시장_반응",
        tool_hint="web_search_tool",
    )
    child_three = AtomicTask(
        id="root.2",
        description="supply chain delay estimate",
        tool_hint="web_search_tool",
    )
    for task in (root, child_one, child_two, child_three):
        task.state = TaskState.DONE
    root.add_child(child_one)
    root.add_child(child_two)
    root.add_child(child_three)

    store.sync_task_tree(root)
    store._write_text(
        store.session_dir / "tasks" / "root" / "task.md", "# Root task trace\n"
    )
    store._write_text(
        store.session_dir / "tasks" / "root" / "root.0" / "task.md",
        "# Child task trace\n",
    )
    store.write_execution_result(
        task_id="root.0",
        tool_name="web_search_tool",
        args={"query": "시장 반응 조사"},
        result=ToolResult(
            success=True,
            result={"markdown": "시장 반응 결과"},
            metadata={},
        ),
        started_at="2026-03-27T13:21:00.000000Z",
        duration_ms=12.5,
    )
    store.write_aggregation_report(task_id="root.0", output=None)
    store.write_aggregation_report(task_id="root", output="루트 요약")
    store.write_final_output("# Final\n\n최종 결론", root_task=root)
    store.sync_task_tree(root)

    stale_path = store.session_dir / "browse" / "stale" / "old.md"
    stale_path.parent.mkdir(parents=True, exist_ok=True)
    stale_path.write_text("stale\n", encoding="utf-8")

    store.build_browse_tree()

    child_one_json = json.loads(
        (store.session_dir / "tasks" / "root" / "root.0" / "task.json").read_text(
            encoding="utf-8"
        )
    )
    assert child_one_json["task_name"] == "시장_반응"
    assert not stale_path.exists()

    browse_root_entries = [
        path for path in (store.session_dir / "browse").iterdir() if path.is_dir()
    ]
    assert len(browse_root_entries) == 1
    root_browse_dir = browse_root_entries[0]
    assert "Valuation" not in root_browse_dir.name
    assert "THINKING" not in root_browse_dir.name
    assert "이란" in root_browse_dir.name

    child_dirs = sorted(
        path.name for path in root_browse_dir.iterdir() if path.is_dir()
    )
    assert child_dirs == ["supply_chain_delay_estimate", "시장_반응", "시장_반응_2"]

    root_readme = (root_browse_dir / "README.md").read_text(encoding="utf-8")
    assert "- task_id: root" in root_readme
    assert "- state: done" in root_readme
    assert "- task_type: merge" in root_readme
    assert "최종 결론" not in root_readme
    assert not (root_browse_dir / "info.json").exists()
    assert not (root_browse_dir / "task.json").exists()
    assert not (root_browse_dir / "steps.jsonl").exists()
    assert not (root_browse_dir / "llm_calls").exists()

    root_report = (root_browse_dir / "report.md").read_text(encoding="utf-8")
    assert "루트 요약" in root_report
    assert (
        (root_browse_dir / "final.md").read_text(encoding="utf-8").startswith("# Final")
    )

    child_browse_dir = root_browse_dir / "시장_반응"
    child_readme = (child_browse_dir / "README.md").read_text(encoding="utf-8")
    assert "- task_id: root.0" in child_readme
    assert "- state: done" in child_readme
    assert "- task_type: leaf" in child_readme
    assert not (root_browse_dir / "task.md").exists()
    assert not (child_browse_dir / "task.md").exists()
    child_report = (child_browse_dir / "report.md").read_text(encoding="utf-8")
    assert "시장 반응 결과" in child_report
    assert not (child_browse_dir / "result.md").exists()
    assert not (child_browse_dir / "execution").exists()
    assert not (child_browse_dir / "task.json").exists()

    idle_child_report = (
        root_browse_dir / "supply_chain_delay_estimate" / "report.md"
    ).read_text(encoding="utf-8")
    assert "Task completed without a report artifact." in idle_child_report


def test_write_aggregation_report_preserves_facts_only_output(tmp_path: Path) -> None:
    store = ValuatorSessionStore(
        session_id="S-facts-only",
        query="facts only",
        model="stub-model",
        created_at="2026-03-29T00:00:00Z",
        root_dir=tmp_path,
    )
    root = ComplexTask(id="root", description="root task")
    root.state = TaskState.DONE

    store.sync_task_tree(root)
    store.write_aggregation_report(
        task_id="root",
        output={
            "status": "facts_only",
            "facts": {"price_uplift": "could not verify"},
            "source_task_id": "root",
        },
    )

    ledger = json.loads(
        (
            store.session_dir / "tasks" / "root" / "aggregation" / "raw_results.json"
        ).read_text(encoding="utf-8")
    )

    assert ledger["facts"] == {"price_uplift": "could not verify"}


def test_leaf_aggregation_report_preserves_execution_markdown(tmp_path: Path) -> None:
    store = ValuatorSessionStore(
        session_id="S-leaf-report",
        query="leaf report",
        model="stub-model",
        created_at="2026-03-29T00:00:00Z",
        root_dir=tmp_path,
    )
    root = ComplexTask(id="root", description="root task")
    child = AtomicTask(id="root.0", description="시장 반응 조사", task_name="시장_반응")
    root.add_child(child)
    root.state = TaskState.DONE
    child.state = TaskState.DONE

    store.sync_task_tree(root)
    store.write_execution_result(
        task_id="root.0",
        tool_name="web_search_tool",
        args={"query": "시장 반응"},
        result=ToolResult(
            success=True, result={"markdown": "시장 반응 결과"}, metadata={}
        ),
        started_at="2026-03-29T00:01:00Z",
        duration_ms=8.0,
    )
    store.write_aggregation_report(task_id="root.0", output=None)

    report = (
        store.session_dir / "tasks" / "root" / "root.0" / "aggregation" / "report.md"
    ).read_text(encoding="utf-8")
    raw_results = json.loads(
        (
            store.session_dir
            / "tasks"
            / "root"
            / "root.0"
            / "aggregation"
            / "raw_results.json"
        ).read_text(encoding="utf-8")
    )

    assert "시장 반응 결과" in report
    assert '"markdown"' not in report
    assert raw_results["facts"] == {"markdown": "시장 반응 결과"}


def test_parent_aggregation_report_prefers_child_aggregation_report(
    tmp_path: Path,
) -> None:
    store = ValuatorSessionStore(
        session_id="S-parent-report",
        query="parent report",
        model="stub-model",
        created_at="2026-03-29T00:00:00Z",
        root_dir=tmp_path,
    )
    root = ComplexTask(id="root", description="root task")
    child = AtomicTask(id="root.0", description="시장 반응 조사", task_name="시장_반응")
    root.add_child(child)
    root.state = TaskState.DONE
    child.state = TaskState.DONE

    store.sync_task_tree(root)
    store.write_execution_result(
        task_id="root.0",
        tool_name="web_search_tool",
        args={"query": "시장 반응"},
        result=ToolResult(
            success=True, result={"markdown": "execution result"}, metadata={}
        ),
        started_at="2026-03-29T00:01:00Z",
        duration_ms=8.0,
    )
    store.write_aggregation_report(task_id="root.0", output="child assembled report")
    store.write_aggregation_report(task_id="root", output="parent summary")

    report = (
        store.session_dir / "tasks" / "root" / "aggregation" / "report.md"
    ).read_text(encoding="utf-8")
    raw_results = json.loads(
        (
            store.session_dir / "tasks" / "root" / "aggregation" / "raw_results.json"
        ).read_text(encoding="utf-8")
    )

    assert "parent summary" in report
    assert "child assembled report" in report
    assert "execution result" not in report
    assert raw_results["child_results"][0]["source_type"] == "aggregation"


def test_aggregation_report_renders_structured_output_without_json_dump(
    tmp_path: Path,
) -> None:
    store = ValuatorSessionStore(
        session_id="S-structured-report",
        query="structured report",
        model="stub-model",
        created_at="2026-03-29T00:00:00Z",
        root_dir=tmp_path,
    )
    root = ComplexTask(id="root", description="root task")
    root.state = TaskState.DONE

    store.sync_task_tree(root)
    store.write_aggregation_report(
        task_id="root",
        output={
            "market_impact_summary": "요약",
            "scenario_table": "| A | B |\n| --- | --- |\n| 1 | 2 |",
        },
    )

    report = (
        store.session_dir / "tasks" / "root" / "aggregation" / "report.md"
    ).read_text(encoding="utf-8")

    assert "market impact summary" in report
    assert "| A | B |" in report
    assert '"market_impact_summary"' not in report


def test_write_final_output_renders_structured_output_as_markdown(
    tmp_path: Path,
) -> None:
    store = ValuatorSessionStore(
        session_id="S-final-structured",
        query="structured final",
        model="stub-model",
        created_at="2026-03-29T00:00:00Z",
        root_dir=tmp_path,
    )
    root = ComplexTask(id="root", description="root task")
    root.state = TaskState.DONE

    store.sync_task_tree(root)
    store.write_final_output(
        {
            "status": "facts_only",
            "facts": {"price_uplift": "could not verify"},
            "source_task_id": "root",
        },
        root_task=root,
    )

    final_markdown = (store.session_dir / "output" / "final.md").read_text(
        encoding="utf-8"
    )

    assert final_markdown.startswith("# Final")
    assert "price uplift" in final_markdown
    assert "could not verify" in final_markdown
    assert '"price_uplift"' not in final_markdown


def test_write_final_output_prefers_root_report_when_output_is_structured(
    tmp_path: Path,
) -> None:
    store = ValuatorSessionStore(
        session_id="S-final-prefers-root-report",
        query="final report",
        model="stub-model",
        created_at="2026-03-29T00:00:00Z",
        root_dir=tmp_path,
    )
    root = ComplexTask(id="root", description="root task")
    root.state = TaskState.DONE

    store.sync_task_tree(root)
    store.write_aggregation_report(task_id="root", output="루트 요약")
    store.write_final_output(
        {
            "status": "facts_only",
            "facts": {"price_uplift": "could not verify"},
            "source_task_id": "root",
        },
        root_task=root,
    )

    final_markdown = (store.session_dir / "output" / "final.md").read_text(
        encoding="utf-8"
    )

    assert final_markdown.startswith("# Final")
    assert "루트 요약" in final_markdown
    assert "price uplift" not in final_markdown


def test_runtime_final_output_text_matches_store_render_without_root_report(
    tmp_path: Path,
) -> None:
    store = ValuatorSessionStore(
        session_id="S-runtime-parity",
        query="runtime parity",
        model="stub-model",
        created_at="2026-03-29T00:00:00Z",
        root_dir=tmp_path,
    )
    root = ComplexTask(id="root", description="root task")
    root.state = TaskState.DONE
    store.sync_task_tree(root)
    output = {
        "status": "facts_only",
        "facts": {"price_uplift": "could not verify"},
        "source_task_id": "root",
    }

    assert store.final_output_markdown(output) == final_output_text(output)


def test_build_browse_tree_uses_execution_fallback_and_failure_stub(
    tmp_path: Path,
) -> None:
    store = ValuatorSessionStore(
        session_id="S-browse-fallbacks",
        query="browse fallback",
        model="stub-model",
        created_at="2026-03-29T00:00:00Z",
        root_dir=tmp_path,
    )
    root = ComplexTask(id="root", description="root task")
    exec_child = AtomicTask(
        id="root.0", description="execution only", task_name="execution_only"
    )
    failed_child = AtomicTask(
        id="root.1", description="failed child", task_name="failed_child"
    )
    failed_child.error = "planner rejected invalid aggregate payload"
    root.add_child(exec_child)
    root.add_child(failed_child)
    root.state = TaskState.DONE
    exec_child.state = TaskState.DONE
    failed_child.state = TaskState.FAILED

    store.sync_task_tree(root)
    store.write_execution_result(
        task_id="root.0",
        tool_name="web_search_tool",
        args={"query": "execution only"},
        result=ToolResult(
            success=True, result={"markdown": "execution only markdown"}, metadata={}
        ),
        started_at="2026-03-29T00:01:00Z",
        duration_ms=8.0,
    )

    store.build_browse_tree()

    browse_root_entries = [
        path for path in (store.session_dir / "browse").iterdir() if path.is_dir()
    ]
    root_browse_dir = browse_root_entries[0]

    execution_report = (root_browse_dir / "execution_only" / "report.md").read_text(
        encoding="utf-8"
    )
    failed_report = (root_browse_dir / "failed_child" / "report.md").read_text(
        encoding="utf-8"
    )

    assert "execution only markdown" in execution_report
    assert "Task failed before producing a report artifact." in failed_report
    assert "planner rejected invalid aggregate payload" in failed_report
