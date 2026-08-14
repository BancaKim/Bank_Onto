# 은행권 온톨로지 설계 문서

## 1. 설계 목표

- FIBO의 검증된 모델링 패턴을 한국 은행권 도메인에 적용
- 은행 실무 용어(수신·여신·요주의·근저당 등)를 정확한 한국어 레이블로 표준화
- 지식그래프, 규제보고 자동화, 상품 메타데이터 관리, LLM 기반 질의응답의 기반 스키마로 활용 가능하도록 설계

## 2. FIBO에서 차용한 핵심 패턴

### 2.1 모듈형 아키텍처

FIBO는 도메인(FND, BE, FBC, SEC, LOAN…) 아래 모듈을 두고 `owl:imports`로 결합합니다.
본 온톨로지도 동일하게 7개 모듈을 두고, 최상위 `bank-onto.ttl`이 전체를 import 합니다.

의존성 방향 (화살표 = imports):

```
bank-onto ──┬─> core                     (기반: 의존성 없음)
            ├─> parties      ──> core
            ├─> products     ──> core, parties
            ├─> accounts     ──> core, parties, products
            ├─> loans        ──> core, parties, products, accounts
            ├─> transactions ──> core, parties, accounts
            └─> risk         ──> core, parties, transactions
```

순환 의존이 없도록 계층화했습니다. 하위 모듈은 상위 모듈을 참조하지 않습니다.

### 2.2 당사자-역할(Party-Role) 패턴

FIBO FND의 `playsRole` 패턴을 그대로 채택했습니다.

```
자연인 "김민준" (parties:NaturalPerson)
  ├─ playsRole ─> 예금주 역할 (parties:AccountHolder)   ─ 계좌와 연결
  └─ playsRole ─> 차주 역할   (parties:Borrower)        ─ 대출계약과 연결
```

**이유**: 고객·차주·보증인은 사람의 본질적 속성이 아니라 계약 맥락에서의 역할입니다.
역할을 분리하면 한 당사자가 여러 은행의 고객이거나, 한 계약에서 차주이면서
다른 계약에서 보증인인 상황을 모순 없이 표현할 수 있습니다.

### 2.3 상품-계약-계좌 3층 구조

| 층 | 클래스 예 | 의미 |
|---|---|---|
| 상품 (Product) | `products:TimeDepositProduct` | 은행이 설계·판매하는 템플릿 |
| 계약 (Contract) | `loans:MortgageLoanContract` | 특정 당사자 간 법률관계 |
| 계좌 (Account) | `accounts:TimeDepositAccount` | 거래를 기록하는 운영 단위 |

계좌는 `accounts:isBasedOnProduct`로 상품에, 대출계약은 `loans:hasLoanAccount`로
계좌에 연결됩니다.

### 2.4 금액·이율의 구조화

금액을 리터럴이 아닌 `core:MonetaryAmount`(수치 + 통화) 개체로 모델링하여
다통화 환경(외화예금, 해외송금)을 지원합니다. 이율도 `core:InterestRate` 개체로 두고,
변동금리는 `core:isLinkedToReferenceRate`로 기준금리(COFIX 등)에 연결합니다.

## 3. 한국 은행권 특화 개념

FIBO에 없거나 다르게 모델링된 한국 특화 개념:

- **전세자금대출** (`products:JeonseLoanProduct`) — 한국 고유의 전세 제도 기반 대출
- **여신 규제비율** (`loans:LTV/DTI/DSR`) — 한국 가계부채 규제 체계
- **자산건전성 5단계 분류** (`loans:AssetQualityClassification`) — 은행업감독규정의 정상/요주의/고정/회수의문/추정손실
- **은행 유형** — 시중은행/지방은행/인터넷전문은행/특수은행 구분 (은행법·특별법 체계)
- **주민등록번호·사업자등록번호** — 실명확인 식별자
- **STR/CTR** — 특정금융정보법상 KoFIU 보고 의무
- **예금자보호** — 예금보험공사, 1인당 5천만원 한도
- **오픈뱅킹 채널** — 오픈뱅킹공동업무 기반 거래 채널

## 4. 명명 규칙

- **IRI**: UpperCamelCase (클래스), lowerCamelCase (속성)
- **네임스페이스**: `https://w3id.org/bank-onto/<module>/`
- **레이블**: 모든 클래스·속성에 `@ko`, `@en` 레이블 필수 (`scripts/validate.py`가 ko 레이블 누락을 검사)
- **정의**: 클래스에는 `skos:definition`(한국어) 권장
- **FIBO 정렬**: 대응 개념이 있으면 `rdfs:seeAlso`로 FIBO IRI 연결. 의미가 완전히 일치함이
  검증되면 `owl:equivalentClass`로 승격 (로드맵)

## 5. 열거형 모델링 방식

상태·방식 등 닫힌 목록(계좌상태, 상환방식, 거래채널, 건전성분류)은
**클래스 + 명명된 개체(named individual)** 방식을 사용했습니다.

```turtle
:RepaymentMethod a owl:Class .
:EqualPrincipalAndInterest a :RepaymentMethod ;  # 원리금균등
    rdfs:label "원리금균등분할상환"@ko .
```

SKOS ConceptScheme으로의 전환은 코드체계(은행코드, 통화코드) 통합 시 검토합니다.

## 6. 검증 체계

`scripts/validate.py`가 수행하는 검사:

1. **구문 검증** — 모든 .ttl 파일의 Turtle 파싱
2. **참조 무결성** — `subClassOf`/`domain`/`range`가 가리키는 미정의 클래스 탐지
3. **레이블 정책** — 한국어 레이블 누락 클래스 탐지

향후 SHACL shape을 추가하여 인스턴스 수준 제약(예: 대출계약은 차주 1인 이상,
금액은 통화 필수)을 기계 검증할 계획입니다. 현재는 OWL 제약
(`owl:minCardinality`)으로 명세만 되어 있습니다.
