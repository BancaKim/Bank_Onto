"""은행 에이전트용 Claude 도구 정의.

BankKnowledgeBase의 조회 API를 Anthropic SDK tool runner용
@beta_tool 함수로 노출한다. 모든 결과는 JSON 문자열로 반환된다.
"""
from __future__ import annotations

import json

from anthropic import beta_tool

from knowledge.kb import BankKnowledgeBase

_kb: BankKnowledgeBase | None = None


def get_kb() -> BankKnowledgeBase:
    global _kb
    if _kb is None:
        _kb = BankKnowledgeBase()
    return _kb


def _dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


@beta_tool
def search_banking_concepts(query: str, limit: int = 10) -> str:
    """은행 온톨로지에서 개념을 검색한다. 한국어/영어 레이블과 정의에 대해 부분 일치 검색을 수행한다.

    Args:
        query: 검색어 (예: "대출", "예금자보호", "mortgage", "LTV").
        limit: 최대 결과 수 (기본 10).
    """
    results = get_kb().search_concepts(query, limit=limit)
    if not results:
        return _dumps({"message": f"'{query}'에 대한 검색 결과가 없습니다."})
    return _dumps([r.to_dict() for r in results])


@beta_tool
def get_concept_details(concept: str) -> str:
    """개념의 상세 정보(정의, 상위/하위 클래스, 관련 속성, FIBO 참조)를 조회한다.
    은행 용어의 정확한 의미나 개념 간 관계를 확인할 때 호출한다.

    Args:
        concept: 개념 이름. qname("loans:LTV"), 로컬명("MortgageLoanContract"),
            한국어 레이블("주택담보대출계약") 모두 허용.
    """
    detail = get_kb().get_concept(concept)
    if detail is None:
        return _dumps({"error": f"'{concept}' 개념을 찾을 수 없습니다. search_banking_concepts로 먼저 검색하세요."})
    return _dumps(detail.to_dict())


@beta_tool
def get_class_hierarchy(concept: str, depth: int = 3) -> str:
    """개념을 루트로 하는 하위 분류 체계(클래스 트리)를 조회한다.
    "어떤 종류의 X가 있는가?" 형태의 질문(예: 대출 상품 종류, 은행 유형)에 호출한다.

    Args:
        concept: 루트 클래스 이름 (예: "LoanProduct", "은행", "products:DepositProduct").
        depth: 탐색 깊이 (기본 3).
    """
    tree = get_kb().get_hierarchy(concept, depth=depth)
    if tree is None:
        return _dumps({"error": f"'{concept}' 클래스를 찾을 수 없습니다."})
    return _dumps(tree)


@beta_tool
def list_instances(concept: str, limit: int = 20) -> str:
    """클래스에 속하는 인스턴스(실제 데이터)를 조회한다. 하위 클래스의 인스턴스도 포함된다.

    Args:
        concept: 클래스 이름 (예: "Account", "LoanContract", "Bank").
        limit: 최대 결과 수 (기본 20).
    """
    instances = get_kb().get_instances(concept, limit=limit)
    if instances is None:
        return _dumps({"error": f"'{concept}' 클래스를 찾을 수 없습니다."})
    if not instances:
        return _dumps({"message": f"'{concept}'의 인스턴스가 없습니다."})
    return _dumps(instances)


@beta_tool
def describe_instance(instance: str) -> str:
    """특정 인스턴스의 모든 속성-값과 이를 참조하는 다른 개체를 조회한다.
    특정 고객, 계좌, 대출계약의 세부 내용을 확인할 때 호출한다.

    Args:
        instance: 인스턴스 이름 (예: "ex:KimMinjun", "LoanContract_KimMinjun").
    """
    desc = get_kb().describe_instance(instance)
    if desc is None:
        return _dumps({"error": f"'{instance}' 인스턴스를 찾을 수 없습니다."})
    return _dumps(desc)


@beta_tool
def run_sparql_query(query: str) -> str:
    """지식 그래프에 SPARQL SELECT 쿼리를 직접 실행한다.
    다른 도구로 답할 수 없는 복합 질의(조인, 필터, 집계)에만 사용한다.
    프리픽스 core:, parties:, products:, accounts:, loans:, transactions:, risk:, ex:는
    이미 바인딩되어 있으므로 PREFIX 선언 없이 사용할 수 있다.

    Args:
        query: SPARQL SELECT 쿼리 문자열.
    """
    try:
        rows = get_kb().run_sparql(query)
    except Exception as exc:  # noqa: BLE001
        return _dumps({"error": f"SPARQL 실행 오류: {exc}"})
    if not rows:
        return _dumps({"message": "쿼리 결과가 없습니다."})
    return _dumps(rows)


BANK_KB_TOOLS = [
    search_banking_concepts,
    get_concept_details,
    get_class_hierarchy,
    list_instances,
    describe_instance,
    run_sparql_query,
]
