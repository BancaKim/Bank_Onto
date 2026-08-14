"""Knowledge layer 단위 테스트 (API 키 불필요).

실행: python -m pytest tests/ -v   또는   python tests/test_knowledge_layer.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knowledge.kb import BankKnowledgeBase
from knowledge import tools

kb = BankKnowledgeBase()


def test_load():
    stats = kb.stats()
    assert stats["triples"] > 1000
    assert stats["classes"] > 100


def test_search_korean():
    results = kb.search_concepts("대출")
    assert results, "'대출' 검색 결과가 있어야 함"
    labels = [lbl for r in results for lbl in r.labels]
    assert any("대출" in lbl for lbl in labels)


def test_search_english():
    results = kb.search_concepts("mortgage")
    assert any("Mortgage" in r.uri for r in results)


def test_resolve_by_label():
    node = kb.resolve("주택담보대출계약")
    assert node is not None


def test_concept_details():
    detail = kb.get_concept("loans:MortgageLoanContract")
    assert detail is not None
    assert detail.kind == "class"
    assert any("주택담보대출계약" in lbl for lbl in detail.labels)
    assert any("SecuredLoanContract" in sup for sup in detail.superclasses)
    # 상위 클래스에서 상속된 속성(hasBorrower 등)이 보여야 함
    prop_names = [p["property"] for p in detail.properties]
    assert any("hasBorrower" in p for p in prop_names)


def test_hierarchy():
    tree = kb.get_hierarchy("products:FinancialProduct", depth=2)
    assert tree is not None
    children = {c["uri"] for c in tree.get("subclasses", [])}
    assert any("LoanProduct" in c for c in children)
    assert any("DepositProduct" in c for c in children)


def test_instances_include_subclasses():
    instances = kb.get_instances("accounts:Account")
    assert instances
    uris = [i["uri"] for i in instances]
    assert any("Account_KimMinjun" in u for u in uris)


def test_describe_instance():
    desc = kb.describe_instance("ex:LoanContract_KimMinjun")
    assert desc is not None
    props = [f["property"] for f in desc["facts"]]
    assert any("hasBorrower" in p for p in props)


def test_sparql_with_bound_prefixes():
    rows = kb.run_sparql("""
        SELECT ?loan ?ltv WHERE {
          ?loan loans:hasLTVValue ?ltv .
        }
    """)
    assert rows
    assert float(rows[0]["ltv"]) == 60.0


def test_tool_functions_return_json():
    out = json.loads(tools.search_banking_concepts.call({"query": "예금자보호"}))
    assert isinstance(out, list) and out

    out = json.loads(tools.get_concept_details.call({"concept": "DSR"}))
    assert out["kind"] == "class"

    out = json.loads(tools.get_class_hierarchy.call({"concept": "LoanProduct"}))
    assert "subclasses" in out

    out = json.loads(tools.run_sparql_query.call(
        {"query": "SELECT ?p WHERE { ?p a parties:CommercialBank }"}
    ))
    assert any("HanbitBank" in str(row) for row in out)

    out = json.loads(tools.get_concept_details.call({"concept": "존재하지않는개념XYZ"}))
    assert "error" in out


def main() -> int:
    test_fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in test_fns:
        try:
            fn()
            print(f"  [PASS] {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  [ERROR] {fn.__name__}: {exc}")
    print(f"\n{len(test_fns) - failed}/{len(test_fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
