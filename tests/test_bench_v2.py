#!/usr/bin/env python3
"""Bank-Onto-Bench v2 (HF 공개용 1,000문항) 무결성 테스트."""
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DATASET = REPO_ROOT / "data" / "bank-onto-bench-v2.jsonl"


def _rows():
    return [json.loads(l) for l in DATASET.read_text().splitlines() if l]


def test_size_and_ratio():
    rows = _rows()
    assert len(rows) == 1000, f"문항 수 {len(rows)} != 1000"
    by_qtype = Counter(r["qtype"] for r in rows)
    assert by_qtype["규정형"] == 300, f"규정형 {by_qtype['규정형']} != 300"
    assert by_qtype["공시형"] == 700, f"공시형 {by_qtype['공시형']} != 700"


def test_no_fictional_entities():
    text = DATASET.read_text()
    for banned in ("김민준", "한빛은행", "한빛 정기예금", "미르"):
        assert banned not in text, f"가상 개체 '{banned}' 포함됨"


def test_schema_and_unique_ids():
    rows = _rows()
    ids = [r["id"] for r in rows]
    assert len(set(ids)) == len(ids), "중복 id 존재"
    questions = [r["question"] for r in rows]
    assert len(set(questions)) == len(questions), "중복 질문 존재"
    for r in rows:
        assert r["answer_type"] in ("boolean", "numeric", "span", "abstain"), r["id"]
        assert r["answer"], r["id"]
        assert r["evidence"]["source"], f"{r['id']}: 출처 없음"
        if r["answer_type"] == "boolean":
            assert r["answer"] in ("YES", "NO"), r["id"]


def test_boolean_balance():
    rows = [r for r in _rows() if r["answer_type"] == "boolean"]
    yes = sum(1 for r in rows if r["answer"] == "YES")
    ratio = yes / len(rows)
    assert 0.4 <= ratio <= 0.6, f"YES 비율 편향: {ratio:.0%} ({yes}/{len(rows)})"


def test_category_coverage():
    cats = Counter(r["category"] for r in _rows())
    for cat in ("예금", "대출", "카드", "외환", "퇴직연금", "펀드"):
        assert cats.get(cat, 0) >= 20, f"'{cat}' 문항 부족: {cats.get(cat, 0)}"


def main() -> int:
    tests = [test_size_and_ratio, test_no_fictional_entities,
             test_schema_and_unique_ids, test_boolean_balance,
             test_category_coverage]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  [PASS] {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  [FAIL] {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
