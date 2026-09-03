# 온톨로지 스키마 다이어그램

전체 스키마(클래스 138개, 객체속성 52개, 데이터속성 62개, 모듈 9개)의 시각화.
계층 다이어그램의 화살표는 **상위 분류 → 하위 분류**(`rdfs:subClassOf`의 역방향),
관계 다이어그램의 화살표는 객체속성이다. `《개체》`는 열거형 named individual.

## 1. 모듈 구조 (owl:imports)

```mermaid
graph BT
  CORE["core<br/>기반: 계약·금액·금리·식별자"]
  PARTIES["parties<br/>은행·고객·역할"] --> CORE
  PRODUCTS["products<br/>수신·여신·카드·외환 상품"] --> PARTIES
  ACCOUNTS["accounts<br/>계좌"] --> PRODUCTS
  LOANS["loans<br/>대출계약·담보·규제비율"] --> ACCOUNTS
  TX["transactions<br/>거래·채널"] --> ACCOUNTS
  RISK["risk<br/>바젤·AML/KYC·예금자보호"] --> TX
  REGS["regs<br/>법령·조문 (규제 원문)"]
  MARKET["market<br/>금감원 공시 데이터 확장"] --> PRODUCTS
  TOP["bank-onto (진입점)"] --> LOANS
  TOP --> RISK
  TOP --> REGS
```

`market`은 `products`를 확장하는 데이터 모듈로, `bank-onto`의 직접 import 대상은 아니고
KB가 디렉터리 로드로 함께 적재한다. `regs`는 다른 모듈에 의존하지 않는 독립 모듈이다.

## 2. 핵심 개념 관계도 (모듈 횡단)

FIBO의 세 가지 축 — 당사자-역할 분리, 상품(템플릿)-계약(법률관계)-계좌(운영단위) 분리 —
가 어떻게 연결되는지 보여준다.

```mermaid
graph LR
  PARTY["당사자<br/>자연인·법인"] -- playsRole --> ROLE["당사자 역할<br/>예금주·차주·보증인 ..."]
  BANK["은행"] -- isRegulatedBy --> REG["감독기관"]
  PROD["금융상품"] -- isOfferedBy --> BANK
  PROD -- hasBaseRate --> RATE["이자율"]
  RATE -- isLinkedToReferenceRate --> REF["기준금리 (COFIX 등)"]
  PROD -- hasRateOption --> OPT["금리 옵션<br/>(공시 데이터)"]
  ACC["계좌"] -- hasAccountHolder --> ROLE
  ACC -- isBasedOnProduct --> PROD
  ACC -- isMaintainedBy --> BANK
  LOAN["대출계약"] -- "hasBorrower / hasLender" --> ROLE
  LOAN -- isSecuredBy --> COL["담보"]
  LOAN -- isGuaranteedBy --> GUA["보증"]
  LOAN -- isBasedOnLoanProduct --> PROD
  LOAN -- hasLoanAccount --> ACC
  LOAN -- hasRepaymentMethod --> RM["《상환방식》"]
  TXN["거래"] -- "hasSourceAccount /<br/>hasDestinationAccount" --> ACC
  TXN -- occursViaChannel --> CH["《거래 채널》"]
  TXN -- isInitiatedBy --> PARTY
  KYC["KYC 고객확인"] -- isPerformedOnCustomer --> ROLE
  STR["의심거래보고(STR)"] -- reportsOnTransaction --> TXN
```

## 3. core — 기반 개념

```mermaid
graph TD
  subgraph C1["계약"]
    AGR["합의 Agreement"] --> CONTRACT["계약 Contract"]
    CONTRACT --> FC["금융계약 FinancialContract"]
  end
  subgraph C2["금리"]
    IR["이자율 InterestRate"] --> FIR["고정금리"]
    IR --> VIR["변동금리"]
    IR --> RR["기준금리"]
  end
  subgraph C3["식별자"]
    ID["식별자 Identifier"] --> AN["계좌번호"]
    ID --> RRN["주민등록번호"]
    ID --> BRN["사업자등록번호"]
    ID --> SW["SWIFT 코드"]
  end
  subgraph C4["기타"]
    AA["자율 행위자"]
    MA["금액 MonetaryAmount"] -- hasCurrency --> CUR["통화 Currency"]
    DP["기간 DatePeriod"]
    CP["계약당사자"]
  end
```

## 4. parties — 당사자와 역할

```mermaid
graph TD
  subgraph P1["당사자 (실체)"]
    AA["자율 행위자 (core)"] --> PARTY["당사자 Party"]
    PARTY --> NP["자연인"]
    PARTY --> ORG["조직 Organization"]
    PARTY --> SP["개인사업자"]
    ORG --> LE["법인 LegalEntity"]
    ORG --> BB["은행 지점"]
    ORG --> RA["감독기관"]
    LE --> FI["금융기관"]
    FI --> BANK["은행 Bank"]
    FI --> CB["중앙은행"]
    BANK --> COM["시중은행"]
    BANK --> REG["지방은행"]
    BANK --> NET["인터넷전문은행"]
    BANK --> SPE["특수은행"]
  end
  subgraph P2["역할 (Party-Role 패턴)"]
    ROLE["당사자 역할 PartyRole"] --> CUST["고객 Customer"]
    ROLE --> LENDER["대주(대출기관)"]
    ROLE --> GUAR["보증인"]
    ROLE --> BO["실제소유자"]
    CUST --> RC["개인고객"]
    CUST --> CC["기업고객"]
    CUST --> AH["예금주"]
    CUST --> DEP["예금자"]
    CUST --> BOR["차주(대출자)"]
    CUST --> CM["카드회원"]
  end
  NP -. playsRole .-> ROLE
```

## 5. products — 금융상품

```mermaid
graph TD
  FP["금융상품 FinancialProduct"] --> DPRO["수신상품"]
  FP --> LPRO["여신상품"]
  FP --> CPRO["카드상품"]
  FS["금융서비스 FinancialService"] --> FX["외환서비스"]
  FS --> RS["송금서비스"]
  FX --> CE["환전서비스"]
  DPRO --> DD["요구불예금"]
  DPRO --> TD["정기예금"]
  DPRO --> IS["정기적금"]
  DPRO --> FCD["외화예금"]
  DD --> OD["보통예금"]
  DD --> CHK["당좌예금"]
  DD --> MMDA["MMDA"]
  LPRO --> CL["신용대출"]
  LPRO --> SL["담보대출"]
  LPRO --> JL["전세자금대출"]
  LPRO --> COL2["기업대출"]
  LPRO --> OVD["마이너스통장(한도대출)"]
  SL --> ML["주택담보대출"]
  CPRO --> CCP["신용카드"]
  CPRO --> DCP["체크카드"]
```

## 6. accounts — 계좌

```mermaid
graph TD
  ACC["계좌 Account"] --> DA["예금계좌"]
  ACC --> LA["대출계좌"]
  ACC --> VA["가상계좌"]
  DA --> DDA["요구불예금계좌"]
  DA --> TDA["정기예금계좌"]
  DA --> ISA["정기적금계좌"]
  DA --> FCA["외화예금계좌"]
  ST["계좌 상태 AccountStatus"] --- STI["《정상》《휴면》《지급정지》《해지》"]
  ACC -- hasAccountStatus --> ST
  VA -- isLinkedToAccount --> DA
```

## 7. loans — 여신

```mermaid
graph TD
  subgraph L1["대출계약"]
    FC["금융계약 (core)"] --> LC["대출계약 LoanContract"]
    LC --> CLC["신용대출계약"]
    LC --> SLC["담보대출계약"]
    LC --> GLC["보증부대출계약"]
    SLC --> MLC["주택담보대출계약"]
  end
  subgraph L2["담보·보증"]
    COL["담보 Collateral"] --> REC["부동산담보"]
    COL --> DEC["예금담보"]
    COL --> SEC["유가증권담보"]
    GUA["보증 Guarantee"] --> GL["보증서"]
  end
  subgraph L3["상환"]
    RM["상환방식"] --- RMI["《원리금균등》《원금균등》《만기일시》"]
    RSCH["상환 스케줄"] -- hasInstallment --> RI["상환 회차"]
  end
  subgraph L4["규제·심사"]
    RLR["여신 규제비율"] --> LTV["LTV 담보인정비율"]
    RLR --> DTI["DTI 총부채상환비율"]
    RLR --> DSR["DSR 총부채원리금상환비율"]
    CR["신용등급"]
    CS["신용점수"]
    APP["대출신청"] -- appliesFor --> LP2["여신상품 (products)"]
    APR["대출승인"]
  end
  subgraph L5["부실"]
    DL["연체"]
    NPL["부실채권 NPL"]
    AQC["자산건전성 분류"] --- AQI["《정상》《요주의》《고정》<br/>《회수의문》《추정손실》"]
  end
  LC -- isSecuredBy --> COL
  LC -- isGuaranteedBy --> GUA
  LC -- hasRepaymentSchedule --> RSCH
  LC -- hasAssetQualityClassification --> AQC
```

## 8. transactions — 거래

```mermaid
graph TD
  TXN["거래 Transaction"] --> DEP["입금거래"]
  TXN --> WIT["출금거래"]
  TXN --> TRF["이체거래"]
  TXN --> CARD["카드결제거래"]
  TXN --> FXT["외환거래"]
  TXN --> INT["이자지급"]
  TRF --> AUTO["자동이체"]
  FXT --> REM["해외송금"]
  AUTO -- executesStandingOrder --> SO["자동이체 약정"]
  CH["거래 채널"] --- CHI["《영업점》《ATM》《인터넷뱅킹》<br/>《모바일뱅킹》《텔레뱅킹》《오픈뱅킹》"]
  STT["거래 상태"] --- STI["《처리중》《완료》《실패》《취소》"]
  TXN -- occursViaChannel --> CH
  TXN -- hasTransactionStatus --> STT
```

## 9. risk — 리스크·규제준수

```mermaid
graph TD
  subgraph R1["리스크"]
    RISK["리스크 Risk"] --> CRR["신용리스크"]
    RISK --> MR["시장리스크"]
    RISK --> OR["운영리스크"]
    RISK --> LR["유동성리스크"]
    MR --> IRR["금리리스크"]
    MR --> FXR["환리스크"]
  end
  subgraph R2["바젤 자본규제"]
    CAP["자본규제"] --> BIS["BIS 자기자본비율"]
    CAP --> CET["CET1 보통주자본비율"]
    CAP --> LCR["LCR 유동성커버리지"]
    CAP --> NSFR["NSFR 순안정자금조달"]
    RWA["위험가중자산"]
  end
  subgraph R3["AML / KYC"]
    CP["규제준수 절차"] --> KYC["KYC 고객확인"]
    CP --> AML["AML 모니터링"]
    CP --> SS["제재대상 필터링"]
    KYC --> EDD["EDD 강화된 고객확인"]
    STR["의심거래보고 STR"]
    CTR["고액현금거래보고 CTR"]
  end
  subgraph R4["보호 제도"]
    DI["예금자보호"]
    FCP["금융소비자보호"]
  end
```

## 10. regs — 법령·조문 (규제 원문)

`data/law-instances.ttl`에 은행 관련 법령·조문 코퍼스가 이 스키마의 인스턴스로 적재된다.

```mermaid
graph LR
  ST["법령 Statute<br/>lawType 법령종류, ministry 소관부처,<br/>effectiveDate 시행일자"] -- hasArticle --> LA["조문 LegalArticle<br/>articleLabel 조문번호,<br/>articleTitle 제목, articleText 본문"]
  LA -- belongsToStatute --> ST
```

## 11. market — 공시 데이터 확장

```mermaid
graph LR
  PROD["금융상품 (products)"] -- hasRateOption --> RO["수신 금리 옵션<br/>termMonths, baseRateValue,<br/>maxPreferentialRateValue, 이자계산방식"]
  PROD -- hasRateOption --> LRO["여신 금리 옵션<br/>금리유형(고정/변동), 상환유형,<br/>담보유형, lendRateMin/Max/Avg"]
  PROD -- isOfferedBy --> BANK["은행 (parties)<br/>finCompanyNo"]
  PROD --- PP["우대조건, 가입방법, 가입대상,<br/>최고한도, 공시월, 출처"]
```

---

*이 다이어그램은 수동으로 관리된다. 스키마 변경 시 `scripts/validate.py` 통과 후
이 문서도 함께 갱신할 것. 전체 클래스·속성 목록은 KB의 `search_concepts` /
`get_hierarchy`로 조회 가능.*
