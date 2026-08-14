"""벤치마크 질문 세트.

각 질문은 정답에 반드시 필요한 근거(gold evidence) 문자열 목록을 갖는다.
리트리버가 제공한 컨텍스트에 근거가 포함되면 답변 가능으로 간주한다
(근거 재현율, evidence recall).

범주:
- DEF     단순 정의 조회 — 벡터 RAG도 잘하는 영역 (통제군)
- HIER    분류 체계 완전 열거 — 전체 하위 유형을 빠짐없이 요구
- MULTIHOP 다중 홉 관계 추적 — 여러 개체를 건너야 답이 나옴
- AGG     집계/필터 — 조건에 맞는 개체 식별
- SCHEMA  스키마 질의 — 클래스 관계, 필요 속성
- NEG     존재하지 않는 개념 — 환각 유도 (컨텍스트가 없어야 정직한 것)
"""

QUESTIONS = [
    # --- DEF: 단순 정의 (통제군) ---
    {"id": "DEF-1", "category": "DEF",
     "question": "DSR이 뭐야?",
     "gold": ["총부채원리금상환비율", "연소득"],
     "answer": "DSR(총부채원리금상환비율)은 연소득 대비 전체 대출의 원리금 상환액 비율이다."},
    {"id": "DEF-2", "category": "DEF",
     "question": "휴면 상태의 계좌란 어떤 거야?",
     "gold": ["장기간 거래가 없어"],
     "answer": "장기간 거래가 없어 휴면 처리된 상태의 계좌."},
    {"id": "DEF-3", "category": "DEF",
     "question": "의심거래보고는 어디에 하는 거야?",
     "gold": ["금융정보분석원"],
     "answer": "자금세탁이 의심되는 거래를 금융정보분석원(KoFIU)에 보고한다."},

    # --- HIER: 분류 체계 완전 열거 ---
    {"id": "HIER-1", "category": "HIER",
     "question": "우리나라 은행의 종류를 모두 알려줘",
     "gold": ["시중은행", "지방은행", "인터넷전문은행", "특수은행"],
     "answer": "시중은행, 지방은행, 인터넷전문은행, 특수은행."},
    {"id": "HIER-2", "category": "HIER",
     "question": "수신상품에는 어떤 종류가 있어?",
     "gold": ["요구불예금", "정기예금", "정기적금", "MMDA", "외화예금"],
     "answer": "요구불예금(보통예금·당좌예금·MMDA), 정기예금, 정기적금, 외화예금."},
    {"id": "HIER-3", "category": "HIER",
     "question": "대출 상환방식에는 어떤 것들이 있어?",
     "gold": ["원리금균등", "원금균등", "만기일시"],
     "answer": "원리금균등분할상환, 원금균등분할상환, 만기일시상환."},
    {"id": "HIER-4", "category": "HIER",
     "question": "여신상품 종류를 전부 나열해줘",
     "gold": ["신용대출", "담보대출", "주택담보대출", "전세자금대출", "기업대출", "마이너스통장"],
     "answer": "신용대출, 담보대출(주택담보대출 포함), 전세자금대출, 기업대출, 마이너스통장(한도대출)."},

    # --- MULTIHOP: 다중 홉 관계 추적 ---
    {"id": "HOP-1", "category": "MULTIHOP",
     "question": "김민준이 받은 대출의 담보 가치는 얼마야?",
     "gold": ["500000000"],
     "answer": "담보(서울시 소재 아파트)의 감정가는 5억 원(500,000,000)이다."},
    {"id": "HOP-2", "category": "MULTIHOP",
     "question": "김민준 대출 금리는 어떤 기준금리에 연동돼?",
     "gold": ["COFIX"],
     "answer": "COFIX(신규취급액 기준)에 연동된 변동금리다."},
    {"id": "HOP-3", "category": "MULTIHOP",
     "question": "김민준이 가입한 정기예금 상품의 금리는 몇 %야?",
     "gold": ["3.50"],
     "answer": "한빛 정기예금, 연 3.50% 고정금리."},
    {"id": "HOP-4", "category": "MULTIHOP",
     "question": "김민준의 이체 거래는 어떤 채널에서 실행됐어?",
     "gold": ["모바일뱅킹"],
     "answer": "모바일뱅킹 채널에서 실행되었다."},
    {"id": "HOP-5", "category": "MULTIHOP",
     "question": "김민준 주택담보대출의 상환방식과 만기일은?",
     "gold": ["원리금균등", "2055-03-01"],
     "answer": "원리금균등분할상환, 만기일 2055-03-01."},

    # --- AGG: 집계/필터 ---
    {"id": "AGG-1", "category": "AGG",
     "question": "예금자보호가 적용되는 상품은 어떤 거야?",
     "gold": ["한빛 정기예금"],
     "answer": "한빛 정기예금(예금자보호 여부 true)."},
    {"id": "AGG-2", "category": "AGG",
     "question": "LTV가 적용된 대출 계약의 LTV 값은?",
     "gold": ["60.0"],
     "answer": "김민준의 주택담보대출계약, LTV 60.0%."},
    {"id": "AGG-3", "category": "AGG",
     "question": "김민준이 보유한 계좌를 모두 알려줘",
     "gold": ["Account_KimMinjun_TD", "Account_KimMinjun_DD"],
     "answer": "정기예금계좌(ex:Account_KimMinjun_TD)와 요구불예금계좌(ex:Account_KimMinjun_DD), 총 2개."},

    # --- SCHEMA: 스키마 질의 ---
    {"id": "SCH-1", "category": "SCHEMA",
     "question": "대출계약을 등록하려면 어떤 당사자 정보가 필요해?",
     "gold": ["차주", "대주"],
     "answer": "차주(hasBorrower, 1인 이상 필수)와 대주(hasLender, 필수), 선택적으로 보증인."},
    {"id": "SCH-2", "category": "SCHEMA",
     "question": "주택담보대출계약은 어떤 계약의 하위 개념이야?",
     "gold": ["담보대출계약"],
     "answer": "담보대출계약(SecuredLoanContract)의 하위이며, 그 위로 대출계약 → 금융계약 → 계약으로 이어진다."},
    {"id": "SCH-3", "category": "SCHEMA",
     "question": "정기적금계좌의 월 납입액은 어떤 속성으로 기록해?",
     "gold": ["hasMonthlyInstallmentAmount"],
     "answer": "accounts:hasMonthlyInstallmentAmount 속성."},
]

# 존재하지 않는 개념 — 컨텍스트를 제공하지 않는 것이 정답
NEGATIVE_QUESTIONS = [
    {"id": "NEG-1", "category": "NEG",
     "question": "리볼빙 결제 수수료율이 몇 %야?",
     "answer": "온톨로지에 리볼빙 관련 개념이 없다 — 모른다고 답해야 함."},
    {"id": "NEG-2", "category": "NEG",
     "question": "펀드 판매보수는 얼마야?",
     "answer": "온톨로지에 펀드 관련 개념이 없다 — 모른다고 답해야 함."},
]
