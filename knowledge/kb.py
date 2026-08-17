"""은행권 온톨로지 Knowledge Base.

rdflib 그래프 위에 은행 에이전트가 쓰기 좋은 조회 API를 제공한다:
- 개념 검색 (한국어/영어 레이블)
- 개념 상세 (정의, 상위/하위 클래스, 관련 속성)
- 클래스 계층 탐색
- 인스턴스 조회
- 임의 SPARQL 실행
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

REPO_ROOT = Path(__file__).resolve().parent.parent
BANK_ONTO_NS = "https://w3id.org/bank-onto/"

PREFIXES = {
    "core": f"{BANK_ONTO_NS}core/",
    "parties": f"{BANK_ONTO_NS}parties/",
    "products": f"{BANK_ONTO_NS}products/",
    "accounts": f"{BANK_ONTO_NS}accounts/",
    "loans": f"{BANK_ONTO_NS}loans/",
    "transactions": f"{BANK_ONTO_NS}transactions/",
    "risk": f"{BANK_ONTO_NS}risk/",
    "ex": f"{BANK_ONTO_NS}examples/",
    "market": f"{BANK_ONTO_NS}market/",
    "mktd": f"{BANK_ONTO_NS}market/data/",
    "regs": f"{BANK_ONTO_NS}regs/",
    "regd": f"{BANK_ONTO_NS}regs/data/",
}


@dataclass
class ConceptSummary:
    uri: str
    labels: list[str]
    definition: str | None = None

    def to_dict(self) -> dict:
        return {"uri": self.uri, "labels": self.labels, "definition": self.definition}


@dataclass
class ConceptDetail:
    uri: str
    kind: str  # "class" | "object_property" | "datatype_property" | "individual"
    labels: list[str] = field(default_factory=list)
    definition: str | None = None
    superclasses: list[str] = field(default_factory=list)
    subclasses: list[str] = field(default_factory=list)
    properties: list[dict] = field(default_factory=list)
    see_also: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "uri": self.uri,
            "kind": self.kind,
            "labels": self.labels,
            "definition": self.definition,
            "superclasses": self.superclasses,
            "subclasses": self.subclasses,
            "properties": self.properties,
            "fibo_references": self.see_also,
            "types": self.types,
        }


class BankKnowledgeBase:
    """온톨로지 + 인스턴스 그래프에 대한 조회 계층."""

    def __init__(self, ontology_dir: Path | None = None, examples_dir: Path | None = None,
                 include_examples: bool = True, data_dir: Path | None = None,
                 include_data: bool = True):
        self.graph = Graph()
        ontology_dir = ontology_dir or REPO_ROOT / "ontology"
        examples_dir = examples_dir or REPO_ROOT / "examples"
        data_dir = data_dir or REPO_ROOT / "data"

        for ttl in sorted(ontology_dir.glob("*.ttl")):
            self.graph.parse(ttl, format="turtle")
        if include_examples and examples_dir.exists():
            for ttl in sorted(examples_dir.glob("*.ttl")):
                self.graph.parse(ttl, format="turtle")
        # 시장 데이터 (ingest/fss_to_ttl.py 결과물) — 있으면 함께 로드
        if include_data and data_dir.exists():
            for ttl in sorted(data_dir.glob("*.ttl")):
                self.graph.parse(ttl, format="turtle")

        for prefix, ns in PREFIXES.items():
            self.graph.bind(prefix, ns, replace=True)

    # ------------------------------------------------------------------
    # 내부 유틸
    # ------------------------------------------------------------------
    def _labels(self, node: URIRef) -> list[str]:
        return [str(lbl) for lbl in self.graph.objects(node, RDFS.label)]

    def _definition(self, node: URIRef) -> str | None:
        for d in self.graph.objects(node, SKOS.definition):
            return str(d)
        return None

    def _qname(self, node) -> str:
        if isinstance(node, URIRef):
            try:
                return self.graph.namespace_manager.normalizeUri(node)
            except Exception:  # noqa: BLE001
                return str(node)
        return str(node)

    def resolve(self, term: str) -> URIRef | None:
        """이름/레이블/URI/qname으로 온톨로지 노드를 찾는다."""
        # 1) 완전한 URI
        if term.startswith("http"):
            uri = URIRef(term)
            if (uri, None, None) in self.graph:
                return uri
        # 2) prefix:LocalName 형태
        if ":" in term and not term.startswith("http"):
            prefix, local = term.split(":", 1)
            if prefix in PREFIXES:
                uri = URIRef(PREFIXES[prefix] + local)
                if (uri, None, None) in self.graph:
                    return uri
        # 3) 각 네임스페이스에서 LocalName 매칭
        for ns in PREFIXES.values():
            uri = URIRef(ns + term)
            if (uri, None, None) in self.graph:
                return uri
        # 4) 레이블 완전 일치 (언어 무관)
        for subj, lbl in self.graph.subject_objects(RDFS.label):
            if isinstance(subj, URIRef) and str(lbl) == term:
                return subj
        return None

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------
    def search_concepts(self, query: str, limit: int = 10) -> list[ConceptSummary]:
        """레이블/정의에 대한 부분 일치 검색 (한국어·영어)."""
        query_lower = query.lower()
        scored: list[tuple[int, ConceptSummary]] = []
        seen: set[str] = set()

        for subj, lbl in self.graph.subject_objects(RDFS.label):
            if not (isinstance(subj, URIRef) and str(subj).startswith(BANK_ONTO_NS)):
                continue
            label_text = str(lbl)
            uri = str(subj)
            if uri in seen:
                continue
            score = None
            if label_text.lower() == query_lower:
                score = 0
            elif query_lower in label_text.lower():
                score = 1
            else:
                definition = self._definition(subj)
                if definition and query_lower in definition.lower():
                    score = 2
            if score is not None:
                seen.add(uri)
                scored.append((score, ConceptSummary(
                    uri=self._qname(subj),
                    labels=self._labels(subj),
                    definition=self._definition(subj),
                )))

        scored.sort(key=lambda pair: pair[0])
        return [summary for _, summary in scored[:limit]]

    def get_concept(self, term: str) -> ConceptDetail | None:
        """개념의 정의, 계층, 관련 속성을 반환한다."""
        node = self.resolve(term)
        if node is None:
            return None

        types = set(self.graph.objects(node, RDF.type))
        if OWL.Class in types:
            kind = "class"
        elif OWL.ObjectProperty in types:
            kind = "object_property"
        elif OWL.DatatypeProperty in types:
            kind = "datatype_property"
        else:
            kind = "individual"

        detail = ConceptDetail(
            uri=self._qname(node),
            kind=kind,
            labels=self._labels(node),
            definition=self._definition(node),
            see_also=[str(s) for s in self.graph.objects(node, RDFS.seeAlso)],
            types=[self._qname(t) for t in types if isinstance(t, URIRef)],
        )

        if kind == "class":
            detail.superclasses = [
                self._qname(sup) for sup in self.graph.objects(node, RDFS.subClassOf)
                if isinstance(sup, URIRef)
            ]
            detail.subclasses = [
                self._qname(sub) for sub in self.graph.subjects(RDFS.subClassOf, node)
                if isinstance(sub, URIRef)
            ]
            detail.properties = self._properties_of_class(node)
        elif kind in ("object_property", "datatype_property"):
            domains = [self._qname(d) for d in self.graph.objects(node, RDFS.domain)]
            ranges = [self._qname(r) for r in self.graph.objects(node, RDFS.range)]
            detail.properties = [{"domain": domains, "range": ranges}]
        return detail

    def _properties_of_class(self, cls: URIRef) -> list[dict]:
        """해당 클래스(및 상위 클래스)를 domain으로 갖는 속성 목록."""
        ancestors = {cls}
        frontier = [cls]
        while frontier:
            current = frontier.pop()
            for sup in self.graph.objects(current, RDFS.subClassOf):
                if isinstance(sup, URIRef) and sup not in ancestors:
                    ancestors.add(sup)
                    frontier.append(sup)

        props = []
        for prop_type in (OWL.ObjectProperty, OWL.DatatypeProperty):
            for prop in self.graph.subjects(RDF.type, prop_type):
                for domain in self.graph.objects(prop, RDFS.domain):
                    if domain in ancestors:
                        ranges = [self._qname(r) for r in self.graph.objects(prop, RDFS.range)]
                        props.append({
                            "property": self._qname(prop),
                            "labels": self._labels(prop),
                            "range": ranges,
                        })
                        break
        return props

    def get_hierarchy(self, term: str, depth: int = 3) -> dict | None:
        """클래스를 루트로 하는 하위 클래스 트리를 반환한다."""
        node = self.resolve(term)
        if node is None:
            return None

        def build(cls: URIRef, remaining: int) -> dict:
            entry = {
                "uri": self._qname(cls),
                "labels": self._labels(cls),
            }
            if remaining > 0:
                children = [
                    build(sub, remaining - 1)
                    for sub in self.graph.subjects(RDFS.subClassOf, cls)
                    if isinstance(sub, URIRef)
                ]
                if children:
                    entry["subclasses"] = children
            return entry

        return build(node, depth)

    def get_instances(self, term: str, limit: int = 20) -> list[dict] | None:
        """클래스의 인스턴스(하위 클래스 포함)를 반환한다."""
        node = self.resolve(term)
        if node is None:
            return None
        descendants = {node}
        frontier = [node]
        while frontier:
            current = frontier.pop()
            for sub in self.graph.subjects(RDFS.subClassOf, current):
                if isinstance(sub, URIRef) and sub not in descendants:
                    descendants.add(sub)
                    frontier.append(sub)

        results = []
        for cls in descendants:
            for inst in self.graph.subjects(RDF.type, cls):
                if not isinstance(inst, URIRef):
                    continue
                results.append({
                    "uri": self._qname(inst),
                    "type": self._qname(cls),
                    "labels": self._labels(inst),
                })
                if len(results) >= limit:
                    return results
        return results

    def describe_instance(self, term: str) -> dict | None:
        """인스턴스의 모든 속성-값을 반환한다."""
        node = self.resolve(term)
        if node is None:
            return None
        facts = []
        for pred, obj in self.graph.predicate_objects(node):
            value = str(obj) if isinstance(obj, Literal) else self._qname(obj)
            facts.append({"property": self._qname(pred), "value": value})
        inbound = []
        for subj, pred in self.graph.subject_predicates(node):
            if isinstance(subj, URIRef):
                inbound.append({"subject": self._qname(subj), "property": self._qname(pred)})
        return {"uri": self._qname(node), "facts": facts, "referenced_by": inbound}

    def run_sparql(self, query: str, limit: int = 50) -> list[dict]:
        """SELECT SPARQL 쿼리를 실행한다. 프리픽스(core, parties, ...)는 자동 바인딩."""
        results = self.graph.query(query)
        rows = []
        var_names = [str(v) for v in results.vars] if results.vars else []
        for row in list(results)[:limit]:
            rows.append({
                name: (str(value) if isinstance(value, Literal) else self._qname(value))
                for name, value in zip(var_names, row)
                if value is not None
            })
        return rows

    def stats(self) -> dict:
        return {
            "triples": len(self.graph),
            "classes": sum(1 for _ in self.graph.subjects(RDF.type, OWL.Class)),
            "object_properties": sum(1 for _ in self.graph.subjects(RDF.type, OWL.ObjectProperty)),
            "datatype_properties": sum(1 for _ in self.graph.subjects(RDF.type, OWL.DatatypeProperty)),
            "namespaces": PREFIXES,
        }
