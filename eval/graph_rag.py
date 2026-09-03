"""온톨로지(그래프) RAG 리트리버.

질문에서 온톨로지 개념을 매칭한 뒤 그래프를 구조적으로 탐색하여
컨텍스트를 구성한다:
- 클래스 → 정의 + 계층(하위 분류) + 관련 속성
- 속성 → 정의 + 실제 사용 트리플 (집계·필터 질의 대응)
- 인스턴스 → 다중 홉 이웃 탐색(BFS)으로 연결된 개체의 사실 수집

LLM 없이 결정적으로 동작하므로 재현 가능한 평가가 가능하다.
(실제 에이전트는 LLM이 도구를 선택하므로 이보다 더 정확하다 — 이 리트리버는
 그래프 접근의 '하한'을 보여준다.)
"""
from __future__ import annotations

from rdflib import Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from eval.corpus import label_of
from knowledge.kb import BANK_ONTO_NS, PREFIXES, BankKnowledgeBase

PARTIES_NAME = URIRef(PREFIXES["parties"] + "hasName")
PRODUCT_NAME = URIRef(PREFIXES["products"] + "hasProductName")


def _lcs_len(a: str, b: str) -> int:
    """최장 공통 연속 부분 문자열 길이."""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        curr = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
                best = max(best, curr[j])
        prev = curr
    return best


class GraphRetriever:
    def __init__(self, kb: BankKnowledgeBase):
        self.kb = kb
        self.graph = kb.graph
        # 이름 색인: rdfs:label + 고유명(hasName, hasProductName)
        # 레이블의 괄호 안 약어("담보인정비율(LTV)" → "LTV")도 별도 항목으로 등록한다.
        self._names: list[tuple[str, URIRef]] = []
        for pred in (RDFS.label, PARTIES_NAME, PRODUCT_NAME):
            for subj, name in self.graph.subject_objects(pred):
                if not (isinstance(subj, URIRef) and str(subj).startswith(BANK_ONTO_NS)):
                    continue
                text = str(name)
                self._names.append((text, subj))
                if "(" in text and text.endswith(")"):
                    base, _, alias = text.rstrip(")").partition("(")
                    if len(base.strip()) >= 2:
                        self._names.append((base.strip(), subj))
                    if len(alias.strip()) >= 2:
                        self._names.append((alias.strip(), subj))
        # rdflib 그래프 순회 순서는 프로세스마다 달라질 수 있으므로 정렬해
        # 리트리버 전체를 결정적으로 만든다 (재현 가능한 평가 보장).
        self._names.sort(key=lambda item: (item[0], str(item[1])))

    # ------------------------------------------------------------------
    # 매칭
    # ------------------------------------------------------------------
    def match_concepts(self, question: str, limit: int = 8) -> list[URIRef]:
        q = question.lower()
        # 정확 동치 사전필터: 이름 길이<4의 매칭 조건(lcs>=len)은 '이름이 질문의
        # 부분문자열'과 동치이고, 길이>=4의 조건(lcs>=4)은 '공통 4-gram 존재'와
        # 동치다. 4-gram 집합 교차 검사로 LCS 계산 대상을 크게 줄인다 (결과 불변).
        q_grams = {q[i:i + 4] for i in range(len(q) - 3)}
        # (정규화 점수, 매칭 절대 길이): 점수가 같으면 더 길게 매칭된 이름이
        # 우선한다 — "제40조(벌칙)" 전체 매칭이 별칭 "벌칙"보다 특이도가 높다.
        best: dict[URIRef, tuple[float, int]] = {}
        for name, node in self._names:
            n = name.lower()
            if len(n) < 4:
                if n not in q:
                    continue
                score, lcs = 1.0, len(n)
            else:
                if not any(n[i:i + 4] in q_grams for i in range(len(n) - 3)):
                    continue
                lcs = _lcs_len(n, q)
                score = lcs / len(n)
            if (score, lcs) > best.get(node, (0.0, 0)):
                best[node] = (score, lcs)
        ranked = sorted(best.items(),
                        key=lambda kv: (-kv[1][0], -kv[1][1], str(kv[0])))
        return [node for node, _ in ranked[:limit]]

    # ------------------------------------------------------------------
    # 노드 분류
    # ------------------------------------------------------------------
    def _kind(self, node: URIRef) -> str:
        types = set(self.graph.objects(node, RDF.type))
        if OWL.Class in types:
            return "class"
        if OWL.ObjectProperty in types or OWL.DatatypeProperty in types:
            return "property"
        return "individual"

    def _is_individual(self, node) -> bool:
        return (
            isinstance(node, URIRef)
            and str(node).startswith(BANK_ONTO_NS)
            and self._kind(node) == "individual"
        )

    # ------------------------------------------------------------------
    # 렌더링
    # ------------------------------------------------------------------
    def _render_class(self, cls: URIRef) -> str:
        detail = self.kb.get_concept(str(cls))
        lines = [f"[개념] {label_of(self.kb, cls)} ({self.kb._qname(cls)})"]
        if detail.definition:
            lines.append(f"정의: {detail.definition}")
        tree = self.kb.get_hierarchy(str(cls), depth=2)

        def walk(entry: dict, indent: int):
            for child in entry.get("subclasses", []):
                ko = [lbl for lbl in child["labels"] if not lbl.isascii()]
                lines.append("  " * indent + f"- 하위: {(ko or child['labels'] or [child['uri']])[0]} ({child['uri']})")
                walk(child, indent + 1)

        walk(tree, 1)
        for sup in detail.superclasses:
            lines.append(f"상위 개념: {sup}")
        for prop in detail.properties[:12]:
            ko = [lbl for lbl in prop["labels"] if not lbl.isascii()]
            lines.append(f"관련 속성: {(ko or prop['labels'] or [prop['property']])[0]} "
                         f"({prop['property']}, 범위: {', '.join(prop['range']) or '-'})")
        # 열거형(named individual)으로 정의된 하위 항목 (상환방식, 계좌상태, 채널 등)
        for inst in sorted(self.graph.subjects(RDF.type, cls), key=str)[:15]:
            if isinstance(inst, URIRef):
                lines.append(f"항목: {label_of(self.kb, inst)} ({self.kb._qname(inst)})")
        return "\n".join(lines)

    def _render_property(self, prop: URIRef) -> str:
        lines = [f"[속성] {label_of(self.kb, prop)} ({self.kb._qname(prop)})"]
        definition = self.kb._definition(prop)
        if definition:
            lines.append(f"정의: {definition}")
        usages = sorted(self.graph.subject_objects(prop), key=lambda so: (str(so[0]), str(so[1])))[:15]
        for subj, obj in usages:
            subj_txt = label_of(self.kb, subj) if isinstance(subj, URIRef) else str(subj)
            obj_txt = str(obj) if isinstance(obj, Literal) else label_of(self.kb, obj)
            lines.append(f"- {subj_txt} ({self.kb._qname(subj)}) → {obj_txt}")
        return "\n".join(lines)

    def _render_individual(self, ind: URIRef) -> str:
        lines = [f"[개체] {label_of(self.kb, ind)} ({self.kb._qname(ind)})"]
        for pred, obj in sorted(self.graph.predicate_objects(ind),
                                key=lambda po: (str(po[0]), str(po[1]))):
            if pred == RDFS.label:
                continue
            value = str(obj) if isinstance(obj, Literal) else \
                f"{label_of(self.kb, obj)} ({self.kb._qname(obj)})"
            lines.append(f"- {label_of(self.kb, pred)}: {value}")
        for subj, pred in sorted(self.graph.subject_predicates(ind),
                                 key=lambda sp: (str(sp[0]), str(sp[1]))):
            if isinstance(subj, URIRef) and str(subj).startswith(BANK_ONTO_NS):
                lines.append(
                    f"- (역참조) {label_of(self.kb, subj)} ({self.kb._qname(subj)}) "
                    f"이(가) [{label_of(self.kb, pred)}] 관계로 이 개체를 참조"
                )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # BFS 이웃 탐색 (다중 홉)
    # ------------------------------------------------------------------
    def _expand_individuals(self, seeds: list[URIRef], depth: int = 4,
                            cap: int = 25) -> list[URIRef]:
        """시드별 독립 BFS. 예산(cap)을 시드마다 따로 주어, 이웃이 많은
        허브(예: 시장 데이터의 은행 노드)에 연결된 시드가 다른 시드의
        탐사 예산을 잠식하지 않게 한다."""
        merged: list[URIRef] = []
        for seed in seeds:
            visited = [seed]
            frontier = [seed]
            for _ in range(depth):
                next_frontier = []
                for node in frontier:
                    neighbors = [
                        obj for _, obj in self.graph.predicate_objects(node)
                        if self._is_individual(obj)
                    ] + [
                        subj for subj, _ in self.graph.subject_predicates(node)
                        if self._is_individual(subj)
                    ]
                    for nb in sorted(neighbors, key=str):
                        if nb not in visited and len(visited) < cap:
                            visited.append(nb)
                            next_frontier.append(nb)
                frontier = next_frontier
                if not frontier or len(visited) >= cap:
                    break
            for node in visited:
                if node not in merged:
                    merged.append(node)
        return merged

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------
    def retrieve_units(self, question: str) -> list[str]:
        """랭킹된 컨텍스트 유닛(섹션) 목록. 매칭 개념 → 클래스/속성 렌더링 →
        BFS 이웃 개체 순. 시나리오 평가(Hit@k·MRR·예산 컷)에 쓰인다."""
        matched = self.match_concepts(question)
        if not matched:
            return []  # 매칭 개념 없음 → 정직하게 빈 컨텍스트 (환각 방지)

        sections = ["[매칭된 개념] " + ", ".join(
            f"{label_of(self.kb, n)}({self.kb._qname(n)})" for n in matched)]

        individuals = [n for n in matched if self._kind(n) == "individual"]
        for node in matched:
            kind = self._kind(node)
            if kind == "class":
                sections.append(self._render_class(node))
            elif kind == "property":
                sections.append(self._render_property(node))

        if individuals:
            for ind in self._expand_individuals(individuals):
                sections.append(self._render_individual(ind))
        return sections

    def retrieve_context(self, question: str) -> str:
        return "\n\n".join(self.retrieve_units(question))
