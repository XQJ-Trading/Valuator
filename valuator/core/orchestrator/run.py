from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

from .engine import Engine

DEFAULT_QUERIES = [
    (
        "아마존 분석해줘\n\n"
        "다음은 언급한 티커에 대한 전문 투자자 관점에서의 기업 분석 업무를 체계적으로 구조화한 Task Text입니다.\n\n"
        "**주제: 특정 종목(티커)에 대한 심층 분석 (전문 투자자 관점)**\n\n"
        "1. **사업부문별 비교 분석 (Business Segment Analysis)**\n"
        "1.a. **목적 및 범위:** 기업의 각 사업부문별 성과를 비교하여 핵심 수익원과 성장 동력을 파악합니다.\n"
        "1.b. **사업부문 식별 및 정의:** 공시 자료(사업보고서 등)를 기반으로 기업의 모든 사업부문을 명확히 구분하고 정의합니다.\n"
        "1.c. **사업부문별 매출액 분석:**\n"
        "  - 각 사업부문의 최근 3~5년간 매출액 추이를 분석합니다.\n"
        "  - 전체 매출에서 각 부문이 차지하는 비중과 그 변화를 분석합니다.\n"
        "1.d. **사업부문별 수익성 분석:**\n"
        "  - 각 사업부문의 영업이익, 이익률 등을 비교 분석합니다.\n"
        "  - 수익성 기여도가 높은 핵심 사업부문을 식별합니다.\n\n"
        "2. **핵심 사업부 심층 분석 (Core Business Deep Dive)**\n"
        "2.a. **목적 및 범위:** 핵심 사업부의 산업 생태계(전방 수요, 밸류체인)를 분석하여 차년도 실적에 영향을 미칠 긍정적 요인과 리스크를 예측합니다.\n"
        "2.b. **전방 수요처 및 밸류체인 분석:**\n"
        "  - 핵심 사업부의 주요 고객사 및 최종 수요처(End-market)를 파악합니다.\n"
        "  - 원재료 조달부터 최종 제품 판매까지의 밸류체인 구조를 분석합니다.\n"
        "2.c. **차년도 수요 측면 분석:**\n"
        "  - 전방 산업의 시장 성장률, 고객사 투자 계획 등을 기반으로 차년도 수요를 전망합니다.\n"
        "  - 수요 측면의 긍정적 요인(예: 신규 시장 개척, 고객사 점유율 확대)을 식별합니다.\n"
        "  - 수요 측면의 리스크 요인(예: 전방 산업 침체, 경쟁 심화)을 식별합니다.\n"
        "2.d. **원재료 수급 측면 분석:**\n"
        "  - 주요 원재료의 가격 변동 추이 및 수급 안정성을 평가합니다.\n"
        "  - 원재료 수급 측면의 긍정적 요인(예: 원가 하락, 공급망 안정화)을 식별합니다.\n"
        "  - 원재료 수급 측면의 리스크 요인(예: 원가 급등, 공급망 차질)을 식별합니다.\n\n"
        "3. **재무구조 및 지배구조 리스크 분석 (Financial & Governance Risk Analysis)**\n"
        "3.a. **목적 및 범위:** 기업의 재무적 안정성과 지배구조의 투명성을 검토하여 잠재적 리스크 요인을 도출합니다.\n"
        "3.b. **재무구조 건전성 검토:**\n"
        "  - 부채비율, 유동비율, 이자보상배율 등 주요 재무 안정성 지표를 분석합니다.\n"
        "  - 현금흐름표를 통해 영업, 투자, 재무 활동의 건전성을 평가합니다.\n"
        "3.c. **지배구조(거버넌스) 리스크 검토:**\n"
        "  - 주요 주주 구성 및 이사회 독립성을 평가합니다.\n"
        "  - 특수관계자 거래, 경영진의 평판 등 잠재적 지배구조 리스크를 검토합니다.\n\n"
        "4. **최종 투자 전망 종합 (Final Outlook Synthesis)**\n"
        "4.a. **목적 및 범위:** 앞선 모든 분석 결과를 종합하여 해당 기업에 대한 균형 잡힌 투자 전망을 제시합니다.\n"
        "4.b. **긍정적 전망(Bull Case) 정리:**\n"
        "  - 분석을 통해 도출된 성장 동력, 기회 요인, 강점 등을 요약합니다.\n"
        "4.c. **부정적 전망(Bear Case) 정리:**\n"
        "  - 분석을 통해 도출된 핵심 리스크, 위협 요인, 약점 등을 요약합니다.\n"
        "4.d. **결론 제시:** 긍정적/부정적 전망을 요약합니다."
    ),
    "Analyze NVIDIA (NVDA) revenue drivers, margin outlook, and key valuation risks.",
    "Analyze Tesla (TSLA) demand, margin trend, and capital allocation risk.",
]


def _default_session_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    return f"S-{timestamp}"


async def _run(args: argparse.Namespace) -> int:
    query = args.query
    if not query:
        idx = args.query_index
        if idx < 0 or idx >= len(DEFAULT_QUERIES):
            raise ValueError(f"query_index must be between 0 and {len(DEFAULT_QUERIES)-1}")
        query = DEFAULT_QUERIES[idx]

    session_id = args.session_id or _default_session_id()
    engine = Engine.create(session_id=session_id, max_rounds=args.max_rounds)
    result = await engine.run(query)

    print(f"session_id: {result['session_id']}")
    feedback = result.get("coverage_feedback", {})
    if isinstance(feedback, dict):
        print(f"coverage_feedback: {feedback.get('summary', '')}")
    print(f"status: {result['status']}")
    print(f"final_path: {result['final_path']}")
    print(f"review_path: {result['review_path']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run session-based plan/execute pipeline")
    parser.add_argument("--query", type=str, default="", help="User query")
    parser.add_argument(
        "--query-index",
        type=int,
        default=0,
        help="Default query index when --query is empty",
    )
    parser.add_argument("--session-id", type=str, default="", help="Session ID")
    parser.add_argument("--max-rounds", type=int, default=3, help="Max replan rounds")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
