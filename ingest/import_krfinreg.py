"""KR-FinReg-QA(석사논문 벤치마크) 은행 문항 → Bank_Onto 이식 변환기.

원본: ~/research_paper/experiments/questions.jsonl (306문항, YES/NO/ABSTAIN 판정형).
이 스크립트는 그중 **은행 상품 문항만** 골라 Bank_Onto 3-way 벤치마크 형식으로
변환해 data/krfinreg-bank-questions.jsonl 로 저장한다.

이식 규칙 (원본 벤치마크의 '정답은 원문에서 기계적으로 산출' 원칙 유지):
1. 저축은행·보험사·법령(law) 문항 제외 — 은행권 상품 문항만.
2. 원본은 202607 공시 기준이므로, 판정의 결정적 근거 문구(gold_basis의
   인용구)가 현재 적재된 공시 데이터(data/fss/*.json)에 그대로 존재할 때만
   이식한다. 문구가 바뀐 문항은 탈락시키고 사유를 기록한다 (정답 부패 방지).
3. 원본 질문은 닫힌 문서 설정("이 상품은 …?" + doc_id 범위 제공)이므로,
   개방형 검색 설정에 맞게 질문 문면에 은행명·상품명을 명시한다.
4. ABSTAIN(부재) 문항은 질문의 핵심어가 상품 원문 어디에도 없는지 재확인한다.

사용법:
    python ingest/import_krfinreg.py [--source PATH]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from ingest.fss_naming import clean_name  # noqa: E402

FSS_DIR = REPO_ROOT / "data" / "fss"
OUTPUT_PATH = REPO_ROOT / "data" / "krfinreg-bank-questions.jsonl"
DEFAULT_SOURCE = Path.home() / "research_paper" / "experiments" / "questions.jsonl"

JOIN_DENY_TEXT = {"1": "제한없음", "2": "서민전용", "3": "일부제한"}

# ABSTAIN 문항의 부재 재확인용 핵심어 (질문에 등장하는 것만 검사)
ABSENCE_TERMS = ["양도", "질권", "압류", "상속", "중도해지", "담보제공", "자동해지"]


def load_products() -> dict[tuple[str, str], dict]:
    """FSS 원본 JSON에서 (은행명, 상품코드) → 필드 사전. 판정 근거 재검증용.

    상품코드는 은행 간 충돌할 수 있으므로 반드시 은행명과 복합키로 쓴다.
    """
    products: dict[tuple[str, str], dict] = {}
    for path in sorted(FSS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data.get("baseList", []):
            products[(item["kor_co_nm"], item["fin_prdt_cd"])] = {
                "bank": item["kor_co_nm"],
                "name": clean_name(item["fin_prdt_nm"]),  # KB 적재와 동일 정규화
                "join_member": item.get("join_member") or "",
                "join_deny": JOIN_DENY_TEXT.get(
                    str(item.get("join_deny", "")).strip(), ""),
                "spcl_cnd": item.get("spcl_cnd") or "",
                "etc_note": item.get("etc_note") or "",
                "max_limit": str(item.get("max_limit") or ""),
            }
    return products


def is_bank_question(row: dict) -> bool:
    for doc_id in row.get("doc_ids", []):
        parts = doc_id.split(":")
        issuer = parts[1] if len(parts) > 1 else ""
        if issuer == "law" or doc_id.startswith("amend:"):
            return False
        if "저축은행" in issuer or "보험" in issuer:
            return False
    return True


def quoted_phrases(basis: str) -> list[str]:
    return re.findall(r"'([^']+)'", basis or "")


def adapt_row(row: dict, products: dict[str, dict]) -> tuple[dict | None, str]:
    """원본 문항 1건을 이식. (변환 결과, 탈락 사유) 중 하나만 채워진다."""
    doc_id = row["doc_ids"][0]
    parts = doc_id.split(":")
    if len(parts) != 4:
        return None, f"doc_id 형식 불일치: {doc_id}"
    _, bank, code, _month = parts

    product = products.get((bank, code))
    if product is None:
        return None, f"현재 공시에 상품 없음: {bank}:{code}"

    fulltext = " ".join(product[k] for k in
                        ("join_member", "join_deny", "spcl_cnd", "etc_note",
                         "max_limit", "name"))
    if "이 상품" in row["question"]:
        question = row["question"].replace(
            "이 상품", f"{product['bank']} '{product['name']}'")
    else:
        question = (f"{product['bank']} '{product['name']}' 상품에 대해: "
                    f"{row['question']}")

    verdict = row["gold_verdict"]
    evidence: list[str] = [product["name"]]

    if verdict == "ABSTAIN":
        terms = [t for t in ABSENCE_TERMS if t in row["question"]]
        hit = [t for t in terms if t in fulltext]
        if hit:
            return None, f"부재 전제 깨짐(원문에 {hit} 존재): {code}"
        evidence = []  # 부재 문항은 근거 없음이 정답
    else:
        phrases = quoted_phrases(row.get("gold_basis", ""))
        decisive = [p for p in phrases if p in fulltext]
        if not decisive:
            return None, (f"근거 문구 소실(공시 변경 추정): {code} "
                          f"{phrases}")
        evidence += decisive

    return {
        "id": row["qid"],
        "group": row["group"],
        "bank": product["bank"],
        "product_name": product["name"],
        "product_code": code,
        "question": question,
        "verdict": verdict,
        "gold": evidence,
        "basis": row.get("gold_basis", ""),
        "provenance": ("KR-FinReg-QA v1 (202607 공시) → 202608 공시로 "
                       "근거 재검증 후 이식"),
    }, ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()

    if not args.source.exists():
        print(f"원본 없음: {args.source}")
        return 1
    if not any(FSS_DIR.glob("*.json")):
        print("data/fss/ 에 공시 데이터가 없습니다. fss_client.py 먼저 실행.")
        return 1

    products = load_products()
    rows = [json.loads(l) for l in args.source.read_text().splitlines() if l]
    bank_rows = [r for r in rows if is_bank_question(r)]

    converted, dropped = [], []
    for row in bank_rows:
        adapted, reason = adapt_row(row, products)
        if adapted:
            converted.append(adapted)
        else:
            dropped.append((row["qid"], reason))

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for item in converted:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    from collections import Counter
    by_group = Counter((r["group"], r["verdict"]) for r in converted)
    print(f"이식: {len(converted)}문항 / 탈락 {len(dropped)}문항 "
          f"(원본 은행 문항 {len(bank_rows)}개 중)")
    for (g, v), c in sorted(by_group.items()):
        print(f"  {g} {v:8s} {c}")
    if dropped:
        print("탈락 사유:")
        for qid, reason in dropped:
            print(f"  {qid}: {reason}")
    print(f"저장: {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
