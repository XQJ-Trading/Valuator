import argparse
import asyncio
import json
from .executor import Executor
from .gemini3 import Gemini3Client
from .hdps import HDPS
from .planner import Planner
from .sessions import SessionWriter


REPORT_SYSTEM_PROMPT = (
    "You are a quant research analyst. Write a concise, data-backed Markdown report using only the provided artifacts. "
    "Bottom-up structure: (1) facts per task ID, (2) findings, (3) section conclusions. "
)

REPORT_PROMPT = (
    "User query:\n{query}\n\n"
    "Artifacts:\n{artifacts}\n\n"
    "Write a concise, data-backed Markdown report.\n"
    "Rules:\n"
    "- Keep it concise and information-dense; build from facts to conclusions.\n"
    "- Cite artifact filenames when referencing facts.\n"
    "- In Framing, list assumptions/biases, an alternative framing.\n"
    "- Include counter-scenarios or multiple perspectives where relevant.\n"
    "- Cover every task ID using only supported facts"
    "- Write in Korean.\n"
)


async def _execute_tasks(
    plan: dict, hdps: HDPS, task_ids: list[str] | None = None
) -> list[str]:
    ex = Executor(hdps=hdps)
    tasks = plan["tasks"]
    if task_ids:
        wanted = set(task_ids)
        tasks = [task for task in tasks if task["id"] in wanted]
    for task in tasks:
        call = task["tool_calls"][0]
        await ex.run_tool(
            task_id=task["id"],
            tool_name=call["name"],
            tool_input=call["args"],
            output_path=task["outputs"][0]["path"],
        )
    return [task["id"] for task in tasks]


def _load_artifacts(hdps: HDPS, task_ids: list[str]) -> str:
    blocks = []
    for task_id in task_ids:
        out_dir = hdps.p(f"execution/outputs/{task_id}")
        for path in sorted(out_dir.glob("*")):
            if path.name == "artifact_manifest.json" or path.is_dir():
                continue
            content = path.read_text(encoding="utf-8")
            blocks.append(f"[{task_id}/{path.name}]\n{content[:4000]}")
    return "\n\n".join(blocks)


async def _build_report(client: Gemini3Client, query: str, artifacts: str) -> str:
    prompt = REPORT_PROMPT.format(query=query, artifacts=artifacts)
    return await client.generate(
        prompt,
        system_prompt=REPORT_SYSTEM_PROMPT,
        response_mime_type="text/plain",
    )


async def main(query: str = "") -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default=query)
    parser.add_argument("--system-prompt", default="HDPS mode")
    parser.add_argument("--final", default=None)
    args = parser.parse_args()

    hdps = HDPS(session_id=HDPS().new_session_id())
    hdps.bootstrap()
    planner = Planner(hdps=hdps)
    query = query or args.query
    plan = await planner.plan(query)
    task_ids = await _execute_tasks(plan, hdps)
    final = args.final
    if final is None:
        report_client = Gemini3Client()
        artifacts = _load_artifacts(hdps, task_ids)
        final = await _build_report(report_client, query, artifacts)
    final = f"작성 시각(UTC): {hdps.now()}\n\n{final}"
    summary = {
        "status": "SUCCESS",
        "blocked_events": 0,
        "retries": 0,
        "plan_major_version": plan["major_version"],
        "completed_at": hdps.now(),
    }
    sid = SessionWriter(hdps=hdps).write(
        user_input=args.query,
        system_prompt=args.system_prompt,
        final=final,
        summary=summary,
        verdict="PASS",
        execution_task_ids=task_ids,
    )
    print(json.dumps({"session_id": sid}, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    # query = "브로드컴 기업 분석 해줘."
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
    asyncio.run(main(query))
