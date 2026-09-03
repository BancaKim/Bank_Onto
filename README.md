# Bank_Onto: 은행권 온톨로지 (Banking Ontology)

FIBO(Financial Industry Business Ontology)의 설계 원칙을 따라 구축한 **한국 은행 도메인 온톨로지**입니다.
OWL 2 / Turtle 형식으로 작성되었으며, 모든 개념에 한국어·영어 레이블과 한국어 정의(skos:definition)를 포함합니다.

## FIBO와의 관계

FIBO는 EDM Council이 관리하는 금융산업 표준 온톨로지로, 도메인별 모듈 구조(FND, BE, FBC, LOAN 등)를 가집니다.
본 온톨로지는 FIBO의 구조와 패턴을 차용하되, 한국 은행권 실무 개념(전세자금대출, LTV/DTI/DSR, 예금자보호,
휴면계좌, 오픈뱅킹, KoFIU 보고 등)을 반영하여 독자적으로 설계했습니다. 주요 클래스에는 `rdfs:seeAlso`로
대응하는 FIBO IRI를 연결해 두었습니다.

핵심 설계 패턴:

- **모듈형 구조** — 도메인별 독립 모듈을 `owl:imports`로 결합 (FIBO의 도메인-모듈 체계)
- **당사자-역할(Party-Role) 패턴** — 한 사람이 예금주이면서 동시에 차주일 수 있도록, 당사자(Party)와
  역할(PartyRole)을 분리 (FIBO FND의 핵심 패턴)
- **상품-계약-계좌 분리** — 상품(템플릿) → 계약(법적 관계) → 계좌(운영 단위)를 구분

## 모듈 구성

| 모듈 | 파일 | FIBO 대응 | 주요 내용 |
|---|---|---|---|
| 통합 | `ontology/bank-onto.ttl` | (진입점) | 모든 모듈 import |
| 기반 | `ontology/bank-core.ttl` | FND | 계약, 금액, 통화, 이자율, 식별자, 기간 |
| 당사자 | `ontology/parties.ttl` | BE | 은행(시중/지방/인터넷전문/특수), 고객, 역할(예금주·차주·보증인) |
| 상품 | `ontology/products.ttl` | FBC | 수신(보통예금·정기예금·적금·MMDA), 여신, 카드, 외환 상품 |
| 계좌 | `ontology/accounts.ttl` | FBC/CAE | 예금·대출·가상계좌, 계좌 상태(정상·휴면·지급정지·해지) |
| 여신 | `ontology/loans.ttl` | LOAN | 대출계약, 담보·보증, 상환방식, 신용평가, LTV/DTI/DSR, 자산건전성 분류 |
| 거래 | `ontology/transactions.ttl` | — | 입출금·이체·카드결제·외환거래, 채널(영업점·ATM·모바일·오픈뱅킹) |
| 리스크·규제 | `ontology/risk-compliance.ttl` | — | 리스크 유형, 바젤 자본규제(BIS·LCR), AML/KYC, STR/CTR, 예금자보호 |

네임스페이스: `https://w3id.org/bank-onto/<module>/`

## 저장소 구조

```
Bank_Onto/
├── ontology/          # 온톨로지 모듈 (.ttl)
├── knowledge/         # 에이전트 Knowledge Layer
│   ├── kb.py          #   BankKnowledgeBase: 검색·정의·계층·인스턴스·SPARQL 조회 API
│   └── tools.py       #   Claude 에이전트 도구 6종 (@beta_tool)
├── agent/
│   └── bank_agent.py  # Claude API tool runner 기반 은행 상담 에이전트
├── examples/
│   ├── sample-instances.ttl   # 가상 시나리오 인스턴스 (한빛은행 · 김민준)
│   └── queries.sparql         # SPARQL 예시 쿼리 5종
├── scripts/
│   ├── validate.py    # 구문·무결성·레이블 검증
│   └── query.py       # 예시 쿼리 실행기
├── tests/
│   └── test_knowledge_layer.py  # Knowledge layer 테스트 (API 키 불필요)
└── docs/
    └── architecture.md        # 설계 문서
```

## 시작하기

```bash
pip install -r requirements.txt

# 온톨로지 검증 (구문, 미정의 참조, 한국어 레이블 누락 검사)
python scripts/validate.py

# 예시 SPARQL 쿼리 실행
python scripts/query.py

# Knowledge layer 테스트 (API 키 불필요)
python tests/test_knowledge_layer.py
```

## 은행 에이전트 Knowledge Layer

`knowledge/` 패키지는 온톨로지를 LLM 에이전트의 지식 계층으로 노출합니다.

**`BankKnowledgeBase`** (`knowledge/kb.py`) — 온톨로지+인스턴스 그래프에 대한 조회 API:

| 메서드 | 용도 |
|---|---|
| `search_concepts("대출")` | 한국어/영어 레이블·정의 부분 일치 검색 |
| `get_concept("주택담보대출계약")` | 정의, 상위/하위 클래스, 상속 포함 관련 속성, FIBO 참조 |
| `get_hierarchy("LoanProduct")` | 하위 분류 트리 ("어떤 종류의 대출이 있나?") |
| `get_instances("Account")` | 클래스(하위 클래스 포함)의 인스턴스 목록 |
| `describe_instance("ex:KimMinjun")` | 인스턴스의 모든 속성-값과 역참조 |
| `run_sparql(query)` | 임의 SPARQL SELECT (프리픽스 자동 바인딩) |

개념 이름은 qname(`loans:LTV`), 로컬명(`LTV`), 한국어 레이블(`담보인정비율(LTV)`) 어느 형태로도 해석됩니다.

**Claude 에이전트 도구** (`knowledge/tools.py`) — 위 API를 Anthropic SDK tool runner용
`@beta_tool` 함수 6종으로 노출: `search_banking_concepts`, `get_concept_details`,
`get_class_hierarchy`, `list_instances`, `describe_instance`, `run_sparql_query`.

**에이전트 실행** (`agent/bank_agent.py`):

```bash
export ANTHROPIC_API_KEY=...   # 또는 `ant auth login` 프로필

# 단일 질문
python agent/bank_agent.py "주택담보대출 받으려면 어떤 규제비율이 적용되나요?"

# 대화형 모드
python agent/bank_agent.py
```

에이전트는 시스템 프롬프트에 의해 은행 개념 답변을 온톨로지 조회 결과에 근거하도록
제약되며, 근거 개념의 URI를 답변에 표기합니다. 자체 에이전트에 통합하려면
`knowledge.tools.BANK_KB_TOOLS`를 tool runner의 `tools`에 전달하면 됩니다.

[Protégé](https://protege.stanford.edu/)에서 `ontology/bank-onto.ttl`을 열면 전체 모듈을 탐색할 수 있습니다
(로컬 파일 import를 위해 catalog 설정이 필요할 수 있습니다).

## 예시 시나리오

`examples/sample-instances.ttl`은 다음 가상 시나리오를 인스턴스로 표현합니다:

1. 가상의 **한빛은행**(시중은행, 금융감독원 감독)
2. 고객 **김민준**이 예금주 역할로 **정기예금**(연 3.5%, 예금자보호) 가입
3. 동일인이 차주 역할로 **주택담보대출**(COFIX 연동 변동금리, LTV 60%, 원리금균등, 30년) 실행
4. 모바일뱅킹 채널을 통한 **계좌이체** 및 **KYC 고객확인**(저위험) 수행

## 벤치마크: 벡터 RAG vs Graph RAG(LPG) vs 온톨로지 RAG

`eval/`은 같은 지식을 세 가지 검색 패러다임으로 제공했을 때의 성능을
2계층(검색/답변)으로 비교합니다. 결과: [docs/benchmark-report.md](docs/benchmark-report.md).

**검색 계층** (근거 재현율 — 파이프라인 품질의 상한, LLM 없이 결정적):

| 지표 (18문항) | 벡터 RAG | Graph RAG(LPG) | 온톨로지 RAG |
|---|---|---|---|
| 근거 재현율 | 69% | 92% | **100%** |
| 답 없는 질문에 준 오답 재료 | 2,020자 | 0자 | **0자** |

LPG(속성 그래프, Neo4j식 k-hop 이웃 탐색)는 다중 홉·열거에서 벡터를 크게 앞서지만,
속성 스키마(domain/range)와 SPARQL 집계가 없어 스키마 질의·조건 필터에서 실패합니다
— 이 격차가 온톨로지 의미론의 순수 기여분입니다.

**답변 계층** (동일 LLM, 컨텍스트 공급 방식만 상이 — API 키 필요):

```bash
python eval/run_retrieval_eval.py            # 검색 수준 3-way (API 키 불필요)
python eval/run_answer_eval.py               # 답변 수준 3-way: 객관식 + LLM 심판 + 유사도
python eval/run_answer_eval.py --scoring mcq # 객관식만 (결정적 채점, 심판 편향 없음)
```

객관식 20문항(`eval/mcq_questions.py`)은 정답 기호 일치로 결정적 채점되고,
자유 답변은 LLM-as-judge(0~2점)와 TF-IDF 유사도(보조)로 채점됩니다.

벡터 RAG가 구조적으로 지는 지점: 다중 홉 관계 추적(청킹이 연결을 절단),
분류 완전 열거(top-k는 완전성 미보장), 조건 필터/집계(유사도는 조건 평가가 아님),
환각 방지(답이 없어도 top-k를 반환). 자세한 해석과 공정성 한계는 리포트 참고.

## RAG 시나리오 매트릭스 (Chen et al. 2026 "Is GraphRAG Needed?" 구도)

`eval/scenarios.py`는 논문의 9-시나리오 비교를 같은 지식층 위에 이식한 것이다:
기본 RAG 변형 4종(청크 / 개체 문서 / 관계 문서 / 결합) → 하이브리드 텍스트-그래프
→ 사전정의 KG(LPG) → 온톨로지 → 컨텍스트 엔지니어링(CE) 2종. Bench v2 880문항,
결정적 채점. 결과: [docs/scenario-report.md](docs/scenario-report.md).

| 시나리오 | R@4K | R@∞ | 평균 컨텍스트 |
|---|---|---|---|
| S1 기본 청크 RAG | 82% | 89% | 8K자 |
| S6 Graph RAG (LPG) | 85% | 99% | 34K자 |
| S7 온톨로지 (원시) | 71% | 99% | 114K자 |
| **S9 온톨로지 + CE** | **87%** | 99% | 53K자 |

논문의 두 관찰이 그대로 재현된다: ① 그래프 계열은 예산 없이는 근거를 다 가져오지만
(99%) **컨텍스트 과잉**으로 실제 예산(4K자) 안에서는 원시 온톨로지가 기본 청크보다
못하며, ② 컨텍스트 엔지니어링이 이를 뒤집는다(71%→87%, 컨텍스트 54% 절감).
검색 지표만으로는 LPG와 온톨로지의 차이가 2%p라, 온톨로지의 본 강점(SPARQL·규칙
판정으로 답을 *연산*)은 답변 계층에서 재야 한다 — `eval/run_scenario_answer_eval.py`
(S1~S9 + 에이전틱 A1/A2, `answer_type`별 결정적 채점, API 키 필요).

```bash
python eval/run_scenario_eval.py                 # 검색 계층 9-시나리오 (키 불필요, ~7분)
python eval/run_scenario_answer_eval.py --sample 200   # 답변 계층 (ANTHROPIC_API_KEY)
```

## 실데이터 적재: 금융감독원 상품 공시 (합법 소스)

`ingest/`는 금융감독원 **금융상품통합비교공시 "금융상품한눈에" Open API**
(finlife.fss.or.kr — 공시 데이터 활용을 위해 공식 제공되는 무료 API)에서
전 은행의 실제 정기예금·적금·주택담보대출·전세자금대출·신용대출 상품을 받아
온톨로지 인스턴스로 적재합니다. 은행 사이트 크롤링은 약관 위반 소지가 있어
사용하지 않습니다.

```bash
export FSS_API_KEY=발급받은키          # finlife.fss.or.kr 에서 무료 발급
python ingest/fss_client.py            # 공시 데이터 다운로드 → data/fss/
python ingest/fss_to_ttl.py            # 온톨로지 인스턴스 변환 → data/market-instances.ttl
python eval/run_market_eval.py         # 실무형 벤치마크 (질문·정답 자동 생성)
```

API 접근이 불가한 환경에서는 `python ingest/fss_to_ttl.py --sample` 로 가상 은행
픽스처를 사용해 파이프라인을 검증할 수 있습니다. 실무형 벤치마크는 적재된 데이터에서
질문과 정답을 SPARQL로 자동 계산하므로("12개월 정기예금 최고 우대금리는?",
"고정금리 주담대만 골라줘" 등) 데이터가 갱신되면 벤치마크도 함께 갱신됩니다.
샘플 기준 결과: [docs/market-benchmark-report.md](docs/market-benchmark-report.md)
— 근거 재현율 벡터 59% vs 온톨로지 100%.

## 확장 로드맵

- [ ] SHACL 제약(shape) 추가 — 데이터 품질 검증 강화
- [ ] 신탁·퇴직연금(IRP)·방카슈랑스 모듈
- [ ] 금융결제원 표준 코드(은행코드 등) 어휘 통합
- [ ] FIBO 공식 IRI와의 `owl:equivalentClass` 정렬 확대
- [ ] 한국은행 경제통계·금융감독원 공시 데이터 연계 예시

## 라이선스

MIT License
