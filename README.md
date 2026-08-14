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

## 확장 로드맵

- [ ] SHACL 제약(shape) 추가 — 데이터 품질 검증 강화
- [ ] 신탁·퇴직연금(IRP)·방카슈랑스 모듈
- [ ] 금융결제원 표준 코드(은행코드 등) 어휘 통합
- [ ] FIBO 공식 IRI와의 `owl:equivalentClass` 정렬 확대
- [ ] 한국은행 경제통계·금융감독원 공시 데이터 연계 예시

## 라이선스

MIT License
