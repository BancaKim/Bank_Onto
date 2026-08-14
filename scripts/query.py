#!/usr/bin/env python3
"""examples/queries.sparql 의 예시 쿼리를 온톨로지+인스턴스 그래프에 실행한다.

사용법:
    python scripts/query.py
"""
import re
import sys
from pathlib import Path

from rdflib import Graph

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_graph() -> Graph:
    graph = Graph()
    for ttl in sorted((REPO_ROOT / "ontology").glob("*.ttl")):
        graph.parse(ttl, format="turtle")
    for ttl in sorted((REPO_ROOT / "examples").glob("*.ttl")):
        graph.parse(ttl, format="turtle")
    return graph


def split_queries(text: str) -> list[tuple[str, str]]:
    """'# Q1.' 형태의 제목 주석을 기준으로 쿼리를 분리한다."""
    queries: list[tuple[str, list[str]]] = []
    current_title = None
    current_lines: list[str] = []
    for line in text.splitlines():
        title_match = re.match(r"#\s*(Q\d+\..*)", line)
        if title_match:
            if current_title and current_lines:
                queries.append((current_title, current_lines))
            current_title = title_match.group(1).strip()
            current_lines = []
        elif current_title and not line.strip().startswith("#"):
            current_lines.append(line)
    if current_title and current_lines:
        queries.append((current_title, current_lines))

    return [
        (title, "\n".join(lines).strip())
        for title, lines in queries
        if "SELECT" in "\n".join(lines)
    ]


def main() -> int:
    graph = load_graph()
    print(f"그래프 로드 완료: {len(graph)} triples\n")

    sparql_file = REPO_ROOT / "examples" / "queries.sparql"
    queries = split_queries(sparql_file.read_text(encoding="utf-8"))

    # rdfs 프리픽스가 없는 쿼리를 위해 공통 프리픽스 보강
    common_prefix = "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"

    for title, query in queries:
        print(f"=== {title} ===")
        if "PREFIX rdfs:" not in query:
            query = common_prefix + query
        try:
            results = graph.query(query)
            rows = list(results)
            if not rows:
                print("  (결과 없음)")
            for row in rows:
                values = ", ".join(
                    str(v) if v is not None else "-" for v in row
                )
                print(f"  {values}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [ERROR] {exc}")
            return 1
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
