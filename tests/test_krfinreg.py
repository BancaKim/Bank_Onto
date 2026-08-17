#!/usr/bin/env python3
"""KR-FinReg-QA 은행 부분집합 이식 테스트 (API 키 불필요).

검증 항목:
1. FSS 적재가 판정형 문항에 필요한 필드(가입제한, 기타 유의사항)를 포함
2. 변환된 은행 문항 데이터셋의 무결성 (은행만, 근거가 KB에서 해석 가능)
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DATASET_PATH = REPO_ROOT / "data" / "krfinreg-bank-questions.jsonl"


def _kb():
    from knowledge.kb import BankKnowledgeBase
    global _KB_CACHE
    try:
        return _KB_CACHE
    except NameError:
        _KB_CACHE = BankKnowledgeBase()
        return _KB_CACHE


def test_kb_has_verdict_evidence_fields():
    """joinDenyNote·etcNote가 적재되어야 Q1(가입제한)·Q3(최소금액) 근거가 존재한다."""
    kb = _kb()
    deny = kb.run_sparql(
        "SELECT (COUNT(?p) AS ?c) WHERE { ?p market:joinDenyNote ?v }")
    note = kb.run_sparql(
        "SELECT (COUNT(?p) AS ?c) WHERE { ?p market:etcNote ?v }")
    assert int(deny[0]["c"]) >= 30, f"joinDenyNote 적재 부족: {deny[0]['c']}"
    assert int(note[0]["c"]) >= 30, f"etcNote 적재 부족: {note[0]['c']}"


def test_dataset_exists_and_bank_only():
    assert DATASET_PATH.exists(), f"{DATASET_PATH.name} 없음 — 변환기 미실행"
    rows = [json.loads(l) for l in DATASET_PATH.read_text().splitlines() if l]
    assert len(rows) >= 60, f"문항 수 부족: {len(rows)}"
    for row in rows:
        assert "저축은행" not in row["bank"], f"{row['id']}: 저축은행 포함"
        assert "보험" not in row["bank"], f"{row['id']}: 보험사 포함"
        assert row["verdict"] in ("YES", "NO", "ABSTAIN"), row["id"]
        # 질문 문면이 상품을 특정해야 리트리버가 찾을 수 있다 (개방형 검색 설정)
        assert row["product_name"] in row["question"], (
            f"{row['id']}: 질문에 상품명 없음"
        )


def test_dataset_evidence_resolvable_in_kb():
    """YES/NO 문항의 결정적 근거 문자열이 실제로 KB 직렬화 텍스트에 존재해야 한다."""
    from eval.corpus import build_documents

    text = "\n".join(build_documents(_kb()))
    rows = [json.loads(l) for l in DATASET_PATH.read_text().splitlines() if l]
    for row in rows:
        if row["verdict"] == "ABSTAIN":
            continue
        for ev in row["gold"]:
            assert ev in text, f"{row['id']}: 근거 '{ev}' 가 KB 코퍼스에 없음"


def main() -> int:
    tests = [
        test_kb_has_verdict_evidence_fields,
        test_dataset_exists_and_bank_only,
        test_dataset_evidence_resolvable_in_kb,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  [PASS] {test.__name__}")
        except Exception as exc:  # noqa: BLE001 — 테스트 실패 사유 표시용
            failed += 1
            print(f"  [FAIL] {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
