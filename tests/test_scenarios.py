"""시나리오 매트릭스 순수 함수 테스트 (API 키·KB 불필요).

실행: python tests/test_scenarios.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.scenarios import assemble, compact, context_engineer, retrieval_metrics


def test_assemble_respects_budget_and_truncates_first_unit():
    units = ["a" * 3000, "b" * 3000, "c" * 100]
    ctx = assemble(units, 4000)
    assert ctx == "a" * 3000, "두 번째 유닛은 예산 초과로 제외"
    assert assemble(["x" * 5000], 4000) == "x" * 4000, "첫 유닛은 잘라서라도 포함"
    assert assemble(units, None).count("\n\n") == 2


def test_compact_strips_qname_refs_but_keeps_lpg_headers():
    onto_unit = "[개체] 한빛 정기예금 (mktd:prdt_0019001_HB_TD_01)\n- 기본금리(연 %): 3.10\n- (역참조) 계좌 (ex:A) 이(가) [상품에 기반한다] 관계로 이 개체를 참조"
    c = compact(onto_unit)
    assert "(mktd:" not in c and "역참조" not in c and "3.10" in c
    lpg_header = "(mktd:prdt_0019001_HB_TD_01_opt0:RateOption)\n  기본금리(연 %): 3.10"
    assert compact(lpg_header).startswith("(mktd:"), "줄 첫머리 LPG 헤더는 보존"


def test_context_engineer_orders_individuals_before_properties_before_classes():
    units = ["[매칭된 개념] X(a:X)", "[개념] 정기예금 상품 (p:T)\n정의: ...",
             "[속성] 기본금리 (m:b)\n- A (m:a) → 3.1", "[개체] A (m:a)\n- 기본금리: 3.1",
             "[개체] B (m:b)\n- 기본금리: 2.9"]
    out = context_engineer(units, "A의 기본금리는?")
    assert out[0].startswith("[매칭된 개념]")
    kinds = [u[:4] for u in out[1:]]
    assert kinds == ["[개체]", "[개체]", "[속성]", "[개념]"], kinds
    assert out[1].startswith("[개체] A"), "같은 우선순위 안에서는 탐색 순서 보존"
    assert context_engineer([], "q") == []


def test_retrieval_metrics_definitions():
    units = ["상품 A 기본금리 3.1", "상품 B 기본금리 2.9", "상품 C"]
    m = retrieval_metrics(units, ["A", "3.1"])
    assert m["hit1"] == 1.0 and m["mrr"] == 1.0
    m = retrieval_metrics(units, ["A", "2.9"])           # 두 유닛에 걸친 근거
    assert m["hit1"] == 0.0 and abs(m["mrr"] - 0.5) < 1e-9
    assert m["recall@inf"] == 1.0
    m = retrieval_metrics(["x"], ["없는근거"])
    assert m["mrr"] == 0.0 and m["recall@4000"] == 0.0
    m = retrieval_metrics(["a" * 3995, "gold 여기"], ["gold"])   # 3995+2+7 > 4000
    assert m["recall@2000"] == 0.0 and m["recall@4000"] == 0.0 and m["recall@8000"] == 1.0


def main() -> int:
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  [PASS] {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
