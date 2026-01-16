import json
import re
import shutil

from .gemini3 import Gemini3Client
from .hdps import HDPS
from .state_manager import StateManager
from .tool_router import ToolRouter


SYSTEM_PROMPT = (
    "Role: Planner decomposing top-down queries into JSON tasks.\n"
    "Output: Single JSON object {'tasks': [Task, ...]}. No markdown.\n"
    "Task Schema: {id (T-0001), title, description, level (int), parent_id (str|null), "
    "deps ([]), outputs ([{path, type}]), acceptance ([str]), data_sources ([SEC|YFINANCE|WEB])}.\n"
    "Rules:\n"
    "1. Level 1: parent_id=null. Level 2+: parent_id must reference a task from level-1.\n"
    "2. Parallelism: deps must be [] for every task (never list dependencies).\n"
    "3. Sources: exactly one source per task.\n"
    "4. Path: /execution/outputs/{id}/<file>.<ext>."
)


class Planner:
    def __init__(self, hdps: HDPS | None = None, model: str | None = None):
        self.hdps = hdps or HDPS()
        self.client = Gemini3Client(model=model)
        self.state_manager = StateManager(self.hdps, self.client)
        self.tool_router = ToolRouter(self.hdps)

    async def plan(self, query: str) -> dict:
        if not query or not query.strip():
            raise ValueError("query is required")
        self.hdps.ensure_required()
        goal = self.hdps.p("plan/goal.md").read_text(encoding="utf-8").strip()
        raw = await self.client.generate(
            self._build_prompt(goal, query),
            system_prompt=SYSTEM_PROMPT,
            response_mime_type="application/json",
        )
        ts = self.hdps.now()
        raw_ascii = raw.encode("unicode_escape").decode("ascii")
        self.hdps.append_ndjson(
            "plan/active/raw_responses.ndjson",
            {"ts": ts, "query": query, "raw": raw_ascii},
        )
        try:
            data = self._parse_json_response(raw)
            tasks = data.get("tasks")
            if isinstance(tasks, list):
                for task in tasks:
                    task["deps"] = []
            self._validate(data, require_tool_calls=False)
        except Exception as exc:
            self.hdps.append_ndjson(
                "plan/active/raw_responses.ndjson",
                {"ts": ts, "error": str(exc)},
            )
            raise
        state = await self.state_manager.ensure(query, data.get("tasks", []))
        data = self.tool_router.attach_tool_calls(data, state)
        self._validate(data, require_tool_calls=True)
        return self._commit(data, f"planner_update:{query}")

    def _build_prompt(self, goal: str, query: str) -> str:
        return (
            f"Goal:\n{goal}\n\n"
            f"Request:\n{query}\n\n"
            "Constraint: output paths must be absolute under "
            "/execution/outputs/{task_id}/<filename>.<ext>.\n"
        )

    def _parse_json_response(self, raw: str) -> dict:
        body = self._strip_fences(raw)
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            data = self._recover_json_object(body)
            if data is None:
                preview = raw.strip().replace("\n", " ")
                if len(preview) > 160:
                    preview = f"{preview[:160]}..."
                raise ValueError(f"invalid JSON response: {preview}") from exc
        if not isinstance(data, dict):
            raise ValueError("response must be a JSON object")
        return data

    def _strip_fences(self, text: str) -> str:
        content = text.strip()
        if "```" in content:
            parts = content.split("```")
            content = parts[1] if len(parts) > 1 else parts[0]
        return re.sub(r"^json\\s*", "", content.strip(), flags=re.IGNORECASE)

    def _recover_json_object(self, text: str) -> dict | None:
        body = text.lstrip()
        decoder = json.JSONDecoder()
        try:
            data, _ = decoder.raw_decode(body)
            return data
        except json.JSONDecodeError:
            return None

    def _validate(self, data: dict, require_tool_calls: bool) -> None:
        tasks = data.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            raise ValueError("tasks must be a non-empty list")
        required = {
            "id",
            "title",
            "description",
            "level",
            "parent_id",
            "deps",
            "outputs",
            "acceptance",
            "data_sources",
        }
        allowed_sources = {"SEC", "YFINANCE", "WEB"}
        seen: set[str] = set()
        levels: dict[str, int] = {}
        for task in tasks:
            if not isinstance(task, dict):
                raise ValueError("task must be an object")
            task_id = task.get("id")
            if missing := required - task.keys():
                raise ValueError(f"task {task_id} missing: {sorted(missing)}")
            if not isinstance(task_id, str) or not task_id:
                raise ValueError("id must be a non-empty string")
            if not isinstance(task["title"], str) or not task["title"].strip():
                raise ValueError(f"title must be a non-empty string: {task_id}")
            if (
                not isinstance(task["description"], str)
                or not task["description"].strip()
            ):
                raise ValueError(f"description must be a non-empty string: {task_id}")
            level = task["level"]
            if not (isinstance(level, int) and level >= 1):
                raise ValueError(f"invalid level: {task_id}")
            parent_id = task["parent_id"]
            if level == 1:
                if parent_id is not None:
                    raise ValueError(f"level 1 task cannot have parent_id: {task_id}")
            else:
                if not isinstance(parent_id, str) or not parent_id:
                    raise ValueError(f"level 2+ task requires parent_id: {task_id}")
                if parent_id not in seen or levels.get(parent_id) != level - 1:
                    raise ValueError(f"orphaned or invalid parent linkage: {task_id}")
            deps = task["deps"]
            if not isinstance(deps, list) or deps:
                raise ValueError(f"deps must be an empty list: {task_id}")
            outputs = task["outputs"]
            if not isinstance(outputs, list) or not outputs:
                raise ValueError(f"outputs must be a non-empty list: {task_id}")
            prefix = f"/execution/outputs/{task_id}/"
            for output in outputs:
                if (
                    not isinstance(output, dict)
                    or "path" not in output
                    or "type" not in output
                ):
                    raise ValueError(f"output must include path and type: {task_id}")
                out_path = output["path"]
                if not isinstance(out_path, str) or not out_path.startswith(prefix):
                    raise ValueError(f"invalid output path in {task_id}")
            acceptance = task["acceptance"]
            if not isinstance(acceptance, list) or not acceptance:
                raise ValueError(f"acceptance must be a non-empty list: {task_id}")
            data_sources = task["data_sources"]
            if (
                not isinstance(data_sources, list)
                or len(data_sources) != 1
                or data_sources[0] not in allowed_sources
            ):
                raise ValueError(f"invalid data_sources in {task_id}")
            if require_tool_calls:
                calls = task.get("tool_calls")
                if not isinstance(calls, list) or not calls:
                    raise ValueError(
                        f"missing tool_calls for executable task: {task_id}"
                    )
                call = calls[0]
                if (
                    not isinstance(call, dict)
                    or "args" not in call
                    or not isinstance(call["args"], dict)
                ):
                    raise ValueError(
                        f"invalid tool_calls for executable task: {task_id}"
                    )
            seen.add(task_id)
            levels[task_id] = level

    def _commit(self, data: dict, reason: str) -> dict:
        ts = self.hdps.now()
        meta = self.hdps.read_json("plan/active/metadata.json")
        major = meta.get("major_version", 1)
        rev = meta.get("revision", 0) + 1
        snapshot = self._snapshot(ts, reason)
        data.update({"major_version": major, "revision": rev})
        self.hdps.write_json("plan/active/decomposition.json", data)
        meta.update(
            {
                "major_version": major,
                "revision": rev,
                "modification_type": "MINOR",
                "trigger": reason,
                "last_modified": ts,
            }
        )
        self.hdps.write_json("plan/active/metadata.json", meta)
        self.hdps.append_atomic(
            self.hdps.p("plan/change_log.md"),
            f"{ts} PLAN_UPDATE: {reason} snapshot={snapshot}\n",
        )
        status_log = self.hdps.p("plan/active/status_log.ndjson")
        event_id = self.hdps.next_event_id(ts, status_log)
        self.hdps.append_ndjson(
            "plan/active/status_log.ndjson",
            {
                "event_id": event_id,
                "ts": ts,
                "actor": "Planner",
                "type": "PLAN_REVISION_BUMP",
                "detail": {"from": rev - 1, "to": rev, "reason": reason},
            },
        )
        status = self.hdps.read_json("status.json")
        status.update(
            {
                "system_status": "PLANNING",
                "plan_major_version": major,
                "plan_revision": rev,
                "current_task_id": data["tasks"][0]["id"],
                "last_event_id": event_id,
            }
        )
        self.hdps.write_json("status.json", status)
        return data

    def _snapshot(self, ts: str, reason: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", reason)[:48] or "update"
        snap_dir = self.hdps.p(f"plan/archive/snapshot_{ts}_{safe}")
        snap_dir.mkdir(parents=True, exist_ok=True)
        for name in ("decomposition.json", "metadata.json"):
            src = self.hdps.p(f"plan/active/{name}")
            if src.exists():
                shutil.copy2(src, snap_dir / name)
        return snap_dir.name


if __name__ == "__main__":
    import asyncio

    query = """아마존 분석해줘
다음은 언급한 티커에 대한 전문 투자자 관점에서의 기업 분석 업무를 체계적으로 구조화한 Task Text입니다.

**주제: 특정 종목(티커)에 대한 심층 분석 (전문 투자자 관점)**

1.  **사업부문별 비교 분석 (Business Segment Analysis)**
    1.a. **목적 및 범위:** 기업의 각 사업부문별 성과를 비교하여 핵심 수익원과 성장 동력을 파악합니다.
    1.b. **사업부문 식별 및 정의:** 공시 자료(사업보고서 등)를 기반으로 기업의 모든 사업부문을 명확히 구분하고 정의합니다.
    1.c. **사업부문별 매출액 분석:**
        - 각 사업부문의 최근 3~5년간 매출액 추이를 분석합니다.
        - 전체 매출에서 각 부문이 차지하는 비중과 그 변화를 분석합니다.
    1.d. **사업부문별 수익성 분석:**
        - 각 사업부문의 영업이익, 이익률 등을 비교 분석합니다.
        - 수익성 기여도가 높은 핵심 사업부문을 식별합니다.

2.  **핵심 사업부 심층 분석 (Core Business Deep Dive)**
    2.a. **목적 및 범위:** 핵심 사업부의 산업 생태계(전방 수요, 밸류체인)를 분석하여 차년도 실적에 영향을 미칠 긍정적 요인과 리스크를 예측합니다.
    2.b. **전방 수요처 및 밸류체인 분석:**
        - 핵심 사업부의 주요 고객사 및 최종 수요처(End-market)를 파악합니다.
        - 원재료 조달부터 최종 제품 판매까지의 밸류체인 구조를 분석합니다.
    2.c. **차년도 수요 측면 분석:**
        - 전방 산업의 시장 성장률, 고객사 투자 계획 등을 기반으로 차년도 수요를 전망합니다.
        - 수요 측면의 긍정적 요인(예: 신규 시장 개척, 고객사 점유율 확대)을 식별합니다.
        - 수요 측면의 리스크 요인(예: 전방 산업 침체, 경쟁 심화)을 식별합니다.
    2.d. **원재료 수급 측면 분석:**
        - 주요 원재료의 가격 변동 추이 및 수급 안정성을 평가합니다.
        - 원재료 수급 측면의 긍정적 요인(예: 원가 하락, 공급망 안정화)을 식별합니다.
        - 원재료 수급 측면의 리스크 요인(예: 원가 급등, 공급망 차질)을 식별합니다.

3.  **재무구조 및 지배구조 리스크 분석 (Financial & Governance Risk Analysis)**
    3.a. **목적 및 범위:** 기업의 재무적 안정성과 지배구조의 투명성을 검토하여 잠재적 리스크 요인을 도출합니다.
    3.b. **재무구조 건전성 검토:**
        - 부채비율, 유동비율, 이자보상배율 등 주요 재무 안정성 지표를 분석합니다.
        - 현금흐름표를 통해 영업, 투자, 재무 활동의 건전성을 평가합니다.
    3.c. **지배구조(거버넌스) 리스크 검토:**
        - 주요 주주 구성 및 이사회 독립성을 평가합니다.
        - 특수관계자 거래, 경영진의 평판 등 잠재적 지배구조 리스크를 검토합니다.

4.  **최종 투자 전망 종합 (Final Outlook Synthesis)**
    4.a. **목적 및 범위:** 앞선 모든 분석 결과를 종합하여 해당 기업에 대한 균형 잡힌 투자 전망을 제시합니다.
    4.b. **긍정적 전망(Bull Case) 정리:**
        - 분석을 통해 도출된 성장 동력, 기회 요인, 강점 등을 요약합니다.
    4.c. **부정적 전망(Bear Case) 정리:**
        - 분석을 통해 도출된 핵심 리스크, 위협 요인, 약점 등을 요약합니다.
    4.d. **결론 제시:** 긍정적/부정적 전망을 요약합니다."""
    if not query:
        raise SystemExit('usage: python -m valuator.core.planner "query"')
    base_hdps = HDPS()
    sid = base_hdps.new_session_id()
    hdps = HDPS(session_id=sid)
    hdps.bootstrap()
    plan = asyncio.run(Planner(hdps=hdps).plan(query))
    print(json.dumps(plan, indent=2, ensure_ascii=True))
