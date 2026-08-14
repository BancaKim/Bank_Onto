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

        # 분류 노드
        for cls in classes:
            self.nodes[key(cls)] = LpgNode(
                key=key(cls), name=label_of(kb, cls), labels=["Category"],
                definition=kb._definition(cls),
            )
        for cls in classes:
            for sup in graph.objects(cls, RDFS.subClassOf):
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

        for ind in individuals:
            node = LpgNode(key=key(ind), name=label_of(kb, ind),
                           definition=kb._definition(ind))
            for pred, obj in graph.predicate_objects(ind):
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
        best: dict[str, float] = {}
        for name, node_key in self._name_index:
            n = name.lower()
            lcs = _lcs_len(n, q)
            threshold = len(n) if len(n) < 4 else 4
            if len(n) >= 2 and lcs >= threshold:
                score = lcs / len(n)
                if score > best.get(node_key, 0):
                    best[node_key] = score
        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        return [k for k, _ in ranked[:limit]]

    # ------------------------------------------------------------------
    # k-hop 이웃 탐색
    # ------------------------------------------------------------------
    def retrieve_context(self, question: str) -> str:
        seeds = self._match_seeds(question)
        if not seeds:
            return ""

        visited: list[str] = list(seeds)
        frontier = list(seeds)
        kept_edges: list[tuple[str, str, str]] = []
        for _ in range(self.hops):
            next_frontier = []
            for node_key in frontier:
                for src, etype, dst in self._adj.get(node_key, []):
                    other = dst if src == node_key else src
                    if (src, etype, dst) not in kept_edges:
                        kept_edges.append((src, etype, dst))
                    if other not in visited:
                        if len(visited) >= self.node_cap:
                            continue
                        visited.append(other)
                        next_frontier.append(other)
            frontier = next_frontier
            if not frontier or len(visited) >= self.node_cap:
                break

        lines = []
        for node_key in visited:
            node = self.nodes.get(node_key)
            if node is None:
                continue
            label_txt = ":".join(node.labels) if node.labels else "Node"
            lines.append(f"({node.name}:{label_txt})")
            if node.definition:
                lines.append(f"  정의: {node.definition}")
            for prop_name, value in node.props.items():
                lines.append(f"  {prop_name}: {value}")
        visited_set = set(visited)
        for src, etype, dst in kept_edges:
            if src in visited_set and dst in visited_set:
                src_name = self.nodes[src].name if src in self.nodes else src
                dst_name = self.nodes[dst].name if dst in self.nodes else dst
                lines.append(f"({src_name}) -[{etype}]-> ({dst_name})")
        return "\n".join(lines)
