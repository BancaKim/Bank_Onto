# 지식 계약 (Knowledge Contract) — 지식층이 LLM 추론을 제한하는 방식

Bank_Onto의 지식층은 검색(retrieval)만 제공하는 것이 아니라, 에이전트가 따라야
하는 **작동 계약**이다. 이 문서는 그 계약의 구조와 계보를 기록한다.

## 불변식 (invariant chain)

```
공개 원문 (금감원 공시 · 법령 조문)
  → SHACL 품질 게이트 (shapes/shapes.ttl — 계약 위반 데이터는 지식층 진입 불가)
  → 온톨로지 지식층 (KB)
  → 규칙 추출 (knowledge/rules.py — 정규식 기반, 결정적, LLM 불개입)
  → 판단 패킷 (3값 논리 verdict + 근거 좌표)
  → 에이전트 응답 계약 (verdict를 뒤집을 수 없음, UNKNOWN이면 보류)
  → 근거가 표기된 답변
```

어느 단계에서도 LLM이 사실이나 결론을 만들지 않는다. LLM의 역할은 도구 선택과
자연어 설명뿐이다.

## 계보

| 구성 요소 | 출처 | 이식한 것 |
|---|---|---|
| 3값 논리 판단 패킷 | research_paper `rule_engine.py` | "엔진이 판단하고 LLM은 설명만 한다" — 참·거짓·**미상**, 사실이 없으면 거짓이 아니라 미상, 인식 상태 우선순위(NOT_APPLICABLE→DENIED→UNKNOWN→CONFIRMED) |
| 온톨로지 = 작동 계약 | [SEOCHO](https://github.com/TTEON/seocho) | "ontology → evidence → trace → supported answer" 불변식, 데이터 쓰기를 shape로 제약, 모든 판단이 통과하는 단일 관문 |
| 기호적 지식층 | Bank_Onto 고유 | 규칙 추출까지 LLM 불개입 (SEOCHO·논문은 LLM 추출+검증, 우리는 구조화 원천 직접 적재) |

## 규칙 계층 (knowledge/rules.py)

- **추출**: 적재된 공시 필드에서 결정적으로 추출 — 연령(joinMember), 가입 경로
  (joinWay), 최소 금액(etcNote), 만기별 우대금리 상한(금리옵션). 은행권 211개
  상품 전체에 대해 상품별 규칙 사전을 구성한다.
- **판단**: `RuleBook.evaluate(bank, product, facts)` →
  `{verdict, conditions[], missing_slots[], evidence[], contract}`.
  facts에 없는 슬롯은 **미상**이며, 미상은 DENIED가 아니다. 단 하나라도 위반이
  확정되면 사실 부족과 무관하게 DENIED다.
- **금리 주장 검증**: `check_rate_claim(bank, product, claimed, months)` —
  "우대금리 X% 이상인가" 주장을 공시 값과 결정적으로 비교.

## 에이전트 계약 (agent/bank_agent.py · knowledge/tools.py)

`check_product_eligibility` / `check_rate_claim` 도구가 판단 패킷을 반환하며,
시스템 프롬프트가 다음을 강제한다:

1. 가입 가능·요건 충족·금리 주장 질문에는 반드시 판단 도구를 호출한다.
2. verdict가 CONFIRMED/DENIED이면 결론과 근거를 그대로 전달한다 — 뒤집기 금지.
3. UNKNOWN이면 단정하지 않고 missing_slots의 정보를 요청한다.
4. NOT_APPLICABLE이면 지식층에 없음을 밝히고, 일반 지식 답변임을 구분 표기한다.

## 검증

- **교차 검증** (tests/test_rules.py): 규칙 엔진이 Bench v2.2의 판정형 gold
  148건(연령 32 + 연령×경로 32 + 금리 임계 84)을 **100% 재현**한다. 벤치마크
  생성기와 규칙 엔진은 같은 원문에서 독립적으로 판정을 산출하므로, 일치는 두
  구현이 모두 원문에 충실하다는 상호 증명이다.
- **SHACL 게이트** (scripts/validate.py [5]단계): 공시 상품(이름·은행 연결),
  금리옵션(0~30% 범위, 만기 1~120개월), 법령 조문(번호·본문·소속) 계약을
  적재 데이터 전체가 준수함을 커밋 전마다 검사한다.

## 남은 로드맵

- 규칙의 TTL 물질화 (`rules:` 모듈로 그래프에 적재 → SPARQL로 규칙 조회)
- 법령 개정 이력 모듈 → 시간 축 판정(OUTDATED 상태) 활성화 — research_paper의
  버전드 규칙 191개 이식이 지름길
- 답변 계층 평가에서 패킷 유무 비교 (P2 vs B2 방식 — research_paper 설계 재사용)
