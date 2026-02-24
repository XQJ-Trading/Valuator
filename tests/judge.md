# Judge Protocol

## 이 문서의 역할

이 문서는 종료된 세션(`valuator/sessions/S-*`)을 분석할 때 따르는 프로토콜이다.
코드가 아니라 **사고 절차**이며, 모든 산출물은 세션 내 `judge/` 디렉토리에 md 파일로만 기록한다.

핵심 질문은 하나다:
> **세션의 `final.md`가, baseline 결과물이 제공하는 투자 의사결정 품질을 온전히 보존하면서 더 나은 정보를 주는가?**

여기서 baseline은 파이프라인에 주입하는 입력이 아니라, final.md를 사후에 평가하기 위한 **외부 잣대(골드 리포트)**다.
Reviewer 클래스는 파이프라인 안에서 구조적 품질(query/execution coverage, status)을 이미 판단하고 있고,
이 judge는 그 위에 **"baseline 대비 의사결정 품질"이라는 별도 렌즈**를 얹는 것이다.

---

## Hard Constraints

- baseline이 전달하는 핵심 주장·팩트·리스크·트리거를 final.md가 누락하면, 어떤 추가 인사이트가 있어도 pass가 아니다.
- baseline 완전 보존은 **최소 조건**이다. 그 위에서 강화가 있어야 비로소 "개선"이다.
- 산출물은 md 파일만 작성한다. 코드 변경, JSON 생성, 스크립트 실행 없음.
- 날짜는 상대 표현(`최근`, `지난 분기`)이 아니라 절대 표현(`2025Q3`, `2026-01-08`)을 쓴다.

---

## Inputs

기본 모드(결과물 비교)에서 읽는 것:

| 용도 | 경로 | 읽는 이유 |
| :-- | :-- | :-- |
| 유저 원문 | `input/user_input.md` | query의 원래 의도 파악 |
| 골드 기준 | `tests/v1.5_testset.yaml` 대응 baseline | final.md를 어떤 잣대로 볼지 결정 |
| 평가 대상 | `output/final.md` | 실제 판정 대상 |
| 구조 리뷰 참고 | `review/latest.json` | Reviewer가 이미 내린 coverage/status 확인 |

선택 모드(정보 손실 원인 추적)에서 추가로 읽는 것:

| 용도 | 경로 | 읽는 이유 |
| :-- | :-- | :-- |
| Leaf 리서치 | `execution/round-*/outputs/*/result.md` | 실행 단계에서 수집된 팩트 원본 |
| Root 집계 | `aggregation/round-*/T-ROOT/report.md` | 어디서 압축/소실이 일어났는지 추적 |

기본 모드만으로 verdict를 내릴 수 있다.
선택 모드는 "어디서 깨졌는지"까지 알고 싶을 때만 켠다.

---

## Outputs (`sessions/S-*/judge/`)

| 파일 | 생성 조건 | 역할 |
| :-- | :-- | :-- |
| `context.md` | 항상 | 세션 문맥, baseline 레퍼런스, 평가 전제 |
| `baseline_coverage.md` | 항상 | baseline vs final 요구사항별 커버리지 매트릭스 |
| `info_loss_audit.md` | 선택 모드일 때 | leaf→root→final 경로별 팩트 손실 추적 |
| `quant_review.md` | 항상 | 퀀트 5축 정성 리뷰 |
| `verdict.md` | 항상 | 최종 판정 + 핵심 발견 + 필요 수정 |
| `final_rewrite_proposed.md` | verdict가 revise/fail일 때 | 구체적 리라이팅 방향 제안 |

---

## Evaluation Protocol

### Step 1. 세션 문맥 파악 → `context.md`

읽을 것: `input/user_input.md`, `review/latest.json`, baseline case.

기록할 것:
- 세션 id, query 원문 요약 (1~2문장)
- 대응 baseline case id 및 baseline 리포트 제목/시점
- Reviewer가 이미 내린 구조적 판단 요약 (query_coverage, execution_coverage, status)
- judge 평가에서 전제하는 것들 (예: "baseline은 2025Q3 실적 + 2026 전망 기준으로 작성됨")

이 파일은 이후 모든 judge 파일의 **앵커**다. 다른 파일에서 반복 서술하지 않고 여기를 참조한다.

---

### Step 2. Baseline vs Final 비교 → `baseline_coverage.md`

**사고 방식**: baseline 리포트를 처음부터 끝까지 읽으면서, "이 리포트가 투자 의사결정을 위해 제공하는 핵심 주장/팩트/프레임"을 머릿속에서 추린다.
그 각각에 대해 final.md에서 대응하는 내용을 찾는다.

별도 스펙 파일로 분해해 저장하지 않는다. baseline을 읽는 행위 자체가 분해이고, 그 결과는 곧바로 Coverage Matrix로 나온다.

**Coverage Matrix 구조**:

```
| ID | Baseline이 제공하는 것 | Final 상태 | Evidence | Impact |
```

- **ID**: `B-01`, `B-02`, ... 순번.
- **Baseline이 제공하는 것**: baseline 리포트에서 투자 판단을 움직이는 핵심 단위.
  - 단순 정보 나열이 아니라, "이것이 없으면 어떤 의사결정이 불가능해지는지"를 내포하는 문장으로 쓴다.
  - 예: "NA/Intl/AWS 세그먼트별 매출·이익·마진 정량표 → 포트폴리오 비중 판단의 기초 좌표"
- **Final 상태**: `Present` / `Partial` / `Missing`
  - `Present`: baseline과 동등하거나 더 나은 수준으로 존재.
  - `Partial`: 방향은 맞지만 디테일·정합성·시점이 약화됨.
  - `Missing`: 해당 내용이 final에 없거나, 있어도 의사결정에 쓸 수 없는 수준.
- **Evidence**: final.md 내 구체 위치 (섹션명, 줄 번호, 표 제목 등). Missing이면 "해당 없음".
- **Impact**: 이 상태가 투자 판단에 미치는 영향. **단순히 "누락됨"이 아니라, "이것 때문에 어떤 판단이 틀어질 수 있는지"**를 쓴다.
  - 예: "세그먼트 수치표 부재 → AWS 이익 기여도를 정량적으로 비교할 수 없어, 밸류에이션 배수 적용 근거가 사라짐"

**추가로 기록할 것: Baseline을 넘어선 부분**

Coverage Matrix 아래에 별도 섹션으로:
- final.md에는 있지만 baseline에는 없는 **추가 인사이트/구조/해석**을 `Added` 라벨로 적는다.
- 각 항목에 대해: "이것이 투자 의사결정에 실질적으로 기여하는 추가 가치인지, 아니면 장식인지"를 판단한다.

이 섹션이 있어야 **"baseline을 보존했는가"와 "baseline보다 나아졌는가"를 동시에** 볼 수 있다.

---

### Step 3. (선택) 정보 손실 원인 추적 → `info_loss_audit.md`

기본 모드에서는 Step 2의 Coverage Matrix에서 `Partial/Missing`인 항목들이 곧 "정보 차이"다.
여기서 더 파고 싶을 때 — 즉, **"왜 빠졌는지, 파이프라인 어느 레이어에서 깨졌는지"**를 알고 싶을 때만 이 파일을 만든다.

추적 경로:
- **Path A**: `execution/round-*/outputs/*/result.md` → `aggregation/round-*/T-ROOT/report.md`
  - leaf에서 수집한 팩트가 root 집계에서 살아남았는가?
- **Path B**: `aggregation/round-*/T-ROOT/report.md` → `output/final.md`
  - root에서 살아남은 팩트가 최종 문서에서도 살아남았는가?

**Critical Fact Trace 구조**:

```
| ID | Critical fact (source) | Root 존재 | Final 존재 | Assessment | 손실 원인 |
```

- **Assessment**: `Retained` / `Weakened` / `Lost`
- **손실 원인** (Lost일 때만): 요약 압축 / 병합 충돌 / 우선순위 누락 / 기타
  - 이 원인이 있어야 "aggregation 전략을 고칠지, final writer 프롬프트를 고칠지, leaf task 설계를 고칠지"를 구분할 수 있다.

핵심 인사이트:
- 손실이 Path A에 집중되면 → aggregation 선택 로직의 문제.
- 손실이 Path B에 집중되면 → final 요약 전략의 문제.
- 양쪽 다면 → 구조적 설계 재검토 필요.

---

### Step 4. 퀀트 도메인 정성 리뷰 → `quant_review.md`

baseline을 **암묵적 기준선**으로 두고, final.md가 퀀트 투자 문서로서 각 축에서 baseline 대비 어디에 있는지를 평가한다.
숫자 점수를 매기지 않는다. 대신, 각 축에 대해 **"지금 상태 / 왜 문제인지 / 뭘 바꿔야 하는지"**를 구체적으로 쓴다.

#### 축 1: Time Alignment (기준 시점 정합성)

봐야 할 것:
- final.md가 명시하는 기준 시점(분기/연도)과 baseline의 기준 시점이 일치하는가.
- 본문에서 사용하는 수치들이 해당 시점의 것인가, 아니면 과거 데이터를 현재인 것처럼 쓰고 있는가.
- 전망 기간(예: 2026 연간)과 실제 분석에 사용된 데이터 윈도우가 정합하는가.

왜 중요한가:
- 시점이 어긋나면 멀티플·성장률·ROIC 해석이 자동으로 왜곡된다.
- 투자자가 "이건 언제 기준이지?"를 물어야 하는 순간, 문서의 의사결정 가치는 0에 수렴한다.

#### 축 2: Segment Economics (세그먼트 경제성)

봐야 할 것:
- 사업부별 매출·이익·마진이 baseline과 동일한 프레임(같은 세그먼트 정의, 같은 시점)으로 제시되는가.
- 단순 카테고리 나열이 아니라, **세그먼트 간 마진 차이가 전체 밸류에이션에 미치는 함의**까지 연결되는가.
- 혼합 마진(blended margin)의 방향이 어느 세그먼트에 의해 결정되는지 명확한가.

왜 중요한가:
- 세그먼트 경제성은 포트폴리오 비중 결정의 기초 좌표다.
- 세그먼트별 수치가 없으면 "전체 매출 성장 X%"라는 숫자는 아무것도 설명하지 못한다.

#### 축 3: Capital Efficiency (자본 효율성)

봐야 할 것:
- Capex가 총액 한 줄로 끝나지 않고, 성격별로 분리되는가 (예: 유지 Capex vs 성장/AI Capex).
- Capex → 매출/이익 전환의 시간축이 명시되는가 (투자 집중기 vs 회수기).
- FCF, ROIC, 또는 그에 준하는 자본 회수 지표가 Capex 논의와 연결되는가.

왜 중요한가:
- "Capex X억 달러"만 있으면, 그게 가치 창출인지 가치 파괴인지 판단할 수 없다.
- 투자 집중기에 FCF가 압박받는 건 자연스럽지만, 그 압박의 기간과 강도를 프레이밍하지 않으면 리스크 해석이 왜곡된다.

#### 축 4: Risk Transmission (리스크 손익 전이)

봐야 할 것:
- 리스크가 단순히 "존재한다"로 끝나지 않고, **P&L/현금흐름/밸류에이션의 어떤 라인아이템에 어떻게 전이되는지** 경로가 있는가.
- 규제 리스크라면: 어떤 규제 → 어떤 사업 행위 변경 → 어떤 매출/비용 항목에 영향 → 마진/FCF에 얼마나.
- 매크로 리스크라면: 어떤 경제 변수 → 어떤 수요/비용 경로 → 세그먼트별 영향 차이.

왜 중요한가:
- "FTC 리스크가 있다"는 뉴스 요약이다.
- "FTC가 Buy Box 알고리즘 변경을 강제하면, 광고 단가가 X% 하락하고 Retail OPM이 Y%p 압축된다"는 투자 분석이다.
- 후자가 없으면 리스크 섹션은 읽는 사람의 불안만 키우고, 행동 기준은 주지 못한다.

#### 축 5: Actionability (실행 가능성)

봐야 할 것:
- 결론이 "좋다/나쁘다"의 서술적 요약에 머무르지 않고, **구체적인 행동 전환 조건(트리거)**이 명시되는가.
- Bull/Bear 시나리오가 "가능성 나열"이 아니라, **관측 가능한 지표와 임계치**로 정의되는가.
  - 예: "AWS QoQ 성장률이 20% 이상 유지되고, NA Retail OPM이 4% 이상이면 비중확대"
- 매수/보류/축소의 기준이 명확해서, 다른 투자자가 같은 문서를 읽고 같은 행동 규칙에 도달할 수 있는가.

왜 중요한가:
- 결론이 행동으로 연결되지 않으면, 분석 문서가 아니라 에세이다.
- 동일 문서를 읽고 상반된 행동을 취할 수 있다면, 그건 분석의 품질 결함이다.

---

### Step 5. 최종 판정 → `verdict.md`

**판정 로직** (순서가 중요하다):

1. **먼저 baseline 커버리지를 본다.**
   - Coverage Matrix에서 `Missing`이 하나라도 있고, 그 Impact가 투자 판단 핵심에 닿으면 → **pass 불가**.
   - `Partial`이 다수이고, 그 약화가 누적되어 의사결정 프레임 자체를 흔들면 → **pass 불가**.

2. **baseline을 보존했다면, 그 위에서 개선을 본다.**
   - 5축 중 **과반(3축 이상)**에서 baseline 대비 동등 이상이고, 나머지에서도 심각한 후퇴가 없으면 → **pass 후보**.
   - `Added` 항목 중 투자 의사결정에 실질 기여하는 추가 가치가 있으면 → **pass 강화 근거**.

3. **판정 기준**:
   - `pass`: baseline 핵심 보존 + 퀀트 5축에서 동등 이상 + 실행 가능성(Actionability)이 baseline만큼 또는 그 이상.
   - `revise`: baseline 핵심의 대부분은 살렸지만, 특정 축(특히 Actionability/Risk Transmission/Capital Efficiency)에서 부족해 재작성하면 개선 가능.
   - `fail`: baseline의 핵심 사실·리스크·트리거를 훼손해, final.md로는 투자 의사결정을 내릴 수 없거나, baseline보다 나쁜 판단을 유도할 수 있음.

**verdict.md 구조**:

- **Status**: pass / revise / fail
- **Core Findings**: 핵심 진단 3~5개. "무엇이 맞고 무엇이 틀렸는지"를 직설적으로.
- **Baseline Gaps**: Coverage Matrix에서 `Missing/Partial`인 항목 요약 + 누적 Impact.
- **Information Difference**: baseline 대비 Lost/Added 중 verdict에 영향을 준 것만 요약.
- **Actionability Review**: 결론의 행동 전환 가능성에 대한 1~2문단 진단.
- **Required Revisions** (revise/fail일 때): 수정 항목별로 **완료 조건(acceptance criteria)**을 명시.
  - 예: "세그먼트 정량표를 2025Q3 기준으로 본문에 삽입한다. 표에는 NA/Intl/AWS 각각의 매출·영업이익·OPM이 포함되어야 한다."

---

### Step 6. (조건부) 리라이팅 방향 제안 → `final_rewrite_proposed.md`

verdict가 `revise` 또는 `fail`일 때만 작성한다.

`verdict.md`의 Required Revisions를 **실제 문단 구조·샘플 문장 수준**으로 전개한다.
퀀트 5축 순서로 섹션을 나누되, 해당 축에 수정 사항이 없으면 스킵한다.

각 섹션에서:
- 현재 final.md의 해당 부분이 어떤 상태인지 1~2문장으로 진단.
- baseline이 보여주는 수준을 참조해, **"이렇게 바뀌어야 한다"**는 방향을 구체적으로 제시.
- 가능하면 문장/표의 골격을 예시로 제시하되, 실제 데이터를 날조하지 않는다.

---

## Qualitative Insight Checklist

모든 judge 파일을 작성한 후, 최종 자기 점검용으로 아래를 확인한다:

- [ ] 기준 시점이 문서 전반에서 일관적인가 (final.md 안에서도, baseline과의 비교에서도)
- [ ] Bull/Bear가 서술적 슬로건이 아니라, 관측 가능한 지표+임계치로 연결되는가
- [ ] 리스크가 "존재" 수준이 아니라, 손익 영향 경로(어떤 라인아이템에 얼마나)로 해석되는가
- [ ] 결론이 실제 의사결정(매수/보류/축소)으로 바로 연결되고, 전환 조건이 명시되는가
- [ ] Coverage Matrix의 Impact 열이 "누락됨" 수준에 머물지 않고, 투자 판단 왜곡을 구체적으로 서술하는가
- [ ] verdict의 Required Revisions가 모호하지 않고, 완료 조건이 검증 가능한가
