"""벡터 RAG 베이스라인용 코퍼스 생성.

온톨로지의 모든 개체를 텍스트 문서로 직렬화(verbalize)한 뒤,
전형적인 RAG 파이프라인처럼 고정 크기 청크로 분할한다.
두 시스템(벡터/그래프)이 정확히 같은 지식에서 출발하도록 보장하는 역할.
"""
from __future__ import annotations

from rdflib import BNode, Literal, URIRef
from rdflib.namespace import OWL, RDFS, SKOS

from knowledge.kb import BANK_ONTO_NS, BankKnowledgeBase


from knowledge.kb import PREFIXES
from rdflib import URIRef as _URIRef

_NAME_PREDICATES = (
    _URIRef(PREFIXES["parties"] + "hasName"),
    _URIRef(PREFIXES["products"] + "hasProductName"),
)


def label_of(kb: BankKnowledgeBase, node) -> str:
    """한국어 레이블 우선, 없으면 고유명(hasName 등), 최후에 qname."""
    if isinstance(node, Literal):
        return str(node)
    labels = sorted(kb.graph.objects(node, RDFS.label), key=str)
    ko = [str(lbl) for lbl in labels if getattr(lbl, "language", None) == "ko"]
    if ko:
        return ko[0]
    if labels:
        return str(labels[0])
    for pred in _NAME_PREDICATES:
        for name in sorted(kb.graph.objects(node, pred), key=str):
            return str(name)
    return kb._qname(node)


def build_documents(kb: BankKnowledgeBase) -> list[str]:
    """온톨로지의 모든 개체를 '개체당 하나의 텍스트 블록'으로 직렬화한다."""
    return [text for _, text in build_entity_documents(kb)]


def build_relation_documents(kb: BankKnowledgeBase) -> list[str]:
    """트리플 하나를 문장 하나로 직렬화한 '관계 문서' 코퍼스
    (논문의 relations-documents 변형). 주어·술어·목적어를 레이블로 풀어 쓴다."""
    docs = []
    for subj, text in build_entity_documents(kb):
        header, *lines = text.split("\n")
        subj_label = header[3:].rsplit(" (", 1)[0] if header.startswith("## ") else header
        for line in lines:
            if line.startswith("- "):
                docs.append(f"{subj_label} — {line[2:]}")
            elif line.startswith("정의: "):
                docs.append(f"{subj_label} — {line}")
    return docs


def build_entity_documents(kb: BankKnowledgeBase) -> list[tuple[str, str]]:
    """(개체 qname, 직렬화 텍스트) 쌍 목록 — 하이브리드 시나리오가 벡터 히트를
    그래프 노드로 되돌릴 때 qname을 사용한다."""
    docs = []
    subjects = sorted(
        {s for s in kb.graph.subjects() if isinstance(s, URIRef)
         and str(s).startswith(BANK_ONTO_NS)},
        key=str,
    )
    for subj in subjects:
        lines = [f"## {label_of(kb, subj)} ({kb._qname(subj)})"]
        definition = kb._definition(subj)
        if definition:
            lines.append(f"정의: {definition}")
        for pred, obj in kb.graph.predicate_objects(subj):
            if pred in (RDFS.label, SKOS.definition) or isinstance(obj, BNode):
                continue
            if obj in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.Ontology):
                continue
            value = str(obj) if isinstance(obj, Literal) else label_of(kb, obj)
            lines.append(f"- {label_of(kb, pred)}: {value}")
        docs.append((kb._qname(subj), "\n".join(lines)))
    return docs


def chunk_corpus(docs: list[str], size: int = 400, overlap: int = 80) -> list[str]:
    """전형적 RAG 방식의 고정 크기 슬라이딩 윈도우 청킹."""
    text = "\n\n".join(docs)
    chunks = []
    step = size - overlap
    i = 0
    while i < len(text):
        chunks.append(text[i:i + size])
        i += step
    return chunks
