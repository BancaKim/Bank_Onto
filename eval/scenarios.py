"""RAG 시나리오 매트릭스 — Chen et al. (2026) "Is GraphRAG Needed?"의 9-시나리오
구도를 Bank_Onto 지식층에 이식한 것.

모든 시나리오는 같은 인터페이스를 갖는다:
    retrieve(question) -> 랭킹된 컨텍스트 유닛(str) 목록
유닛 목록은 (1) Hit@k·MRR 계산과 (2) 컨텍스트 예산 컷(assemble)에 쓰인다.
세 지식 표현(텍스트 청크 / 속성 그래프 / 온톨로지)이 모두 같은 KB에서 파생된다.

결정적(LLM 불개입) 시나리오 9종:
  S1 basic-chunk     고정 청크(400자) + TF-IDF top-k              — 논문의 Basic RAG
  S2 entity-doc      개체당 문서 1개 + TF-IDF                      — entity description docs
  S3 relation-doc    트리플당 문장 1개 + TF-IDF                    — relations documents
  S4 entity+relation 위 두 코퍼스 결합 색인                         — 논문 최고 기본 변형
  S5 hybrid          벡터로 시드 개체 검색 → LPG k-hop 확장         — hybrid text-graph
  S6 lpg             이름 매칭 시드 → LPG k-hop (사전정의 도메인 KG) — GraphRAG(pre-defined KG)
  S7 onto            온톨로지 리트리버(계층·속성·BFS)               — ontology RAG
  S8 lpg+ce          S6 + 컨텍스트 엔지니어링(질문 관련도 재정렬·압축)
  S9 onto+ce         S7 + 컨텍스트 엔지니어링
에이전틱 시나리오(A1 기본 도구 에이전트, A2 온톨로지 에이전트)는 LLM이 필요하므로
run_scenario_answer_eval.py에 있다. LLM이 추출한 '계산된 KG'(computed KG)는
API 없이는 구축할 수 없어 포함하지 않았다.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from eval.corpus import (build_entity_documents, build_relation_documents,
                         chunk_corpus)
from eval.graph_rag import GraphRetriever
from eval.lpg_rag import LpgGraphRetriever
from eval.vector_rag import TfidfVectorRetriever, char_ngrams
from knowledge.kb import BankKnowledgeBase

DEFAULT_BUDGET = 4000   # 문자 — KR-FinReg-QA의 컨텍스트 상한 관행
BUDGETS = (2000, 4000, 8000)


# ----------------------------------------------------------------------
# 컨텍스트 조립 / 컨텍스트 엔지니어링
# ----------------------------------------------------------------------
def assemble(units: list[str], budget: int | None) -> str:
    """랭킹 순서대로 예산(문자) 안에 들어가는 유닛만 이어 붙인다.
    첫 유닛이 예산보다 크면 잘라서라도 넣는다 (빈 컨텍스트보다 낫다)."""
    if budget is None:
        return "\n\n".join(units)
    out, used = [], 0
    for unit in units:
        length = len(unit) + (2 if out else 0)
        if used + length > budget:
            if not out:
                out.append(unit[:budget])
            break
        out.append(unit)
        used += length
    return "\n\n".join(out)


# 이름 뒤에 붙은 URI 참조 "(mktd:prdt_...)"만 제거한다. 줄 첫머리의 괄호
# (LPG 노드 헤더 "(mktd:…:RateOption)")는 개체 식별 정보이므로 보존한다.
_QNAME_RE = re.compile(r"(?<=\S)\s?\((?:[a-z]+:)[^\s()]+\)")
_REVERSE_REF_RE = re.compile(r"^- \(역참조\).*$", re.MULTILINE)


def compact(unit: str) -> str:
    """토큰 절약 압축: URI qname 참조 제거, 역참조 행 제거, 공백 정리.
    사실 값(수치·이름·본문)은 건드리지 않는다."""
    text = _QNAME_RE.sub("", unit)
    text = _REVERSE_REF_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _cosine(a: dict, b: dict) -> float:
    dot = sum(w * b[g] for g, w in a.items() if g in b)
    na = math.sqrt(sum(w * w for w in a.values())) or 1.0
    nb = math.sqrt(sum(w * w for w in b.values())) or 1.0
    return dot / (na * nb)


def _unit_priority(unit: str) -> int:
    """구조 인지 우선순위: 개체 사실(0) > 속성 사용처(1) > 클래스 계층(2).
    질문 답에 직접 쓰이는 것은 개체의 값이고, 클래스 계층은 분류 질문에만 필요하다."""
    if unit.startswith("[개념]"):
        return 2
    if unit.startswith("[속성]"):
        return 1
    return 0


def context_engineer(units: list[str], question: str) -> list[str]:
    """논문의 컨텍스트 엔지니어링을 결정적으로 재현한다 (gold 비의존):
    (1) 압축 — URI 참조·역참조 행 제거,
    (2) 구조 인지 재정렬 — 개체 사실 → 속성 사용처 → 클래스 계층 순.
        같은 우선순위 안에서는 리트리버의 탐색 거리 순서(시드 → 이웃)를
        그대로 보존한다 — 거리가 곧 관련도 근사이며, 어휘 재정렬은 실험에서
        오히려 해가 됐다(같은 은행의 다른 상품이 금리옵션보다 앞으로 밀림),
    (3) 중복 제거.
    '[매칭된 개념]' 헤더는 첫 자리를 지킨다. 정보는 버리지 않고 예산 효율만 바꾼다.
    question 인자는 인터페이스 호환용(현재 미사용)."""
    if not units:
        return []
    head, rest = ([units[0]], units[1:]) if units[0].startswith("[매칭된 개념]") else ([], units)
    ordered = sorted(((_unit_priority(u), i, u) for i, u in enumerate(rest)),
                     key=lambda t: (t[0], t[1]))
    out, seen = [compact(h) for h in head], set()
    for _, _, unit in ordered:
        c = compact(unit)
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


# ----------------------------------------------------------------------
# 시나리오
# ----------------------------------------------------------------------
@dataclass
class Scenario:
    id: str
    name: str
    family: str          # basic | hybrid | graph | ontology
    description: str
    _fn: object = field(repr=False)

    def retrieve(self, question: str) -> list[str]:
        return self._fn(question)


class ScenarioSuite:
    """KB 하나에서 9개 시나리오를 구성한다 (색인은 한 번만 만든다)."""

    def __init__(self, kb: BankKnowledgeBase, k_basic: int = 20):
        self.kb = kb
        entity_pairs = build_entity_documents(kb)
        self._entity_keys = [key for key, _ in entity_pairs]
        entity_docs = [text for _, text in entity_pairs]
        relation_docs = build_relation_documents(kb)
        chunks = chunk_corpus(entity_docs)

        self.idx_chunk = TfidfVectorRetriever(chunks)
        self.idx_entity = TfidfVectorRetriever(entity_docs)
        self.idx_relation = TfidfVectorRetriever(relation_docs)
        self.idx_combined = TfidfVectorRetriever(entity_docs + relation_docs)
        self.lpg = LpgGraphRetriever(kb)
        self.onto = GraphRetriever(kb)
        self._entity_index_by_text = {text: key for key, text in entity_pairs}
        self.sizes = {
            "chunks": len(chunks), "entity_docs": len(entity_docs),
            "relation_docs": len(relation_docs),
            "lpg_nodes": len(self.lpg.nodes), "lpg_edges": len(self.lpg.edges),
            "triples": len(kb.graph),
        }
        k = k_basic

        def hybrid(question: str) -> list[str]:
            hits = self.idx_entity.retrieve(question, k=3)
            seeds = [self._entity_index_by_text[h] for h in hits
                     if self._entity_index_by_text.get(h) in self.lpg.nodes]
            return self.lpg.expand_units(seeds)

        self.scenarios: list[Scenario] = [
            Scenario("S1", "basic-chunk", "basic",
                     "고정 400자 청크(80자 중첩) + TF-IDF top-k",
                     lambda q: self.idx_chunk.retrieve(q, k=k)),
            Scenario("S2", "entity-doc", "basic",
                     "개체당 문서 1개 + TF-IDF top-k",
                     lambda q: self.idx_entity.retrieve(q, k=k)),
            Scenario("S3", "relation-doc", "basic",
                     "트리플당 문장 1개(관계 문서) + TF-IDF top-k",
                     lambda q: self.idx_relation.retrieve(q, k=2 * k)),
            Scenario("S4", "entity+relation", "basic",
                     "개체 문서 + 관계 문서 결합 색인 + TF-IDF top-k",
                     lambda q: self.idx_combined.retrieve(q, k=int(1.5 * k))),
            Scenario("S5", "hybrid", "hybrid",
                     "벡터 검색으로 시드 개체 3개 → LPG k-hop 확장",
                     hybrid),
            Scenario("S6", "lpg", "graph",
                     "이름 매칭 시드 → LPG k-hop (사전정의 도메인 KG)",
                     self.lpg.retrieve_units),
            Scenario("S7", "onto", "ontology",
                     "온톨로지 리트리버: 개념 매칭 → 계층·속성·BFS",
                     self.onto.retrieve_units),
            Scenario("S8", "lpg+ce", "graph",
                     "S6 + 컨텍스트 엔지니어링(압축·관련도 재정렬)",
                     lambda q: context_engineer(self.lpg.retrieve_units(q), q)),
            Scenario("S9", "onto+ce", "ontology",
                     "S7 + 컨텍스트 엔지니어링(압축·관련도 재정렬)",
                     lambda q: context_engineer(self.onto.retrieve_units(q), q)),
        ]

    def by_id(self, sid: str) -> Scenario:
        return next(s for s in self.scenarios if s.id == sid)


# ----------------------------------------------------------------------
# 검색 지표
# ----------------------------------------------------------------------
def retrieval_metrics(units: list[str], gold: list[str]) -> dict:
    """Hit@1: 첫 유닛에 근거 전부 포함. MRR: 근거가 전부 갖춰지는 최소 랭크 r의
    1/r (누적 합집합 기준 — 다중 문서 근거에 맞춘 정의). recall@B: 예산 B로
    조립한 컨텍스트의 근거 재현율."""
    total = len(gold) or 1
    complete_rank = 0
    seen = set()
    for r, unit in enumerate(units, 1):
        for g in gold:
            if g in unit:
                seen.add(g)
        if len(seen) == len(gold):
            complete_rank = r
            break
    out = {
        "hit1": 1.0 if units and all(g in units[0] for g in gold) else 0.0,
        "mrr": 1.0 / complete_rank if complete_rank else 0.0,
        "chars": len(assemble(units, None)),
    }
    for budget in BUDGETS:
        ctx = assemble(units, budget)
        out[f"recall@{budget}"] = sum(1 for g in gold if g in ctx) / total
    ctx_full = assemble(units, None)
    out["recall@inf"] = sum(1 for g in gold if g in ctx_full) / total
    return out
