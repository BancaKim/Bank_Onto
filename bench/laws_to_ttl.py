"""수집된 법령 JSON(data/laws/*.json) → 온톨로지 인스턴스(TTL) 변환.

data/law-instances.ttl 로 저장하며, KB(knowledge/kb.py)가 data/*.ttl 을
자동 로드하므로 규정형 벤치마크의 근거 코퍼스가 지식층에 포함된다.

실행: python bench/laws_to_ttl.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDF, RDFS, XSD

REPO_ROOT = Path(__file__).resolve().parent.parent
LAWS_DIR = REPO_ROOT / "data" / "laws"
OUTPUT = REPO_ROOT / "data" / "law-instances.ttl"

REGS = Namespace("https://w3id.org/bank-onto/regs/")
REGD = Namespace("https://w3id.org/bank-onto/regs/data/")


def iso(date8: str) -> str:
    return f"{date8[:4]}-{date8[4:6]}-{date8[6:]}"


def main() -> int:
    graph = Graph()
    graph.bind("regs", REGS)
    graph.bind("regd", REGD)
    graph.bind("rdfs", RDFS)

    n_articles = 0
    for path in sorted(LAWS_DIR.glob("*.json")):
        law = json.loads(path.read_text(encoding="utf-8"))
        statute = REGD[f"law_{law['slug']}"]
        graph.add((statute, RDF.type, REGS.Statute))
        graph.add((statute, RDFS.label, Literal(law["name"], lang="ko")))
        graph.add((statute, REGS.lawType, Literal(law["law_type"])))
        graph.add((statute, REGS.ministry, Literal(law["ministry"])))
        graph.add((statute, REGS.effectiveDate,
                   Literal(iso(law["effective_date"]), datatype=XSD.date)))

        for i, art in enumerate(law["articles"]):
            node = REGD[f"art_{law['slug']}_{i:04d}"]
            n_articles += 1
            graph.add((node, RDF.type, REGS.LegalArticle))
            title = f"({art['title']})" if art["title"] else ""
            graph.add((node, RDFS.label,
                       Literal(f"「{law['name']}」 {art['label']}{title}", lang="ko")))
            graph.add((node, REGS.articleLabel, Literal(art["label"])))
            if art["title"]:
                graph.add((node, REGS.articleTitle, Literal(art["title"])))
            graph.add((node, REGS.articleText, Literal(art["text"])))
            graph.add((node, REGS.belongsToStatute, statute))
            graph.add((statute, REGS.hasArticle, node))

    graph.serialize(OUTPUT, format="turtle")
    print(f"변환: 법령 {len(list(LAWS_DIR.glob('*.json')))}종, 조문 {n_articles}개, "
          f"트리플 {len(graph)}개 → {OUTPUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
