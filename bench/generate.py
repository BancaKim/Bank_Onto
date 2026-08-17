"""Bank-Onto-Bench v2 생성기 — HF 공개용 은행 도메인 1,000문항.

구성 (규정형 300 : 공시형 700 = 3:7):
  공시형  금융감독원 금융상품통합비교공시(finlife.fss.or.kr) 은행권 실데이터에서
          템플릿 × 상품 조합으로 기계 생성. 정답은 공시 필드에서 직접 산출.
  규정형  국가법령정보센터(law.go.kr) 현행 법령 7종의 조문에서 기계 생성
          (조문위치·정의·법령메타·벌칙수치) + KR-FinReg-QA의 법령 시간형
          60문항(신구조문 유효기간 판정, 시행일 메타데이터 기반) 이식.

설계 원칙:
- 정답은 전부 원문(공시 필드·조문 텍스트·시행일)에서 기계적으로 산출. LLM 불개입.
- boolean 문항은 YES/NO 프로브를 쌍으로 생성해 균형 유지.
- 가상 개체(김민준·한빛은행 등) 불포함. 모든 문항에 출처 좌표(evidence) 포함.
- 실행마다 동일 출력 (정렬 순회, 난수 미사용).

실행: python bench/generate.py
출력: data/bank-onto-bench-v2.jsonl
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from ingest.fss_naming import clean_name, credit_name_resolver  # noqa: E402

FSS_DIR = REPO_ROOT / "data" / "fss"
LAWS_DIR = REPO_ROOT / "data" / "laws"
THESIS_QUESTIONS = Path.home() / "research_paper" / "experiments" / "questions.jsonl"
OUTPUT = REPO_ROOT / "data" / "bank-onto-bench-v2.jsonl"

FSS_SOURCE = "금융감독원 금융상품통합비교공시 Open API (finlife.fss.or.kr), 202608"
LAW_SOURCE = "국가법령정보센터 Open API (www.law.go.kr)"

KIND_META = {
    "deposit": ("예금", "정기예금"),
    "saving": ("예금", "적금"),
    "mortgage": ("대출", "주택담보대출"),
    "rent": ("대출", "전세자금대출"),
    "credit": ("대출", "신용대출"),
}

CHANNELS = ["영업점", "인터넷", "스마트폰", "전화(텔레뱅킹)"]


def fmt_rate(value) -> str:
    return f"{float(value):g}"


def _batchim(word: str) -> bool | None:
    last = word[-1]
    if "가" <= last <= "힣":
        return bool((ord(last) - ord("가")) % 28)
    return None


def eul_reul(word: str) -> str:
    """받침 유무에 따른 목적격 조사 선택 (한글이 아니면 '을(를)')."""
    b = _batchim(word)
    return "을(를)" if b is None else ("을" if b else "를")


def i_ga(word: str) -> str:
    b = _batchim(word)
    return "이(가)" if b is None else ("이" if b else "가")


def eun_neun(word: str) -> str:
    b = _batchim(word)
    return "은(는)" if b is None else ("은" if b else "는")


def gwa_wa(word: str) -> str:
    b = _batchim(word)
    return "과(와)" if b is None else ("과" if b else "와")


def pick(variants: list[str], *key_parts) -> str:
    """문면 변형을 결정적으로 배정한다 (zlib.crc32 — PYTHONHASHSEED 무관).

    정답·근거 산출 경로와 무관하게 질문 표면형만 바꾼다. 변형 문안은 수작업으로
    작성·검수했으며 의미(판정 기준·단위·만기 조건)는 모든 변형에서 동일하다.
    """
    import zlib
    idx = zlib.crc32(":".join(str(p) for p in key_parts).encode()) % len(variants)
    return variants[idx]


# ----------------------------------------------------------------------
# 공시형 (상품)
# ----------------------------------------------------------------------
def load_products() -> list[dict]:
    products = []
    for kind in KIND_META:
        path = FSS_DIR / f"{kind}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        options_by_code: dict[str, list] = {}
        for opt in data.get("optionList", []):
            options_by_code.setdefault(
                f"{opt['fin_co_no']}:{opt['fin_prdt_cd']}", []).append(opt)
        credit_name = credit_name_resolver(data.get("baseList", []))
        for item in data.get("baseList", []):
            key = f"{item['fin_co_no']}:{item['fin_prdt_cd']}"
            # 명명 규칙은 KB 적재(fss_to_ttl)와 공유 (ingest/fss_naming.py)
            name = credit_name(item) if kind == "credit" \
                else clean_name(item["fin_prdt_nm"])
            products.append({
                "kind": kind,
                "bank": item["kor_co_nm"],
                "name": name,
                "code": item["fin_prdt_cd"],
                "join_way": item.get("join_way") or "",
                "join_member": item.get("join_member") or "",
                "spcl_cnd": item.get("spcl_cnd") or "",
                "etc_note": item.get("etc_note") or "",
                "max_limit": str(item.get("max_limit") or ""),
                "options": sorted(options_by_code.get(key, []),
                                  key=lambda o: json.dumps(o, sort_keys=True)),
            })
    products.sort(key=lambda p: (p["kind"], p["bank"], p["code"]))
    return products


def evidence_of(product: dict, field: str, value: str) -> dict:
    return {"source": FSS_SOURCE,
            "locator": f"{product['bank']}:{product['code']}:{field}",
            "text": str(value)[:200]}


def label(product: dict) -> str:
    return f"{product['bank']} '{product['name']}'"


def term_option(product: dict, months: int):
    for opt in product["options"]:
        if str(opt.get("save_trm")) == str(months):
            return opt
    return None


def gen_base_rate(products):  # P1: 예금 12개월 기본금리 조회
    out = []
    for p in (x for x in products if x["kind"] == "deposit"):
        opt = term_option(p, 12)
        if opt and opt.get("intr_rate"):
            rate = fmt_rate(opt["intr_rate"])
            question = pick([
                f"{label(p)}의 12개월 만기 기본금리는 연 몇 %인가?",
                f"{label(p)}에 12개월 만기로 가입하면 기본금리는 연 몇 %가 적용되는가?",
                f"12개월 만기 기준으로 {label(p)}의 기본금리는 연 몇 %인가?",
                f"{label(p)}의 1년(12개월) 만기 기본금리로 공시된 값은 연 몇 %인가?",
            ], "base_rate", p["code"])
            out.append({
                "template": "base_rate_lookup",
                "category": "예금", "subcategory": "정기예금",
                "question": question,
                "answer_type": "numeric", "answer": rate, "unit": "%",
                "evidence": evidence_of(p, "intr_rate(12개월)", rate),
            })
    return out


def gen_max_rate(products):  # P3: 적금 최고우대금리 조회
    out = []
    for p in (x for x in products if x["kind"] == "saving"):
        opt = term_option(p, 12) or (p["options"][0] if p["options"] else None)
        if opt and opt.get("intr_rate2"):
            months = opt.get("save_trm")
            rate = fmt_rate(opt["intr_rate2"])
            question = pick([
                f"{label(p)}의 {months}개월 만기 최고 우대금리는 연 몇 %인가?",
                f"우대조건을 모두 충족하면 {label(p)}의 {months}개월 만기 금리는 최고 연 몇 %인가?",
                f"{label(p)}에서 {months}개월 만기로 받을 수 있는 최고 우대금리는 연 몇 %인가?",
                f"{months}개월 만기 기준 {label(p)}의 최고 우대금리로 공시된 값은?",
            ], "max_rate", p["code"])
            out.append({
                "template": "max_rate_lookup",
                "category": "예금", "subcategory": "적금",
                "question": question,
                "answer_type": "numeric", "answer": rate, "unit": "%",
                "evidence": evidence_of(p, f"intr_rate2({months}개월)", rate),
            })
    return out


def gen_rate_threshold(products):  # P2: 우대금리 임계 판정 (YES/NO 쌍)
    out = []
    for p in (x for x in products if x["kind"] in ("deposit", "saving")):
        opt = term_option(p, 12) or (p["options"][0] if p["options"] else None)
        if not (opt and opt.get("intr_rate2")):
            continue
        months, value = opt.get("save_trm"), float(opt["intr_rate2"])
        cat, sub = KIND_META[p["kind"]]
        for probe, verdict in ((value - 0.2, "YES"), (value + 0.2, "NO")):
            if probe <= 0:
                continue
            question = pick([
                f"{label(p)}의 {months}개월 만기 최고 우대금리는 연 {probe:.2f}% 이상인가?",
                f"{months}개월 만기 기준, {label(p)}의 최고 우대금리가 연 {probe:.2f}% 이상인가?",
                f"{label(p)}({months}개월 만기)의 최고 우대금리는 연 {probe:.2f}%보다 높거나 같은가?",
                f"연 {probe:.2f}% 이상의 최고 우대금리를 {label(p)}의 {months}개월 만기에서 기대할 수 있는가?",
            ], "rate_threshold", p["code"], verdict)
            out.append({
                "template": "rate_threshold",
                "category": cat, "subcategory": sub,
                "question": question,
                "answer_type": "boolean", "answer": verdict,
                "evidence": evidence_of(p, f"intr_rate2({months}개월)",
                                        fmt_rate(value)),
            })
    return out


def gen_join_way(products):  # P4: 가입경로 판정 (YES/NO 쌍)
    out = []
    for p in products:
        ways = [w.strip() for w in p["join_way"].split(",") if w.strip()]
        present = [c for c in CHANNELS if c in ways]
        absent = [c for c in CHANNELS if c not in ways]
        cat, sub = KIND_META[p["kind"]]
        for channel, verdict in ((present[0] if present else None, "YES"),
                                 (absent[0] if absent else None, "NO")):
            if channel is None:
                continue
            question = pick([
                f"{label(p)}은(는) {channel} 경로로 가입할 수 있는가?",
                f"{channel} 채널을 통해 {label(p)}에 가입할 수 있는가?",
                f"{label(p)}의 가입 경로에 {channel}{i_ga(channel)} 포함되는가?",
                f"{label(p)}은(는) {channel}{eul_reul(channel)} 통한 가입이 가능한 상품인가?",
            ], "join_way", p["code"], channel)
            out.append({
                "template": "join_way",
                "category": cat, "subcategory": sub,
                "question": question,
                "answer_type": "boolean", "answer": verdict,
                "evidence": evidence_of(p, "join_way", p["join_way"]),
            })
    return out


def gen_age_condition(products):  # P5: 가입연령 판정 (YES/NO 쌍)
    out = []
    for p in products:
        m = re.search(r"만\s?(\d{2})세\s?이상", p["join_member"])
        if not m:
            continue
        age = int(m.group(1))
        cat, sub = KIND_META[p["kind"]]
        for probe, verdict in ((age + 3, "YES"), (age - 3, "NO")):
            if probe <= 0:
                continue
            question = pick([
                f"만 {probe}세인 개인이 {label(p)}의 가입 연령 요건(연령 외 요건은 충족 가정)을 충족하는가?",
                f"{label(p)}은(는) 만 {probe}세 개인이 가입할 수 있는 연령 요건인가? (연령 외 요건은 충족 가정)",
                f"연령 요건만 볼 때, 만 {probe}세가 {label(p)}에 가입 가능한가? (그 외 요건은 충족 가정)",
            ], "age", p["code"], verdict)
            out.append({
                "template": "age_condition",
                "category": cat, "subcategory": sub,
                "question": question,
                "answer_type": "boolean", "answer": verdict,
                "evidence": evidence_of(p, "join_member", p["join_member"]),
            })
    return out


def gen_max_limit(products):  # P6: 최고한도 조회
    out = []
    for p in products:
        limit = p["max_limit"].strip()
        if not limit or limit.lower() in ("none", "null"):
            continue
        cat, sub = KIND_META[p["kind"]]
        gold = f"{int(limit):,}원" if limit.isdigit() else limit
        question = pick([
            f"{label(p)}의 공시된 최고 한도는 얼마인가?",
            f"{label(p)}의 최고 한도로 공시된 금액은 얼마인가?",
            f"공시 기준으로 {label(p)}의 한도 상한은 얼마인가?",
        ], "max_limit", p["code"])
        out.append({
            "template": "max_limit_lookup",
            "category": cat, "subcategory": sub,
            "question": question,
            "answer_type": "span", "answer": gold,
            "evidence": evidence_of(p, "max_limit", limit),
        })
    return out


def gen_interest_type(products):  # P7: 이자계산방식 (단리/복리)
    out = []
    for p in (x for x in products if x["kind"] in ("deposit", "saving")):
        types = {o.get("intr_rate_type_nm") for o in p["options"]
                 if o.get("intr_rate_type_nm")}
        if len(types) != 1:
            continue  # 단리·복리 둘 다 있으면 단답이 성립하지 않음
        cat, sub = KIND_META[p["kind"]]
        question = pick([
            f"{label(p)}의 공시된 이자 계산 방식은 단리인가 복리인가?",
            f"{label(p)}은(는) 단리와 복리 중 어느 방식으로 이자를 계산하는가?",
            f"이자 계산 방식(단리/복리) 기준으로 {label(p)}은(는) 어느 쪽인가?",
        ], "calc_type", p["code"])
        out.append({
            "template": "interest_calc_type",
            "category": cat, "subcategory": sub,
            "question": question,
            "answer_type": "span", "answer": types.pop(),
            "evidence": evidence_of(p, "intr_rate_type_nm",
                                    p["options"][0].get("intr_rate_type_nm", "")),
        })
    return out


def gen_loan_rate(products):  # P8: 담보유형·금리방식별 최저금리 조회
    out = []
    for p in (x for x in products if x["kind"] in ("mortgage", "rent")):
        cat, sub = KIND_META[p["kind"]]
        seen = set()
        for opt in p["options"]:
            mtype = opt.get("mrtg_type_nm") or ""
            ltype = opt.get("lend_rate_type_nm") or ""
            rate = opt.get("lend_rate_min")
            key = (mtype, ltype)
            if not (ltype and rate) or key in seen:
                continue
            seen.add(key)
            qual = f"{mtype} 담보 " if mtype else ""
            question = pick([
                f"{label(p)}의 {qual}{ltype} 방식 최저금리는 연 몇 %인가?",
                f"{qual}{ltype} 조건에서 {label(p)} 상품이 공시한 최저금리는 연 몇 %인가?",
                f"{label(p)}에서 {qual}{ltype} 방식으로 대출할 때 최저금리는 연 몇 %인가?",
            ], "loan_min", p["code"], mtype, ltype)
            out.append({
                "template": "loan_min_rate",
                "category": cat, "subcategory": sub,
                "question": question,
                "answer_type": "numeric", "answer": fmt_rate(rate), "unit": "%",
                "evidence": evidence_of(
                    p, f"lend_rate_min({mtype or '-'}/{ltype})", fmt_rate(rate)),
            })
    return out


def gen_loan_rate_type(products):  # P9: 금리방식 취급 여부 (YES/NO 쌍)
    out = []
    universe = ["고정금리", "변동금리"]
    for p in (x for x in products if x["kind"] in ("mortgage", "rent")):
        offered = {o.get("lend_rate_type_nm") for o in p["options"]
                   if o.get("lend_rate_type_nm")}
        present = [t for t in universe if t in offered]
        absent = [t for t in universe if t not in offered]
        cat, sub = KIND_META[p["kind"]]
        for rate_type, verdict in ((present[0] if present else None, "YES"),
                                   (absent[0] if absent else None, "NO")):
            if rate_type is None:
                continue
            question = pick([
                f"{label(p)}에서 {rate_type} 방식을 선택할 수 있는가?",
                f"{label(p)}의 금리 방식 옵션에 {rate_type}{i_ga(rate_type)} 있는가?",
                f"{rate_type} 방식으로 {label(p)} 대출을 받는 것이 가능한가?",
            ], "loan_type", p["code"], rate_type)
            out.append({
                "template": "loan_rate_type",
                "category": cat, "subcategory": sub,
                "question": question,
                "answer_type": "boolean", "answer": verdict,
                "evidence": evidence_of(
                    p, "lend_rate_type_nm", ", ".join(sorted(offered)) or "없음"),
            })
    return out


def gen_credit_rate(products):  # P10: 신용대출 평균금리 조회
    out = []
    for p in (x for x in products if x["kind"] == "credit"):
        for opt in p["options"]:
            if opt.get("crdt_lend_rate_type") == "A" and opt.get("crdt_grad_avg"):
                rate = fmt_rate(opt["crdt_grad_avg"])
                question = pick([
                    f"{label(p)}의 공시된 평균 대출금리는 연 몇 %인가?",
                    f"{label(p)}의 평균 금리는 공시 기준 연 몇 %인가?",
                    f"공시상 {label(p)}의 평균 대출금리는 연 몇 %인가?",
                ], "credit_avg", p["code"])
                out.append({
                    "template": "credit_avg_rate",
                    "category": "대출", "subcategory": "신용대출",
                    "question": question,
                    "answer_type": "numeric", "answer": rate, "unit": "%",
                    "evidence": evidence_of(p, "crdt_grad_avg", rate),
                })
                break
    return out


def gen_abstain(products):  # P11: 공시에 없는 항목 (보류가 정답)
    out = []
    for p in products:
        cat, sub = KIND_META[p["kind"]]
        if not p["max_limit"].strip():
            question = pick([
                f"{label(p)}의 공시된 최고 한도 금액은 얼마인가?",
                f"{label(p)}의 최고 한도는 공시에서 얼마로 확인되는가?",
                f"{label(p)}의 한도 상한 금액을 공시에서 찾으면 얼마인가?",
            ], "abstain_limit", p["code"])
            out.append({
                "template": "abstain_missing_field",
                "category": cat, "subcategory": sub,
                "question": question,
                "answer_type": "abstain", "answer": "공시에 해당 정보 없음",
                "evidence": evidence_of(p, "max_limit", "(공시값 없음)"),
            })
        elif not p["spcl_cnd"].strip():
            question = pick([
                f"{label(p)}의 공시된 우대금리 조건은 무엇인가?",
                f"{label(p)}에 적용되는 우대금리 조건을 공시에서 찾으면 무엇인가?",
                f"{label(p)}의 우대조건으로 공시된 내용은 무엇인가?",
            ], "abstain_spcl", p["code"])
            out.append({
                "template": "abstain_missing_field",
                "category": cat, "subcategory": sub,
                "question": question,
                "answer_type": "abstain", "answer": "공시에 해당 정보 없음",
                "evidence": evidence_of(p, "spcl_cnd", "(공시값 없음)"),
            })
    return out


KIND_KO = {"deposit": "정기예금", "saving": "적금",
           "mortgage": "주택담보대출", "rent": "전세자금대출", "credit": "신용대출"}


def _rate12(p: dict):
    opt = term_option(p, 12)
    return float(opt["intr_rate2"]) if opt and opt.get("intr_rate2") else None


def gen_compare_two(products):  # P12: 동일 은행 두 상품 금리 비교 (2지선다)
    out = []
    by_bank_kind: dict[tuple, list] = {}
    for p in (x for x in products if x["kind"] in ("deposit", "saving")):
        if _rate12(p) is not None:
            by_bank_kind.setdefault((p["bank"], p["kind"]), []).append(p)
    for (bank, kind), items in sorted(by_bank_kind.items()):
        for a, b in zip(items, items[1:]):
            ra, rb = _rate12(a), _rate12(b)
            if ra == rb:
                continue
            winner = a if ra > rb else b
            question = pick([
                f"{bank}의 '{a['name']}'{gwa_wa(a['name'])} '{b['name']}' 중 12개월 만기 최고 우대금리가 더 높은 상품은?",
                f"12개월 만기 최고 우대금리 기준으로, {bank}의 '{a['name']}'{gwa_wa(a['name'])} '{b['name']}' 중 어느 상품이 유리한가?",
                f"{bank}의 두 상품 '{a['name']}'{gwa_wa(a['name'])} '{b['name']}'{eul_reul(b['name'])} 비교하면 12개월 만기 최고 우대금리가 높은 쪽은?",
            ], "compare", a["code"], b["code"])
            out.append({
                "template": "compare_two_products",
                "category": "예금", "subcategory": KIND_KO[kind],
                "question": question,
                "answer_type": "span", "answer": winner["name"],
                "evidence": {"source": FSS_SOURCE,
                             "locator": f"{bank}:{a['code']},{b['code']}:intr_rate2(12개월)",
                             "text": f"{a['name']}={fmt_rate(ra)}; {b['name']}={fmt_rate(rb)}"},
            })
    return out


def gen_agg_count(products):  # P13: 은행별 상품 수 집계 (COUNT)
    out = []
    by_bank_kind: dict[tuple, list] = {}
    for p in (x for x in products if x["kind"] in ("deposit", "saving",
                                                   "mortgage", "rent")):
        by_bank_kind.setdefault((p["bank"], p["kind"]), []).append(p)
    for (bank, kind), items in sorted(by_bank_kind.items()):
        if len(items) < 2:
            continue  # 1개짜리 집계는 사실상 조회형
        names = sorted(p["name"] for p in items)
        question = pick([
            f"{bank}{i_ga(bank)} 공시한 {KIND_KO[kind]} 상품은 모두 몇 개인가?",
            f"현재 공시 기준으로 {bank}의 {KIND_KO[kind]} 상품 수는 몇 개인가?",
            f"{bank}의 {KIND_KO[kind]} 상품을 전부 세면 몇 개인가?",
        ], "count", bank, kind)
        out.append({
            "template": "agg_count",
            "category": KIND_META[kind][0], "subcategory": KIND_KO[kind],
            "question": question,
            "answer_type": "numeric", "answer": str(len(items)), "unit": "개",
            "evidence": {"source": FSS_SOURCE,
                         "locator": f"{bank}:{kind}:baseList",
                         "text": "; ".join(names)},
        })
    return out


def gen_agg_superlative(products):  # P14: 전체 은행 최고/최저 (정렬)
    out = []
    for kind in ("deposit", "saving"):
        candidates = [(p, _rate12(p)) for p in products
                      if p["kind"] == kind and _rate12(p) is not None]
        if not candidates:
            continue
        top_rate = max(r for _, r in candidates)
        winners = sorted(p["name"] for p, r in candidates if r == top_rate)
        if len(winners) != 1:
            continue  # 공동 1위면 단답이 성립하지 않음
        question = pick([
            f"전체 은행의 {KIND_KO[kind]} 중 12개월 만기 최고 우대금리가 가장 높은 상품은 무엇인가?",
            f"공시된 모든 은행 {KIND_KO[kind]}에서 12개월 만기 최고 우대금리 1위 상품은?",
        ], "superlative", kind)
        out.append({
            "template": "agg_superlative",
            "category": "예금", "subcategory": KIND_KO[kind],
            "question": question,
            "answer_type": "span", "answer": winners[0],
            "evidence": {"source": FSS_SOURCE,
                         "locator": f"전체:{kind}:max(intr_rate2, 12개월)",
                         "text": f"{winners[0]}={fmt_rate(top_rate)}"},
        })
    return out


def gen_enumerate(products):  # P15: 은행별 상품 완전 열거
    out = []
    by_bank_kind: dict[tuple, list] = {}
    for p in (x for x in products if x["kind"] in ("deposit", "saving")):
        by_bank_kind.setdefault((p["bank"], p["kind"]), []).append(p)
    for (bank, kind), items in sorted(by_bank_kind.items()):
        if not 2 <= len(items) <= 5:
            continue  # 너무 많으면 단답 채점이 무의미
        names = sorted(p["name"] for p in items)
        question = pick([
            f"{bank}의 {KIND_KO[kind]} 상품을 모두 나열하면?",
            f"{bank}{i_ga(bank)} 공시한 {KIND_KO[kind]} 상품 전체 목록은?",
        ], "enumerate", bank, kind)
        out.append({
            "template": "enumerate_products",
            "category": "예금", "subcategory": KIND_KO[kind],
            "question": question,
            "answer_type": "span", "answer": ", ".join(names),
            "evidence": {"source": FSS_SOURCE,
                         "locator": f"{bank}:{kind}:baseList",
                         "text": "; ".join(names)},
        })
    return out


# ----------------------------------------------------------------------
# 계산 추론 축 (v2.2) — 정답이 문서에 직접 적혀 있지 않고 계산해야만 나온다.
# 단리 12개월 정기예금만 사용해 계산 규약이 논쟁의 여지 없이 정의되도록 한다.
# ----------------------------------------------------------------------
from decimal import ROUND_HALF_UP, Decimal

TAX_RATE = Decimal("0.154")  # 이자소득세(지방소득세 포함) 15.4% 가정


def _danri_deposits(products):
    out = []
    for p in (x for x in products if x["kind"] == "deposit"):
        opt = term_option(p, 12)
        if opt and opt.get("intr_rate") and opt.get("intr_rate_type_nm") == "단리":
            out.append((p, Decimal(str(opt["intr_rate"]))))
    return out


def _pretax_interest(principal: int, rate: Decimal) -> Decimal:
    """12개월 단리 세전 이자 = 원금 × 연이율."""
    return (Decimal(principal) * rate / 100).quantize(Decimal("1"), ROUND_HALF_UP)


def gen_calc_interest(products):  # C1: 만기 세전 이자 계산
    out = []
    principals = [5_000_000, 10_000_000, 30_000_000]
    for p, rate in _danri_deposits(products):
        principal = principals[int(pick(["0", "1", "2"], "prin", p["code"]))]
        interest = _pretax_interest(principal, rate)
        question = pick([
            f"{label(p)}에 {principal:,}원을 12개월 만기로 예치하면 만기 세전 이자는 얼마인가? (단리, 공시 기본금리 기준)",
            f"{principal:,}원을 {label(p)}에 12개월 예치할 때 받는 세전 이자를 계산하면? (단리, 공시 기본금리 기준)",
            f"{label(p)}의 공시 기본금리(단리)로 {principal:,}원을 12개월 예치하면 세전 이자는 총 얼마인가?",
        ], "calc_int", p["code"])
        out.append({
            "template": "calc_interest",
            "category": "예금", "subcategory": "정기예금",
            "question": question,
            "answer_type": "numeric", "answer": str(interest), "unit": "원",
            "evidence": evidence_of(p, "intr_rate(12개월,단리)", fmt_rate(rate)),
        })
    return out


def gen_calc_after_tax(products):  # C2: 세후 이자 계산 (2단계)
    out = []
    principals = [10_000_000, 20_000_000, 50_000_000]
    for p, rate in _danri_deposits(products):
        principal = principals[int(pick(["0", "1", "2"], "prin_at", p["code"]))]
        pretax = Decimal(principal) * rate / 100
        after = (pretax * (1 - TAX_RATE)).quantize(Decimal("1"), ROUND_HALF_UP)
        question = pick([
            f"{label(p)}에 {principal:,}원을 12개월 예치하면(단리), 이자소득세 15.4%를 공제한 세후 이자는 얼마인가? (원 미만 반올림)",
            f"{principal:,}원을 {label(p)}에 12개월 넣었을 때 세후 이자는? (단리, 이자소득세 15.4% 공제, 원 미만 반올림)",
            f"{label(p)}의 공시 기본금리(단리) 기준, {principal:,}원 12개월 예치의 세후 수령 이자(이자소득세 15.4% 공제, 원 미만 반올림)는?",
        ], "calc_at", p["code"])
        out.append({
            "template": "calc_interest_after_tax",
            "category": "예금", "subcategory": "정기예금",
            "question": question,
            "answer_type": "numeric", "answer": str(after), "unit": "원",
            "evidence": evidence_of(p, "intr_rate(12개월,단리)", fmt_rate(rate)),
        })
    return out


def gen_calc_diff(products):  # C3: 두 상품 이자 차이 (조회 2회 + 계산 3회)
    out = []
    pool = _danri_deposits(products)
    principal = 10_000_000
    for (a, ra), (b, rb) in zip(pool, pool[1:]):
        if ra == rb:
            continue
        diff = abs(_pretax_interest(principal, ra) - _pretax_interest(principal, rb))
        question = pick([
            f"{label(a)}{gwa_wa(a['name'])} {label(b)}에 각각 {principal:,}원을 12개월 예치하면(단리, 공시 기본금리) 만기 세전 이자 차이는 얼마인가?",
            f"{principal:,}원을 12개월 예치할 때 {label(a)}{gwa_wa(a['name'])} {label(b)}의 세전 이자 차이를 계산하면? (단리, 공시 기본금리)",
        ], "calc_diff", a["code"], b["code"])
        out.append({
            "template": "calc_interest_diff",
            "category": "예금", "subcategory": "정기예금",
            "question": question,
            "answer_type": "numeric", "answer": str(diff), "unit": "원",
            "evidence": {"source": FSS_SOURCE,
                         "locator": f"{a['bank']}:{a['code']},{b['bank']}:{b['code']}:intr_rate(12개월)",
                         "text": f"{a['name']}={fmt_rate(ra)}; {b['name']}={fmt_rate(rb)}"},
        })
    return out


def gen_joint_condition(products):  # C4: 연령 × 가입경로 결합 판정
    out = []
    for p in products:
        m = re.search(r"만\s?(\d{2})세\s?이상", p["join_member"])
        ways = [w.strip() for w in p["join_way"].split(",") if w.strip()]
        present = [c for c in CHANNELS if c in ways]
        absent = [c for c in CHANNELS if c not in ways]
        if not (m and present):
            continue
        age = int(m.group(1))
        yes_case = (age + 4, present[0], "YES")
        if absent and pick(["a", "b"], "joint_no", p["code"]) == "a":
            no_case = (age + 4, absent[0], "NO")   # 경로 요건 위반
        else:
            no_case = (age - 4, present[0], "NO")  # 연령 요건 위반
        for probe_age, channel, verdict in (yes_case, no_case):
            if probe_age <= 0:
                continue
            question = pick([
                f"만 {probe_age}세인 개인이 {channel} 경로로 {label(p)}에 가입하려 한다. 연령 요건과 가입 경로 요건을 모두 충족하는가? (그 외 요건은 충족 가정)",
                f"{label(p)}에 만 {probe_age}세 개인이 {channel}{eul_reul(channel)} 통해 가입하는 경우, 연령·가입경로 요건이 동시에 충족되는가? (그 외 요건은 충족 가정)",
            ], "joint", p["code"], verdict)
            out.append({
                "template": "joint_condition",
                "category": KIND_META[p["kind"]][0],
                "subcategory": KIND_META[p["kind"]][1],
                "question": question,
                "answer_type": "boolean", "answer": verdict,
                "evidence": {"source": FSS_SOURCE,
                             "locator": f"{p['bank']}:{p['code']}:join_member,join_way",
                             "text": f"{p['join_member']} | {p['join_way']}"[:200]},
            })
    return out


# ----------------------------------------------------------------------
# 규정형 (법령)
# ----------------------------------------------------------------------
def load_laws() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(LAWS_DIR.glob("*.json"))]


def law_evidence(law: dict, article: dict) -> dict:
    return {"source": f"{LAW_SOURCE} — {law['name']} (시행 {law['effective_date']})",
            "locator": article["label"],
            "text": article["text"][:200]}


# 조문위치형 법령별 할당 (카테고리 최소 커버리지 보장)
R1_QUOTA = {
    "여신전문금융업법": 26, "외국환거래법": 19, "근로자퇴직급여 보장법": 24,
    "자본시장과 금융투자업에 관한 법률": 24, "은행법": 14,
    "예금자보호법": 14, "금융소비자 보호에 관한 법률": 10,
}


def gen_article_locate(laws):  # R1: 조문 위치형
    out = []
    for law in laws:
        titles: dict[str, list] = {}
        for art in law["articles"]:
            if art["title"] and len(art["title"]) >= 3:
                titles.setdefault(art["title"], []).append(art)
        unique = [(t, arts[0]) for t, arts in sorted(titles.items())
                  if len(arts) == 1]
        for title, art in unique[:R1_QUOTA.get(law["name"], 10)]:
            question = pick([
                f"「{law['name']}」에서 '{title}'{eul_reul(title)} 규정한 조문은 몇 조인가?",
                f"'{title}' 조항은 「{law['name']}」의 몇 조에 있는가?",
                f"「{law['name']}」의 어느 조문이 '{title}'{eul_reul(title)} 다루는가?",
                f"「{law['name']}」에서 '{title}' 관련 규정은 제 몇 조인가?",
            ], "article", law["slug"], art["label"])
            out.append({
                "template": "article_locate",
                "category": law["category"], "subcategory": law["name"],
                "question": question,
                "answer_type": "span", "answer": art["label"],
                "evidence": law_evidence(law, art),
            })
    return out


DEF_PATTERN = re.compile(
    r'"([^"]{2,25})"(?:이?란|이라 함은)\s*([^\n]{15,180}?)(?:를|을) 말한다')


def gen_definitions(laws):  # R2: 정의형 (용어 역조회)
    out = []
    for law in laws:
        count = 0
        for art in law["articles"]:
            if "정의" not in art["title"]:
                continue
            for term, definition in DEF_PATTERN.findall(art["text"]):
                if count >= 12:
                    break
                definition = re.sub(r"\s+", " ", definition).strip()
                # "다음 각 목의 …" 류는 참조문이지 정의가 아님 (용어 특정 불가)
                if "다음 각" in definition or len(definition) < 25:
                    continue
                # 중첩 "말한다"로 정의가 괄호 중간에서 잘린 경우 제외
                if definition.count("(") != definition.count(")"):
                    continue
                question = pick([
                    f"「{law['name']}」 {art['label']}(정의)에서 “{definition}”(으)로 정의되는 용어는 무엇인가?",
                    f"「{law['name']}」 {art['label']}에서 “{definition}”(이)라고 정의된 용어는 무엇인가?",
                    f"다음은 「{law['name']}」 {art['label']}의 정의 조문이다: “{definition}” — 이 정의가 가리키는 용어는?",
                ], "definition", law["slug"], term)
                # 정답 용어가 질문 문면(정의문·법령명 포함)에 노출되면 제외
                if term in question:
                    continue
                out.append({
                    "template": "definition_term",
                    "category": law["category"], "subcategory": law["name"],
                    "question": question,
                    "answer_type": "span", "answer": term,
                    "evidence": law_evidence(law, art),
                })
                count += 1
    return out


def gen_law_meta(laws):  # R3: 법령 메타형 (시행일·소관부처·법종)
    out = []
    for law in laws:
        eff = law["effective_date"]
        eff_fmt = f"{eff[:4]}-{eff[4:6]}-{eff[6:]}"
        meta_ev = {"source": f"{LAW_SOURCE} — {law['name']} 기본정보",
                   "locator": "기본정보", "text": f"시행 {eff_fmt}"}
        out.append({
            "template": "law_meta", "category": law["category"],
            "subcategory": law["name"],
            "question": pick([
                f"「{law['name']}」 현행 법령의 시행일자는 언제인가?",
                f"현행 「{law['name']}」은(는) 언제부터 시행되는가?",
            ], "meta_eff", law["slug"]),
            "answer_type": "span", "answer": eff_fmt, "evidence": meta_ev,
        })
        out.append({
            "template": "law_meta", "category": law["category"],
            "subcategory": law["name"],
            "question": pick([
                f"「{law['name']}」의 소관부처는 어디인가?",
                f"「{law['name']}」{eul_reul(law['name'])} 소관하는 정부 부처는?",
            ], "meta_min", law["slug"]),
            "answer_type": "span", "answer": law["ministry"], "evidence": meta_ev,
        })
    return out


PENALTY_PRISON = re.compile(r"(\d+)년 이하의 징역")
PENALTY_FINE = re.compile(r"(\d+(?:억|천만|백만)?원) 이하의 (벌금|과태료)")


def gen_penalties(laws):  # R4: 벌칙 수치형
    out = []
    for law in laws:
        for art in law["articles"]:
            if not any(k in art["title"] for k in ("벌칙", "과태료")):
                continue
            prisons = sorted(set(PENALTY_PRISON.findall(art["text"])),
                             key=lambda y: -int(y))
            fines = PENALTY_FINE.findall(art["text"])
            if prisons:
                question = pick([
                    f"「{law['name']}」 {art['label']}({art['title']})에서 정한 징역형의 최고 상한은 몇 년인가?",
                    f"「{law['name']}」 {art['label']}({art['title']})에 따르면 징역은 최대 몇 년까지인가?",
                    f"「{law['name']}」 {art['label']}({art['title']})의 징역형 상한은 몇 년인가?",
                ], "prison", law["slug"], art["label"])
                out.append({
                    "template": "penalty_amount",
                    "category": law["category"], "subcategory": law["name"],
                    "question": question,
                    "answer_type": "numeric", "answer": prisons[0], "unit": "년",
                    "evidence": law_evidence(law, art),
                })
            if fines:
                amounts = [a for a, _ in fines]
                kind = fines[0][1]
                top = max(amounts, key=lambda a: _won(a))
                question = pick([
                    f"「{law['name']}」 {art['label']}({art['title']})에서 정한 {kind}의 최고 상한은 얼마인가?",
                    f"「{law['name']}」 {art['label']}({art['title']})에 따르면 {kind}{eun_neun(kind)} 최대 얼마까지인가?",
                    f"「{law['name']}」 {art['label']}({art['title']})의 {kind} 상한 금액은?",
                ], "fine", law["slug"], art["label"])
                out.append({
                    "template": "penalty_amount",
                    "category": law["category"], "subcategory": law["name"],
                    "question": question,
                    "answer_type": "span", "answer": top,
                    "evidence": law_evidence(law, art),
                })
    return out


def _won(amount: str) -> int:
    m = re.match(r"(\d+)(억|천만|백만)?원", amount)
    scale = {"억": 10 ** 8, "천만": 10 ** 7, "백만": 10 ** 6, None: 1}
    return int(m.group(1)) * scale[m.group(2)] if m else 0


LAW_CATEGORY_HINTS = [
    ("퇴직연금", "퇴직연금"), ("퇴직급여", "퇴직연금"),
    ("여신전문", "카드"), ("외국환", "외환"), ("자본시장", "펀드"),
    ("예금자", "예금"), ("은행", "공통"), ("금융소비자", "공통"),
]


def import_temporal(path: Path):  # R5: KR-FinReg-QA 법령 시간형 이식
    if not path.exists():
        print(f"  [경고] 시간형 원본 없음: {path} — 건너뜀")
        return []
    out = []
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if row.get("group") != "Q2_시간":
            continue
        category = "공통"
        for hint, cat in LAW_CATEGORY_HINTS:
            if hint in row["question"]:
                category = cat
                break
        out.append({
            "template": "temporal_validity",
            "category": category, "subcategory": "법령 개정(신구조문)",
            "question": row["question"],
            "answer_type": "boolean", "answer": row["gold_verdict"],
            "evidence": {"source": f"{LAW_SOURCE} — 개정문 시행일 메타데이터 "
                                   f"(KR-FinReg-QA v1에서 이식)",
                         "locator": row["doc_ids"][0],
                         "text": row.get("gold_basis", "")[:200]},
        })
    return out


# ----------------------------------------------------------------------
# 조립
# ----------------------------------------------------------------------
# 합계 700 (가용량 실측 기반; boolean 템플릿은 YES/NO 쌍 보존 위해 짝수)
# v2.2: 얕은 조회형 136문항을 계산 추론 축(calc_*·joint)으로 대체
PRODUCT_QUOTA = [
    (gen_base_rate, 20), (gen_max_rate, 30), (gen_rate_threshold, 84),
    (gen_join_way, 40), (gen_age_condition, 32), (gen_max_limit, 30),
    (gen_interest_type, 20), (gen_loan_rate, 60), (gen_loan_rate_type, 60),
    (gen_credit_rate, 28), (gen_abstain, 60),
    (gen_compare_two, 40), (gen_agg_count, 36), (gen_agg_superlative, 1),
    (gen_enumerate, 23),
    (gen_calc_interest, 37), (gen_calc_after_tax, 37), (gen_calc_diff, 30),
    (gen_joint_condition, 32),
]
PRODUCT_OVERFLOW = ["rate_threshold", "join_way", "loan_rate_type"]

REGULATION_QUOTA = [
    (gen_article_locate, 131), (gen_definitions, 55), (gen_law_meta, 14),
    (gen_penalties, 40), (None, 60),  # None = temporal import
]
REGULATION_OVERFLOW = ["article_locate", "definition_term"]


def take_balanced(items: list[dict], quota: int) -> tuple[list, list]:
    """boolean 템플릿은 YES/NO 쌍 순서를 보존한 채 앞에서부터 quota만큼."""
    return items[:quota], items[quota:]


def assemble() -> list[dict]:
    products = load_products()
    laws = load_laws()

    picked, leftovers = [], {}
    for gen, quota in PRODUCT_QUOTA:
        items = gen(products)
        chosen, rest = take_balanced(items, quota)
        picked.extend(chosen)
        leftovers[items[0]["template"] if items else gen.__name__] = rest
    _fill(picked, leftovers, PRODUCT_OVERFLOW, 700, "공시형")
    for row in picked:
        row["qtype"] = "공시형"

    reg = []
    reg_leftovers = {}
    for gen, quota in REGULATION_QUOTA:
        items = import_temporal(THESIS_QUESTIONS) if gen is None else gen(laws)
        chosen, rest = take_balanced(items, quota)
        reg.extend(chosen)
        reg_leftovers[items[0]["template"] if items else "?"] = rest
    _fill(reg, reg_leftovers, REGULATION_OVERFLOW, 300, "규정형")
    for row in reg:
        row["qtype"] = "규정형"

    rows = picked + reg
    seen = set()
    unique = []
    for row in rows:
        if row["question"] in seen:
            continue
        seen.add(row["question"])
        unique.append(row)
    if len(unique) != len(rows):
        raise SystemExit(f"질문 중복 {len(rows) - len(unique)}건 — 템플릿 점검 필요")

    for i, row in enumerate(unique, 1):
        prefix = "PRD" if row["qtype"] == "공시형" else "REG"
        row["id"] = f"{prefix}-{i:04d}"
    # unit은 스키마 일관성을 위해 항상 존재 (HF pyarrow 타입 추론 안정화)
    ordered_keys = ["id", "qtype", "category", "subcategory", "template",
                    "question", "answer_type", "answer", "unit", "evidence"]
    return [{k: row.get(k, "") if k == "unit" else row[k]
             for k in ordered_keys} for row in unique]


def _fill(picked: list, leftovers: dict, overflow_order: list[str],
          target: int, label_txt: str):
    for template in overflow_order:
        while len(picked) < target and leftovers.get(template):
            # boolean 균형 유지를 위해 쌍(YES/NO 연속 2개) 단위로 추가
            pair = leftovers[template][:2]
            del leftovers[template][:2]
            picked.extend(pair)
    del picked[target:]
    if len(picked) < target:
        raise SystemExit(f"{label_txt} 문항 부족: {len(picked)}/{target}")


def main() -> int:
    rows = assemble()
    with OUTPUT.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    from collections import Counter
    print(f"총 {len(rows)}문항 → {OUTPUT.relative_to(REPO_ROOT)}")
    for key in ("qtype", "category", "answer_type"):
        print(f"  {key}: {dict(Counter(r[key] for r in rows).most_common())}")
    booleans = [r for r in rows if r["answer_type"] == "boolean"]
    yes = sum(1 for r in booleans if r["answer"] == "YES")
    print(f"  boolean 균형: YES {yes} / NO {len(booleans) - yes}")
    print(f"  템플릿: {dict(Counter(r['template'] for r in rows).most_common())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
