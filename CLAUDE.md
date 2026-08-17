# CLAUDE.md

FIBO 스타일 한국 은행권 온톨로지 + 에이전트 knowledge layer + RAG 비교 벤치마크 프로젝트.

## 프로젝트 목적

1. FIBO 설계 원칙(모듈형, 당사자-역할 패턴, 상품-계약-계좌 분리)을 따른 은행 도메인 OWL 온톨로지 구축
2. 이를 LLM 은행 에이전트의 knowledge layer로 사용
3. **온톨로지 RAG가 벡터 RAG·Graph RAG(LPG)보다 우월함을 정량 입증** (핵심 목표)

## 저장소 구조

```
ontology/          OWL 온톨로지 모듈 (Turtle). bank-onto.ttl이 전체 import 진입점
  bank-core.ttl      기반: 계약·금액·통화·금리·식별자 (FIBO FND 대응)
  parties.ttl        은행·고객·당사자-역할 패턴 (FIBO BE 대응)
  products.ttl       수신·여신·카드·외환 상품 (FIBO FBC 대응)
  accounts.ttl       계좌·계좌상태
  loans.ttl          대출계약·담보·상환방식·LTV/DTI/DSR·자산건전성 (FIBO LOAN 대응)
  transactions.ttl   거래·채널
  risk-compliance.ttl 바젤·AML/KYC·예금자보호
  market-data.ttl    금감원 공시 데이터용 확장 (금리옵션 등)
  regulations.ttl    법령·조문 스키마 (규정형 벤치마크 근거 코퍼스용)
knowledge/         에이전트 knowledge layer
  kb.py              BankKnowledgeBase: 검색·개념상세·계층·인스턴스·SPARQL 조회 API
  tools.py           Claude 에이전트 도구 6종 (@beta_tool, BANK_KB_TOOLS)
agent/bank_agent.py  claude-opus-5 + tool runner 은행 상담 에이전트 (단일질문/대화형)
ingest/            금감원 "금융상품한눈에" Open API 적재 파이프라인
  fss_client.py      다운로드 (은행권 020000 고정, FSS_API_KEY 환경변수 필요)
  fss_to_ttl.py      JSON → data/market-instances.ttl 변환 (--sample: 픽스처 검증)
  import_krfinreg.py 석사논문 벤치마크(KR-FinReg-QA, ~/research_paper)의 은행 문항을
                     202608 공시로 근거 재검증 후 이식 → data/krfinreg-bank-questions.jsonl
eval/              3-way RAG 벤치마크 (벡터 vs LPG vs 온톨로지)
  corpus.py          온톨로지 → 텍스트 직렬화 + 400자 청킹 (벡터 베이스라인용)
  vector_rag.py      TF-IDF 문자 n-gram top-5 리트리버 (오프라인 어휘 벡터)
  lpg_rag.py         LPG(속성 그래프) k-hop 이웃 탐색 리트리버 (Neo4j식 KG-RAG)
  graph_rag.py       온톨로지 리트리버 (개념매칭→계층·속성·BFS, LLM 없이 결정적)
  benchmark_questions.py  큐레이션 18문항 + 환각유도 2문항 (gold evidence 방식)
  mcq_questions.py   객관식 20문항 (결정적 채점용)
  run_krfinreg_eval.py    KR-FinReg-QA 은행 이식 76문항 3-way → docs/krfinreg-benchmark-report.md
  run_bench_v2_eval.py    Bench v2 1,000문항 3-way → docs/bench-v2-report.md
  run_retrieval_eval.py   검색 계층 3-way → docs/benchmark-report.md
  run_market_eval.py      시장 데이터 실무 벤치마크 (질문·정답 SPARQL 자동생성)
  run_answer_eval.py      답변 계층 3-way: MCQ + LLM심판 + 유사도 (API 키 필요)
bench/             HF 공개용 Bank-Onto-Bench v2 (1,000문항, 규정 300:공시 700)
  fetch_laws.py      법령정보센터 DRF API로 현행 법령 7종 수집 → data/laws/*.json
  generate.py        공시·법령 원문에서 기계 생성 (결정적, LLM 불개입, 가상개체 없음)
  laws_to_ttl.py     법령 JSON → data/law-instances.ttl (KB 자동 로드 — 규정형 근거)
  export_xlsx.py     → docs/bank-onto-bench-v2.xlsx
data/bank-onto-bench-v2.jsonl       벤치마크 본체 (+ 같은 이름 -README.md = HF 카드)
data/laws/         법령 원문 스냅샷 (조문 구조화 JSON)
data/fss/sample/   가상 은행 픽스처 (FSS API 스키마 동일, 파이프라인 검증용)
data/market-instances.ttl  변환된 시장 데이터 (현재 샘플 기준; KB가 자동 로드)
scripts/           validate.py (구문·참조·ko레이블 검증), query.py (예시 SPARQL),
                   export_benchmark_xlsx.py (벤치마크 4종 → docs/bank-onto-benchmark-v1.xlsx)
tests/             test_knowledge_layer.py (KB 단위 10건) +
                   test_retrievers.py (결정성·다중홉·픽스처 격리 3건) +
                   test_krfinreg.py (이식 필드·데이터셋 무결성 3건) +
                   test_bench_v2.py (v2 규모·비율·균형·커버리지 5건) — 모두 API 키 불필요
docs/              architecture.md, benchmark-report.md, market-benchmark-report.md
```

## 자주 쓰는 명령

```bash
pip install -r requirements.txt        # rdflib, anthropic

python scripts/validate.py             # 온톨로지 검증 (커밋 전 필수)
python tests/test_knowledge_layer.py   # KB 회귀 테스트 (커밋 전 필수)

python eval/run_retrieval_eval.py      # 검색 3-way 벤치마크 (결정적, 키 불필요)
python eval/run_market_eval.py         # 시장 데이터 벤치마크 (결정적, 키 불필요)
python eval/run_answer_eval.py         # 답변 3-way (ANTHROPIC_API_KEY 필요)

python agent/bank_agent.py "질문"      # 에이전트 실행 (ANTHROPIC_API_KEY 필요)

# 실데이터 적재 (금감원 API 키 필요 — finlife.fss.or.kr 무료 발급)
export FSS_API_KEY=...
python ingest/fss_client.py && python ingest/fss_to_ttl.py
python ingest/fss_to_ttl.py --sample   # 키 없이 픽스처로 검증
```

## 핵심 설계 결정

- **네임스페이스**: `https://w3id.org/bank-onto/<module>/`. 프리픽스는 `knowledge/kb.py`의
  `PREFIXES`에 등록 (SPARQL에서 PREFIX 선언 없이 사용 가능). 새 모듈 추가 시 여기도 갱신.
- **레이블 정책**: 모든 클래스·속성에 `@ko`+`@en` rdfs:label 필수, 클래스에 한국어
  skos:definition 권장. `scripts/validate.py`가 ko 레이블 누락을 검사.
- **FIBO 정렬**: 대응 개념은 `rdfs:seeAlso`로 FIBO IRI 연결 (equivalentClass 승격은 로드맵).
- **열거형**: 상태·방식 등 닫힌 목록은 클래스 + named individual 방식
  (예: `loans:EqualPrincipalAndInterest a loans:RepaymentMethod`).
- **KB 로드 순서**: ontology/*.ttl + examples/*.ttl + data/*.ttl 전부 하나의 그래프로.
- **추론기 없음**: rdflib는 OWL 추론을 하지 않음. 클래스 계층은 KB 코드에서 직접 순회
  (`rdfs:subClassOf*`). inverseOf·cardinality는 명세만 존재. 추론 필요 시 owlready2 검토.
- **에이전트**: Anthropic SDK tool runner(`client.beta.messages.tool_runner`) 사용,
  모델 `claude-opus-5`. 도구 추가 시 `knowledge/tools.py`의 `BANK_KB_TOOLS`에 등록.
- **FSS 적재는 은행권(topFinGrpNo=020000) 고정** — 저축은행 등 다른 권역 제외 (사용자 요구).
- **API 키는 절대 커밋 금지** — FSS_API_KEY·ANTHROPIC_API_KEY 모두 환경변수로만.
  `data/fss/*.json`(실데이터 다운로드)은 .gitignore 처리됨, sample/은 커밋 대상.

## 벤치마크 방법론 (수치 인용 시 주의)

- **2계층 평가**: 검색 계층(근거 재현율 = 정답에 필요한 근거가 컨텍스트에 포함된 비율,
  LLM 없이 결정적) + 답변 계층(MCQ 정확도 / LLM-as-judge / TF-IDF 유사도).
  검색 계층은 파이프라인 품질의 **상한**을 측정한다는 프레이밍 유지.
- **공정성 원칙**: 세 시스템이 동일 지식에서 출발. LPG는 분류 체계를 노드로 포함한
  관대한 변환 + 온톨로지와 동일한 시드 매칭(LCS) 사용 — 남는 격차가 스키마 의미론의
  순수 기여분이 되도록. 벡터 베이스라인은 재현성 위해 어휘적 TF-IDF (의미 임베딩으로
  교체 가능하나 다중홉·열거·집계 실패는 청킹+유사도 패러다임 자체의 한계임을 리포트에 명시).
- **현재 수치** (금감원 실데이터 202608 + 법령 7종 1,025조문 적재 기준): 검색
  재현율 — 큐레이션 18문항 벡터 50% / LPG 86% / 온톨로지 100%; 시장 8문항
  12% / 78% / 100%; KR-FinReg 이식 71문항 78% / 100% / 100%; **Bench v2
  880문항 83% / 98% / 99%**. 환각유도 컨텍스트: 벡터 2,020자 vs 그래프 0자.
  벡터 수치는 코퍼스가 커질 때마다(법령 적재 등) 하락함 — top-k 희석은 벡터
  패러다임의 구조적 한계로 리포트에 명시.
- **리트리버 시드 매칭**: LCS 동점 시 매칭 절대 길이(특이도) 우선, 4-gram
  사전필터는 LCS 임계와 정확 동치 (양쪽 그래프 리트리버 동일 적용). 벡터는
  역색인 최적화 (점수 불변). Bench v2에서 LPG-온톨로지 격차가 작은 이유(단일
  문서 조회형 위주)와 컨텍스트 크기 격차는 docs/bench-v2-report.md 해석 참조.
- **KR-FinReg 이식 세트는 단일 상품 조회형**이라 검색 계층 변별력이 작다(LPG=온톨로지
  100% 동률). 이 세트의 목적은 답변 계층: YES/NO 판정 + ABSTAIN 5문항 보류 정확도.
  원본(202607)과 공시가 달라진 문항은 이식에서 자동 탈락시킴(정답 부패 방지).
- 시장 벤치마크는 질문·정답을 적재된 데이터에서 SPARQL로 자동 계산 — 데이터를
  갈아끼우면 벤치마크도 자동 갱신됨. '공시된 상품' 집계는 `market:disclosureMonth`
  조건으로 examples/ 가상 픽스처를 제외함.
- **리트리버 결정성**: 그래프·LPG 리트리버는 이름 색인·시드 순위·이웃 순회를 모두
  정렬해 PYTHONHASHSEED와 무관하게 동일 결과 보장 (tests/test_retrievers.py가 검증).
  BFS 예산은 시드별 독립 할당 — 허브 노드(은행 등)에 연결된 시드가 다른 시드의
  탐사 예산을 잠식하지 않게 함 (두 그래프 시스템에 동일 적용, 공정성 유지).

## 미완료 작업 (로컬에서 이어서)

1. ~~실데이터 적재~~ **완료** (2026-08-17): 금감원 실데이터 적재됨 (은행 19개,
   상품 215개, 금리옵션 660개). 월별 공시 갱신 시 `FSS_API_KEY=...
   python ingest/fss_client.py && python ingest/fss_to_ttl.py` 재실행.
2. **답변 계층 실행**: `python eval/run_answer_eval.py` (ANTHROPIC_API_KEY 필요)
   → docs/answer-eval-report.md 생성. 아직 한 번도 실행되지 않음.
   KR-FinReg 이식 문항(YES/NO/ABSTAIN 판정형)도 답변 계층에 통합할 것 —
   data/krfinreg-bank-questions.jsonl의 verdict로 결정적 채점 가능.
3. **KR-FinReg 2단계 (법령 60문항)**: ~/research_paper의 Q2_시간 문항(신구조문
   유효기간 판정)은 버전드 규칙 데이터(kb_candidates_amend.jsonl, 규칙 191개,
   valid_from/valid_to)를 TTL로 변환하는 시간 축 모듈이 선행되어야 함. 미착수.
4. **로드맵**: SHACL 제약, FIBO equivalentClass 정렬, 신탁·퇴직연금 모듈,
   LangGraph 포팅(발표용 프레이밍 필요 시), 의미 임베딩 벡터 베이스라인 추가.

## Git

- 브랜치: `claude/banking-ontology-build-5zwe0q` (현재 유일한 브랜치이자 기본 브랜치)
- 커밋 전: `python scripts/validate.py && python tests/test_knowledge_layer.py
  && python tests/test_retrievers.py && python tests/test_krfinreg.py
  && python tests/test_bench_v2.py`
- 벤치마크 코드를 바꿨으면 리포트 재생성 후 함께 커밋
  (`run_retrieval_eval.py`, `run_market_eval.py`)
