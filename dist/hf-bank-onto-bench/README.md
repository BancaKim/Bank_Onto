---
language:
- ko
license: other
license_name: kogl-type-1
license_link: https://www.kogl.or.kr/info/license.do
task_categories:
- question-answering
- text-classification
tags:
- finance
- banking
- korean
- regulation
- RAG
size_categories:
- 1K<n<10K
configs:
- config_name: default
  data_files:
  - split: test
    path: data/test.jsonl
---

# Bank-Onto-Bench v2

한국 **은행 도메인** 질의응답 벤치마크 1,000문항. 상품 공시형 700 + 규정형 300 (7:3).

모든 정답은 공개 원문(금융감독원 공시 필드, 국가법령정보센터 조문, 법령 시행일
메타데이터)에서 **기계적으로 산출**되었으며 LLM은 정답 생성에 관여하지 않았다.
가상 인물·가상 은행 시나리오는 포함하지 않는다.

## 구성

| qtype | 문항 | 출처 |
|---|---|---|
| 공시형 | 700 | 금융감독원 금융상품통합비교공시 Open API (finlife.fss.or.kr), 은행권(topFinGrpNo=020000), 2026-08 공시, 은행 19개·상품 215개 |
| 규정형 | 300 | 국가법령정보센터 Open API (law.go.kr) 현행 법령 7종 조문 + 법령 개정 시행일 메타데이터 |

**카테고리**: 예금 405 · 대출 321 · 공통(은행법·금소법) 82 · 퇴직연금 68 ·
펀드 45 · 카드 40 · 외환 39

**정답 유형**: boolean(YES/NO) 392 — YES 206/NO 186 균형 · span 323 ·
numeric 225 · **abstain 60** (공시에 없는 정보 — 보류가 정답인 환각 측정 축)

**검수 이력 (v2.0)**: 정답 문자열이 질문 문면에 노출되는 문항 0건(정의 자기참조
10건·법종 문항 7건 제거), 상품명 개행·중복 병기 정규화, 질문 텍스트 중복 0건,
`datasets.load_dataset` 스키마 안정성 확인(전 필드 string, unit 항상 존재).

**템플릿 16종**: 금리 조회·임계 판정, 가입경로·연령 요건 판정, 최고한도,
이자계산방식, 담보유형별 대출금리, 조문 위치, 법률 용어 정의 역조회, 벌칙 상한,
법령 메타, 신구조문 유효기간 판정(시간 추론), 공시 부재(보류) 등.

## 필드

```json
{
  "id": "PRD-0001",
  "qtype": "공시형 | 규정형",
  "category": "예금 | 대출 | 카드 | 외환 | 퇴직연금 | 펀드 | 공통",
  "subcategory": "정기예금 | 적금 | 주택담보대출 | … | 법령명",
  "template": "rate_threshold | article_locate | …",
  "question": "…",
  "answer_type": "boolean | numeric | span | abstain",
  "answer": "YES | 3.85 | 제34조 | 공시에 해당 정보 없음",
  "unit": "% (numeric일 때)",
  "evidence": {"source": "…", "locator": "은행:상품코드:필드 | 제N조", "text": "원문 발췌"}
}
```

## 채점

- boolean/abstain: 정답 문자열 일치 (결정적)
- numeric: 수치 동등 비교 (단위는 `unit` 필드)
- span: 정규화 후 완전 일치 또는 포함 일치 권장

## 주의사항

- 공시형 정답은 **2026-08 공시 시점** 기준이다. 금리·한도는 매월 변동될 수
  있으므로 시점을 명시해 인용할 것. 재생성 파이프라인은 공시월을 갈아끼우면
  정답을 자동 재산출한다.
- 시간형(temporal_validity) 60문항은 KR-FinReg-QA v1에서 이식했으며 정답은
  법령 개정 시행일 구간에서 기계 산출되었다.
- 규정형의 법령 원문은 공공데이터(국가법령정보센터), 공시형 원천은
  금융감독원 공공데이터이다 (공공누리 제1유형 — 출처 표시).

## 재생성

```bash
FSS_API_KEY=... python ingest/fss_client.py     # 공시 데이터 다운로드
python bench/fetch_laws.py                       # 법령 원문 수집
python bench/generate.py                         # 1,000문항 생성 (결정적)
python tests/test_bench_v2.py                    # 무결성 검증
```
