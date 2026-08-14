#!/usr/bin/env python3
"""은행권 온톨로지 검증 스크립트.

모든 Turtle 파일의 구문을 검증하고, 클래스/속성 통계와
기본적인 무결성 검사(미정의 클래스 참조 등) 결과를 출력한다.

사용법:
    python scripts/validate.py
"""
import sys
from pathlib import Path

from rdflib import Graph, RDF, RDFS, OWL, URIRef

REPO_ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY_DIR = REPO_ROOT / "ontology"
EXAMPLES_DIR = REPO_ROOT / "examples"

BANK_ONTO_NS = "https://w3id.org/bank-onto/"


def parse_files() -> tuple[Graph, list[str]]:
    """모든 .ttl 파일을 하나의 그래프로 병합 파싱한다."""
    graph = Graph()
    errors = []
    ttl_files = sorted(ONTOLOGY_DIR.glob("*.ttl")) + sorted(EXAMPLES_DIR.glob("*.ttl"))
    if not ttl_files:
        errors.append("No .ttl files found.")
        return graph, errors

    for ttl in ttl_files:
        try:
            graph.parse(ttl, format="turtle")
            print(f"  [OK] {ttl.relative_to(REPO_ROOT)}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{ttl.name}: {exc}")
            print(f"  [FAIL] {ttl.relative_to(REPO_ROOT)}: {exc}")
    return graph, errors


def collect_stats(graph: Graph) -> dict[str, int]:
    classes = set(graph.subjects(RDF.type, OWL.Class))
    obj_props = set(graph.subjects(RDF.type, OWL.ObjectProperty))
    data_props = set(graph.subjects(RDF.type, OWL.DatatypeProperty))
    ontologies = set(graph.subjects(RDF.type, OWL.Ontology))

    typed_subjects = set(graph.subjects(RDF.type, None))
    schema_things = classes | obj_props | data_props | ontologies
    individuals = {
        s for s in typed_subjects
        if isinstance(s, URIRef) and s not in schema_things
    }

    return {
        "ontology_modules": len(ontologies),
        "classes": len(classes),
        "object_properties": len(obj_props),
        "datatype_properties": len(data_props),
        "individuals": len(individuals),
        "triples": len(graph),
    }


def check_undefined_references(graph: Graph) -> list[str]:
    """subClassOf / domain / range가 가리키는 클래스가 정의됐는지 검사한다."""
    defined_classes = set(graph.subjects(RDF.type, OWL.Class))
    warnings = []

    def is_bank_onto_class(node) -> bool:
        return isinstance(node, URIRef) and str(node).startswith(BANK_ONTO_NS)

    for predicate in (RDFS.subClassOf, RDFS.domain, RDFS.range):
        for subject, obj in graph.subject_objects(predicate):
            if is_bank_onto_class(obj) and obj not in defined_classes:
                # 개체(enumerated individual)를 range로 쓰는 경우는 클래스 정의 확인
                if (obj, RDF.type, None) not in graph:
                    warnings.append(
                        f"{predicate.split('#')[-1]}: {subject.n3(graph.namespace_manager)} "
                        f"-> undefined {obj.n3(graph.namespace_manager)}"
                    )
    return warnings


def check_labels(graph: Graph) -> list[str]:
    """bank-onto 네임스페이스의 모든 클래스에 한국어 레이블이 있는지 검사한다."""
    missing = []
    for cls in graph.subjects(RDF.type, OWL.Class):
        if not (isinstance(cls, URIRef) and str(cls).startswith(BANK_ONTO_NS)):
            continue
        labels = list(graph.objects(cls, RDFS.label))
        has_korean = any(getattr(lbl, "language", None) == "ko" for lbl in labels)
        if not has_korean:
            missing.append(str(cls))
    return missing


def main() -> int:
    print("=== 은행권 온톨로지 검증 (Bank_Onto Validation) ===\n")
    print("[1] Turtle 구문 검증")
    graph, errors = parse_files()

    if errors:
        print(f"\n구문 오류 {len(errors)}건:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("\n[2] 온톨로지 통계")
    stats = collect_stats(graph)
    for key, value in stats.items():
        print(f"  {key:22s}: {value}")

    print("\n[3] 미정의 클래스 참조 검사")
    undefined = check_undefined_references(graph)
    if undefined:
        for warning in undefined:
            print(f"  [WARN] {warning}")
    else:
        print("  이상 없음")

    print("\n[4] 한국어 레이블 누락 검사")
    missing_labels = check_labels(graph)
    if missing_labels:
        for uri in missing_labels:
            print(f"  [WARN] ko label 누락: {uri}")
    else:
        print("  이상 없음")

    has_warnings = bool(undefined or missing_labels)
    print(f"\n검증 완료: {'경고 있음' if has_warnings else '모든 검사 통과'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
