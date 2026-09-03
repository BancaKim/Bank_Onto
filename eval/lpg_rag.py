"""Graph RAG (LPG) 베이스라인 리트리버.

온톨로지를 LPG(Labeled Property Graph, Neo4j식 속성 그래프)로 변환한 뒤,
전형적인 KG-RAG 방식(LlamaIndex KG retriever, Neo4j 이웃 탐색)대로
질문의 개체를 시드로 k-hop 이웃 서브그래프를 컨텍스트로 반환한다.

LPG 변환 규칙 (일반적인 Neo4j 모델링 관행):
- 인스턴스 → 노드 (레이블 = 클래스 로컬명, 데이터 속성 = 노드 프로퍼티)
- 객체 속성 트리플 → 타입 있는 엣지
- 클래스 → 분류 노드 (정의 프로퍼티 포함), SUBCLASS_OF / INSTANCE_OF 엣지
  (분류 체계를 노드로 함께 적재하는 관대한 변환 — LPG에 유리하게 설정)

온톨로지 RAG와의 차이: 속성 스키마(domain/range) 없음, SPARQL 집계 없음,
서브클래스 추론 없음 — 엣지를 물리적으로 따라가는 것이 전부다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rdflib import Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from eval.corpus import label_of
from eval.graph_rag import _lcs_len
from knowledge.kb import BANK_ONTO_NS, BankKnowledgeBase


@dataclass
class LpgNode:
    key: str
    name: str
    labels: list[str] = field(default_factory=list)   # 노드 레이블 (클래스명)
    props: dict = field(default_factory=dict)          # 데이터 속성
    definition: str | None = None                      # 분류 노드용


class LpgGraphRetriever:
    def __init__(self, kb: BankKnowledgeBase, hops: int = 4, node_cap: int = 30):
        self.kb = kb
        self.hops = hops
        self.node_cap = node_cap
        self.nodes: dict[str, LpgNode] = {}
        self.edges: list[tuple[str, str, str]] = []    # (src, TYPE, dst)
        self._adj: dict[str, list[tuple[str, str, str]]] = {}
        self._build(kb)
        # 이름 색인 — 온톨로지 RAG와 동일하게 괄호 약어도 별도 등록 (공정 비교)
        self._name_index = []
        for n in self.nodes.values():
            if not n.name:
                continue
            self._name_index.append((n.name, n.key))
            if "(" in n.name and n.name.endswith(")"):
                base, _, alias = n.name.rstrip(")").partition("(")
                if len(base.strip()) >= 2:
                    self._name_index.append((base.strip(), n.key))
                if len(alias.strip()) >= 2:
                    self._name_index.append((alias.strip(), n.key))
        # 결정적 평가를 위해 정렬 (rdflib/dict 순회 순서 의존 제거)
        self._name_index.sort()

    # ------------------------------------------------------------------
    # RDF → LPG 변환
    # ------------------------------------------------------------------
    def _build(self, kb: BankKnowledgeBase) -> None:
        graph = kb.graph
        classes = {
            c for c in graph.subjects(RDF.type, OWL.Class)
            if isinstance(c, URIRef) and str(c).startswith(BANK_ONTO_NS)
        }
        properties = set(graph.subjects(RDF.type, OWL.ObjectProperty)) | \
            set(graph.subjects(RDF.type, OWL.DatatypeProperty))

        def key(node: URIRef) -> str:
            return kb._qname(node)

        # 분류 노드 (정렬 순회 — 결정적 변환 보장)
        for cls in sorted(classes, key=str):
            self.nodes[key(cls)] = LpgNode(
                key=key(cls), name=label_of(kb, cls), labels=["Category"],
                definition=kb._definition(cls),
            )
        for cls in sorted(classes, key=str):
            for sup in sorted(graph.objects(cls, RDFS.subClassOf), key=str):
                if isinstance(sup, URIRef) and sup in classes:
                    self.edges.append((key(cls), "SUBCLASS_OF", key(sup)))

        # 인스턴스 노드
        individuals = set()
        for subj in graph.subjects():
            if not (isinstance(subj, URIRef) and str(subj).startswith(BANK_ONTO_NS)):
                continue
            if subj in classes or subj in properties:
                continue
            if (subj, RDF.type, OWL.Ontology) in graph:
                continue
            individuals.add(subj)

        for ind in sorted(individuals, key=str):
            node = LpgNode(key=key(ind), name=label_of(kb, ind),
                           definition=kb._definition(ind))
            for pred, obj in sorted(graph.predicate_objects(ind),
                                    key=lambda po: (str(po[0]), str(po[1]))):
                pname = label_of(kb, pred)
                if pred == RDF.type and isinstance(obj, URIRef) and obj in classes:
                    node.labels.append(str(obj).rsplit("/", 1)[-1])
                    self.edges.append((node.key, "INSTANCE_OF", key(obj)))
                elif isinstance(obj, Literal):
                    if pred not in (RDFS.label, SKOS.definition):
                        node.props[pname] = str(obj)
                elif isinstance(obj, URIRef) and obj in individuals:
                    self.edges.append((node.key, pname, key(obj)))
            self.nodes[node.key] = node

        # 인접 리스트 (양방향)
        for src, etype, dst in self.edges:
            self._adj.setdefault(src, []).append((src, etype, dst))
            self._adj.setdefault(dst, []).append((src, etype, dst))

    # ------------------------------------------------------------------
    # 시드 매칭 (graph_rag와 동일한 LCS 기준 — 공정 비교)
    # ------------------------------------------------------------------
    def _match_seeds(self, question: str, limit: int = 6) -> list[str]:
        q = question.lower()
        # graph_rag.match_concepts와 동일한 정확 동치 사전필터 (결과 불변)
        q_grams = {q[i:i + 4] for i in range(len(q) - 3)}
        # graph_rag와 동일: 동점이면 매칭 절대 길이가 긴(특이도 높은) 이름 우선
        best: dict[str, tuple[float, int]] = {}
        for name, node_key in self._name_index:
            n = name.lower()
            if len(n) < 2:
                continue
            if len(n) < 4:
                if n not in q:
                    continue
                score, lcs = 1.0, len(n)
            else:
                if not any(n[i:i + 4] in q_grams for i in range(len(n) - 3)):
                    continue
                lcs = _lcs_len(n, q)
                score = lcs / len(n)
            if (score, lcs) > best.get(node_key, (0.0, 0)):
                best[node_key] = (score, lcs)
        ranked = sorted(best.items(),
                        key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))
        return [k for k, _ in ranked[:limit]]

    # ------------------------------------------------------------------
    # k-hop 이웃 탐색
    # ------------------------------------------------------------------
    def match_seeds(self, question: str, limit: int = 6) -> list[str]:
        return self._match_seeds(question, limit=limit)

    def expand_units(self, seeds: list[str]) -> list[str]:
        """주어진 시드 노드 키에서 k-hop 탐색을 수행해 노드 단위 유닛 목록을
        반환한다 (방문 순서 = 랭킹). 마지막 유닛은 엣지 목록이다.
        하이브리드(벡터 시드 → 그래프 확장) 시나리오가 이 진입점을 쓴다."""
        if not seeds:
            return []
        # 시드별 독립 k-hop 탐색 — 온톨로지 리트리버와 동일한 예산 정책.
        # 허브 노드(은행 등)에 연결된 시드가 다른 시드의 예산을 잠식하지 않는다.
        visited: list[str] = []
        kept_edges: list[tuple[str, str, str]] = []
        for seed in seeds:
            seed_visited = [seed]
            frontier = [seed]
            for _ in range(self.hops):
                next_frontier = []
                for node_key in frontier:
                    for src, etype, dst in self._adj.get(node_key, []):
                        other = dst if src == node_key else src
                        if (src, etype, dst) not in kept_edges:
                            kept_edges.append((src, etype, dst))
                        if other not in seed_visited and len(seed_visited) < self.node_cap:
                            seed_visited.append(other)
                            next_frontier.append(other)
                frontier = next_frontier
                if not frontier or len(seed_visited) >= self.node_cap:
                    break
            for node_key in seed_visited:
                if node_key not in visited:
                    visited.append(node_key)

        units = []
        for node_key in visited:
            node = self.nodes.get(node_key)
            if node is None:
                continue
            label_txt = ":".join(node.labels) if node.labels else "Node"
            lines = [f"({node.name}:{label_txt})"]
            if node.definition:
                lines.append(f"  정의: {node.definition}")
            for prop_name, value in node.props.items():
                lines.append(f"  {prop_name}: {value}")
            units.append("\n".join(lines))
        visited_set = set(visited)
        edge_lines = []
        for src, etype, dst in kept_edges:
            if src in visited_set and dst in visited_set:
                src_name = self.nodes[src].name if src in self.nodes else src
                dst_name = self.nodes[dst].name if dst in self.nodes else dst
                edge_lines.append(f"({src_name}) -[{etype}]-> ({dst_name})")
        if edge_lines:
            units.append("\n".join(edge_lines))
        return units

    def retrieve_units(self, question: str) -> list[str]:
        return self.expand_units(self._match_seeds(question))

    def retrieve_context(self, question: str) -> str:
        return "\n".join(self.retrieve_units(question))
