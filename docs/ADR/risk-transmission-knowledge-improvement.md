# Plan: risk_transmission knowledge.md 개선

## Context

Judge 5축 비교에서 Report B(파이프라인 산출물)의 약점 3개가 식별됨:
- **Segment Economics: Below** — 자산군별 정량 표 부재
- **Actionability: Below** — 시나리오 트리거는 있으나 포트폴리오 행동 전환 조건 부재
- **Capital Efficiency: Equal** — FCF/ROIC 연결 문장 부재

Report B의 강점(Risk Transmission: Above)은 유지하면서 위 약점을 보완한다.

## 근본 원인

| 약점 | 근본 원인 | 파이프라인 전파 경로 |
|------|----------|---------------------|
| Segment Economics | Format spec에 표 구조 요구 없음 | `knowledge.md ## Format` → `domain_tool.py:37 [FORMAT]` → LLM |
| Actionability | `monitoring_triggers`가 MEDIUM priority → `_evidence_by_priority()`에서 첫 문장으로 절삭 (service.py:706-708). description도 "감시"에 머묾 | `knowledge.md ## Aspects` → `executor/service.py:283-316` → `domain_tool.py:29 [RUBRIC_ASPECTS]` + aggregator priority 절삭 |
| Capital Efficiency | `demand_risk` description이 OPM까지만 연결, FCF/ROIC 미언급 | 동일 경로 |

## 접근법 선택

| 접근법 | 변경 범위 | 타 쿼리 영향 | 코드 변경 |
|--------|----------|-------------|----------|
| **A) knowledge.md만 수정** | risk_transmission 모듈만 | 없음 | 0줄 |
| B) knowledge.md + 집계 루트 프롬프트 | 모든 쿼리 | 있음 (CEO/DCF에 자산군표 강제) | ~5줄 |
| C) 새 모듈 추가 | 전역 | 있음 | ~100줄 + 파일 3개 |

**선택: A** — 코드 변경 0줄, 영향 범위 최소, CLAUDE.md 원칙("가장 단순한 동작 해법") 부합.

## 변경 사항: `risk_transmission/knowledge.md`

### 1. monitoring_triggers: MEDIUM → HIGH 승격 + description 재정의

```markdown
# 변경 전
### monitoring_triggers — 모니터링 트리거 [MEDIUM]
감시해야 할 선행지표, 임계치, 재평가 트리거와 대응 포인트

# 변경 후
### monitoring_triggers — 포트폴리오 행동 전환 조건 [HIGH]
리스크별 관측 가능 지표(가격, 금리, 지수, 환율 등)의 수치 임계치와 해당 임계치 도달 시 포트폴리오 행동(비중 확대/보유/축소/헤지) 전환 조건
```

**이유**:
- HIGH 승격 → aggregator `_evidence_by_priority`에서 전문 보존 (절삭 해소)
- description에 "포트폴리오 행동 전환 조건"이 명시되면 DomainTool이 단순 모니터링 → 행동 조건으로 출력 변경

### 2. demand_risk: FCF/ROIC 연결 추가

```markdown
# 변경 전
### demand_risk — 수요·가격 리스크 [HIGH]
수요 둔화, 가격 경쟁, 믹스 변화가 매출총이익과 operating leverage에 미치는 영향

# 변경 후
### demand_risk — 수요·가격 리스크 [HIGH]
수요 둔화, 가격 경쟁, 믹스 변화가 매출총이익, operating leverage, FCF/ROIC에 미치는 영향
```

**이유**: "FCF/ROIC" 한 단어 추가로 Capital Efficiency 축 개선. check `cash_flow_linked`("현금흐름 line item 연결")과 정합.

### 3. Format spec: 정량 요약표 구조 추가

```markdown
# 추가할 2줄
- 자산군/섹터별 영향을 표로 정리한다: | 자산군 | 영향 방향 | 주요 트리거 | 수치 구간 |
- monitoring_triggers에서 관측 지표별 임계치-행동 대응표를 포함한다: | 지표 | 임계치 | 포트폴리오 행동 |
```

**이유**: format_spec → `domain_tool.py:37 [FORMAT]`으로 직접 전달. 표 구조 명시 → Segment Economics + Actionability 동시 개선.

### 4. Check `monitoring_defined`: 행동 전환 조건 요구 강화

```markdown
# 변경 전
- **monitoring_defined**: 모니터링 트리거와 영향 범위가 제시되어야 한다.
  → monitoring_triggers, financing_fx_risk

# 변경 후
- **monitoring_defined**: 관측 가능 지표의 수치 임계치와 포트폴리오 행동 전환 조건이 제시되어야 한다.
  → monitoring_triggers, financing_fx_risk
```

**이유**: check text → `_domain_contract_section` → aggregator `[DOMAIN_REPORT_CONTRACT]`로 전파. 집계 LLM이 contract 충족 시 행동 전환 조건표 생성.

### 5. Check `cash_flow_linked`: FCF/ROIC 명시

```markdown
# 변경 전
- **cash_flow_linked**: 현금흐름 line item 연결이 포함되어야 한다.
  → demand_risk

# 변경 후
- **cash_flow_linked**: 현금흐름 line item 연결과 FCF/ROIC 영향이 포함되어야 한다.
  → demand_risk
```

## 수정 대상 파일

- `valuator/domain/knowledge/modules/risk_transmission/knowledge.md` — **유일한 수정 파일**

## 기대 효과 (Judge 5축)

| 축 | 변경 전 | 기대 | 변경 근거 |
|----|---------|------|----------|
| Time Alignment | Equal | Equal (유지) | 변경 없음 |
| Segment Economics | Below | **Equal~Above** | Format spec 표 구조 요구 |
| Capital Efficiency | Equal | **Equal~Above** | demand_risk + cash_flow_linked에 FCF/ROIC 명시 |
| Risk Transmission | Above | **Above (유지)** | 기존 3 HIGH aspects + persona 그대로 |
| Actionability | Below | **Equal~Above** | monitoring_triggers HIGH 승격 + 행동 전환 조건 description + 표 구조 |

## 리스크

| 리스크 | 영향 | 완화 |
|--------|------|------|
| monitoring_triggers HIGH 승격 → 토큰 증가 | 미미 (3H+2M → 4H+1M) | 실측 비교 |
| 단일 기업 쿼리에서도 자산군표 생성 | 리스크 전이 맥락에서 유용 | format spec이 "자산군/섹터별"이므로 해당 없으면 LLM이 생략 |
| LLM이 표 구조를 무시 | Segment Economics 미개선 | reviewer gating이 below 시 revise 강제 |

## 검증

1. `python -m valuator.domain.validate` — 모듈 로드 + 교차 참조 검증 통과 확인
2. 동일 이란-미국 전쟁 쿼리로 파이프라인 재실행 → final.md에서:
   - 자산군/섹터별 영향 표 존재 여부
   - 관측 지표 × 임계치 × 포트폴리오 행동 대응표 존재 여부
   - FCF/ROIC 연결 문장 1개+ 존재 여부
3. `python -m pytest tests/test_domain_loader.py` — knowledge.md 파싱 회귀 테스트
