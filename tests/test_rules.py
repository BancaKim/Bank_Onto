#!/usr/bin/env python3
"""규칙 계층(판단 패킷 엔진) 테스트 (API 키 불필요).

설계 계약 (research_paper rule_engine + SEOCHO 계약 개념 이식):
- 엔진이 판단하고 LLM은 설명만 한다 — 엔진에 LLM 호출이 없고 결정적이다.
- 3값 논리: 사실이 없으면 거짓이 아니라 '미상'(UNKNOWN)이다.
- 교차 검증: 엔진 판정은 Bench v2.2의 판정형 gold와 완전 일치해야 한다
  (동일 원문에서 독립적으로 산출된 두 경로가 같은 답에 도달).
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

BENCH = REPO_ROOT / "data" / "bank-onto-bench-v2.jsonl"


def _book():
    from knowledge.kb import BankKnowledgeBase
    from knowledge.rules import RuleBook
    global _BOOK
    try:
        return _BOOK
    except NameError:
        _BOOK = RuleBook.from_kb(BankKnowledgeBase())
        return _BOOK


def test_three_valued_logic():
    """사실 부족 → UNKNOWN(+부족 슬롯 명시), 위반 → DENIED, 충족 → CONFIRMED."""
    book = _book()
    # 연령 요건이 있는 상품을 하나 찾는다 (미즈월복리정기예금: 만19세 이상)
    packet = book.evaluate("광주은행", "미즈월복리정기예금", {})
    assert packet["verdict"] == "UNKNOWN", packet
    assert "age" in packet["missing_slots"], packet

    packet = book.evaluate("광주은행", "미즈월복리정기예금", {"age": 15})
    assert packet["verdict"] == "DENIED", packet

    packet = book.evaluate("광주은행", "미즈월복리정기예금",
                           {"age": 30, "channel": "영업점"})
    assert packet["verdict"] in ("CONFIRMED", "UNKNOWN"), packet
    # 근거 좌표가 반드시 포함된다 (SEOCHO의 supported answer 불변식)
    assert packet["evidence"], packet


def test_not_applicable_and_unknown_product():
    book = _book()
    packet = book.evaluate("없는은행", "없는상품", {"age": 30})
    assert packet["verdict"] == "NOT_APPLICABLE", packet


def test_cross_validation_against_benchmark():
    """엔진이 벤치마크 판정형 gold를 100% 재현해야 한다."""
    book = _book()
    rows = [json.loads(l) for l in BENCH.read_text().splitlines() if l]

    checked = mismatched = 0
    for row in rows:
        if row["template"] in ("age_condition", "joint_condition"):
            bank = row["evidence"]["locator"].split(":")[0]
            name_m = re.search(r"'([^']+)'", row["question"])
            age_m = re.search(r"만 (\d+)세", row["question"])
            facts = {"age": int(age_m.group(1))}
            ch_m = [c for c in ("영업점", "인터넷", "스마트폰", "전화(텔레뱅킹)")
                    if c in row["question"]]
            if row["template"] == "joint_condition":
                facts["channel"] = ch_m[0]
            packet = book.evaluate(bank, name_m.group(1), facts)
            expect = "CONFIRMED" if row["answer"] == "YES" else "DENIED"
            checked += 1
            if packet["verdict"] != expect:
                mismatched += 1
                if mismatched <= 3:
                    print(f"    불일치: {row['id']} gold={row['answer']} "
                          f"engine={packet['verdict']}")
        elif row["template"] == "rate_threshold":
            bank = row["evidence"]["locator"].split(":")[0]
            name_m = re.search(r"'([^']+)'", row["question"])
            probe_m = re.search(r"([\d.]+)%", row["question"])
            months_m = re.search(r"(\d+)개월", row["question"])
            packet = book.check_rate_claim(
                bank, name_m.group(1), float(probe_m.group(1)),
                months=int(months_m.group(1)))
            expect = "CONFIRMED" if row["answer"] == "YES" else "DENIED"
            checked += 1
            if packet["verdict"] != expect:
                mismatched += 1
                if mismatched <= 3:
                    print(f"    불일치: {row['id']} gold={row['answer']} "
                          f"engine={packet['verdict']}")
    assert checked >= 140, f"교차 검증 표본 부족: {checked}"
    assert mismatched == 0, f"gold 불일치 {mismatched}/{checked}"


def main() -> int:
    tests = [test_three_valued_logic, test_not_applicable_and_unknown_product,
             test_cross_validation_against_benchmark]
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
