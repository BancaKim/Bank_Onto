"""규칙 계층 — 은행권 공통 규칙 추출 + 3값 논리 판단 패킷 엔진.

설계 계약 (두 선행 작업의 이식):
- research_paper/knowledge_layer/rule_engine.py: "엔진이 판단하고 LLM은 설명만
  한다." 이 파일에는 LLM 호출이 없다. 판단은 결정적이며, 3값 논리(참·거짓·미상)
  를 따른다 — 사실이 없으면 거짓이 아니라 **미상**이고, 미상이면 보류가 정답이다.
- SEOCHO(github.com/TTEON/seocho)의 계약 개념: 온톨로지가 에이전트의 작동 계약
  이다. 판단 패킷은 근거 좌표를 항상 동반하고(supported answer 불변식), 에이전트
  는 패킷 결론을 뒤집을 수 없다 (knowledge/tools.py의 도구 계약 참조).

규칙 출처: 적재된 지식층(금감원 공시 필드)에서 정규식으로 결정적으로 추출한다.
- 연령 요건: joinMember의 "만 N세 이상"
- 가입 경로: joinWay 채널 목록
- 최소 가입금액: etcNote의 금액 요건
- 우대금리 상한: 금리옵션의 maxPreferentialRateValue

인식 상태 판정 순서 (rule_engine.py와 동일, 먼저 걸리는 것이 이긴다):
  1. 상품/규칙 없음        → NOT_APPLICABLE
  2. 조건 위반 확정        → DENIED
  3. 사실 부족             → UNKNOWN (부족 슬롯 명시)
  4. 전 조건 충족          → CONFIRMED
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rdflib import URIRef

from knowledge.kb import BankKnowledgeBase, PREFIXES

MARKET = PREFIXES["market"]
PRODUCTS = PREFIXES["products"]
PARTIES = PREFIXES["parties"]

CHANNELS = ["영업점", "인터넷", "스마트폰", "전화(텔레뱅킹)"]

_AMOUNT_UNIT = {"": 1, "만": 10**4, "십만": 10**5, "백만": 10**6,
                "천만": 10**7, "억": 10**8}
_MIN_AMOUNT_RE = re.compile(
    r"(?:최소\s?가입\s?금액|최저)[^\d]{0,8}([\d,]+)\s?(만|십만|백만|천만|억)?\s?원\s?이상")
_AGE_RE = re.compile(r"만\s?(\d{1,3})세\s?이상")


@dataclass
class Condition:
    """단일 요건. evaluate()는 True/False/None(미상)을 반환한다."""
    attr: str            # age | channel | amount
    op: str              # ">=" | "in"
    value: object
    source_field: str
    source_text: str

    def evaluate(self, facts: dict):
        if self.attr not in facts or facts[self.attr] is None:
            return None  # 사실 없음 → 미상
        got = facts[self.attr]
        if self.op == ">=":
            return float(got) >= float(self.value)
        if self.op == "in":
            return str(got) in self.value
        return None

    def to_dict(self, result) -> dict:
        return {"attr": self.attr, "op": self.op, "value": self.value,
                "result": {True: "충족", False: "위반", None: "미상"}[result],
                "source": f"{self.source_field}: {self.source_text[:120]}"}


@dataclass
class ProductRules:
    bank: str
    name: str
    conditions: list[Condition] = field(default_factory=list)
    max_rates: dict[int, float] = field(default_factory=dict)  # 만기→최고우대금리
    locator: str = ""


class RuleBook:
    """지식층에서 추출한 상품별 규칙 사전 + 판단 패킷 엔진."""

    def __init__(self, rules: dict[tuple[str, str], ProductRules]):
        self._rules = rules

    # ------------------------------------------------------------------
    # 추출 (결정적 — LLM 불개입)
    # ------------------------------------------------------------------
    @classmethod
    def from_kb(cls, kb: BankKnowledgeBase) -> "RuleBook":
        rows = kb.run_sparql("""
            SELECT ?name ?bankName ?joinMember ?joinWay ?etcNote WHERE {
                ?p products:hasProductName ?name ;
                   market:disclosureMonth ?m ;
                   products:isOfferedBy ?b .
                ?b parties:hasName ?bankName .
                OPTIONAL { ?p market:joinMember ?joinMember }
                OPTIONAL { ?p market:joinWay ?joinWay }
                OPTIONAL { ?p market:etcNote ?etcNote }
            }""", limit=100_000)
        rules: dict[tuple[str, str], ProductRules] = {}
        for row in rows:
            bank, name = str(row["bankName"]), str(row["name"])
            pr = ProductRules(bank=bank, name=name, locator=f"{bank}:{name}")
            join_member = str(row.get("joinMember") or "")
            join_way = str(row.get("joinWay") or "")
            etc_note = str(row.get("etcNote") or "")

            if m := _AGE_RE.search(join_member):
                pr.conditions.append(Condition(
                    "age", ">=", int(m.group(1)), "가입대상(joinMember)",
                    join_member))
            if join_way:
                ways = [w.strip() for w in join_way.split(",") if w.strip()]
                channels = [c for c in CHANNELS if c in ways]
                if channels:
                    pr.conditions.append(Condition(
                        "channel", "in", channels, "가입방법(joinWay)", join_way))
            if m := _MIN_AMOUNT_RE.search(etc_note):
                amount = int(m.group(1).replace(",", "")) * \
                    _AMOUNT_UNIT[m.group(2) or ""]
                pr.conditions.append(Condition(
                    "amount", ">=", amount, "기타유의사항(etcNote)", etc_note))
            rules[(bank, name)] = pr

        # 우대금리 상한 (만기별)
        for row in kb.run_sparql("""
            SELECT ?name ?bankName ?term ?rate WHERE {
                ?p products:hasProductName ?name ;
                   products:isOfferedBy ?b ;
                   market:hasRateOption ?o .
                ?b parties:hasName ?bankName .
                ?o market:termMonths ?term ; market:maxPreferentialRateValue ?rate .
            }""", limit=100_000):
            key = (str(row["bankName"]), str(row["name"]))
            if key in rules:
                term, rate = int(row["term"]), float(row["rate"])
                current = rules[key].max_rates.get(term)
                rules[key].max_rates[term] = max(current, rate) \
                    if current is not None else rate
        return cls(rules)

    # ------------------------------------------------------------------
    # 판단 (3값 논리)
    # ------------------------------------------------------------------
    def _resolve(self, bank: str, product: str) -> ProductRules | None:
        if (bank, product) in self._rules:
            return self._rules[(bank, product)]
        # 은행명 부분 일치 허용 ("국민은행" vs "주식회사 국민은행")
        candidates = [pr for (b, n), pr in sorted(self._rules.items())
                      if n == product and (bank in b or b in bank)]
        return candidates[0] if len(candidates) == 1 else None

    def evaluate(self, bank: str, product: str, facts: dict) -> dict:
        """가입 요건 판단 패킷. facts 예: {"age": 20, "channel": "스마트폰",
        "amount": 500000}. 제공된 사실만 평가하며, 없는 사실은 미상 처리한다."""
        pr = self._resolve(bank, product)
        if pr is None or not pr.conditions:
            return self._packet("NOT_APPLICABLE", pr, [],
                                note="적용할 규칙이 없거나 상품을 찾지 못함")
        results = [(c, c.evaluate(facts)) for c in pr.conditions]
        # 질문과 무관한 슬롯(사실도 없고 물은 적도 없는 조건)은 미상으로 남기되,
        # 하나라도 '위반'이면 사실 부족과 무관하게 DENIED가 확정된다.
        if any(r is False for _, r in results):
            return self._packet("DENIED", pr, results)
        missing = [c.attr for c, r in results if r is None and c.attr in facts]
        unknown = [c.attr for c, r in results if r is None]
        provided_all_pass = all(r is True for c, r in results
                                if c.attr in facts)
        if provided_all_pass and facts and not missing:
            # 제공된 사실은 전부 충족 — 묻지 않은 조건이 남았으면 그 목록을 명시
            if unknown:
                return self._packet("CONFIRMED", pr, results,
                                    note=f"미확인 요건 있음: {unknown} — 해당 "
                                         f"사실이 주어지면 재판정 필요")
            return self._packet("CONFIRMED", pr, results)
        return self._packet("UNKNOWN", pr, results, missing_slots=unknown)

    def check_rate_claim(self, bank: str, product: str, claimed: float,
                         months: int = 12) -> dict:
        """'만기 M개월 최고 우대금리가 claimed% 이상인가'를 판정한다."""
        pr = self._resolve(bank, product)
        if pr is None:
            return self._packet("NOT_APPLICABLE", None, [],
                                note="상품을 찾지 못함")
        rate = pr.max_rates.get(months)
        if rate is None:
            return self._packet("UNKNOWN", pr, [], missing_slots=["max_rate"],
                                note=f"{months}개월 만기 금리옵션이 공시에 없음")
        verdict = "CONFIRMED" if rate >= claimed else "DENIED"
        packet = self._packet(verdict, pr, [])
        packet["evidence"].append(
            {"source": pr.locator,
             "fact": f"{months}개월 최고 우대금리 = 연 {rate:g}% "
                     f"(질의 기준 {claimed:g}%)"})
        return packet

    @staticmethod
    def _packet(verdict: str, pr: ProductRules | None, results,
                missing_slots: list[str] | None = None, note: str = "") -> dict:
        packet = {
            "verdict": verdict,
            "product": pr.locator if pr else None,
            "conditions": [c.to_dict(r) for c, r in results],
            "missing_slots": missing_slots or [],
            "evidence": [{"source": pr.locator, "fact": c.to_dict(r)["source"]}
                         for c, r in results] if pr else [],
            "contract": ("이 패킷의 결론은 결정적 규칙 평가 결과다. 답변은 "
                         "결론을 뒤집을 수 없으며, UNKNOWN이면 단정 대신 "
                         "부족한 정보를 요청해야 한다."),
        }
        if note:
            packet["note"] = note
        return packet
