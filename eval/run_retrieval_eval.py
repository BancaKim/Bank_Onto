"""검색(retrieval) 수준 3-way 비교: 벡터 RAG vs Graph RAG(LPG) vs 온톨로지 RAG.

측정 지표:
- 근거 재현율(evidence recall): 정답에 필요한 근거가 컨텍스트에 포함된 비율.
  검색이 근거를 못 가져오면 LLM이 아무리 좋아도 정답이 불가능하므로,
  이 지표는 각 RAG 파이프라인 품질의 상한을 결정한다.
- NEG(존재하지 않는 개념) 질문에 제공한 컨텍스트 양 — 0에 가까울수록
  환각 위험이 낮다.

답변(생성) 수준 평가는 eval/run_answer_eval.py 참고 (API 키 필요).

실행: python eval/run_retrieval_eval.py   (API 키 불필요, 결정적)
결과: docs/benchmark-report.md
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.benchmark_questions import NEGATIVE_QUESTIONS, QUESTIONS
from eval.corpus import build_documents, chunk_corpus
from eval.graph_rag import GraphRetriever
from eval.lpg_rag import LpgGraphRetriever
from eval.vector_rag import TfidfVectorRetriever
from knowledge.kb import BankKnowledgeBase

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "docs" / "benchmark-report.md"

CATEGORY_NAMES = {
    "DEF": "단순 정의",
    "HIER": "분류 열거",
    "MULTIHOP": "다중 홉",
    "AGG": "집계/필터",
    "SCHEMA": "스키마",
}

SYSTEMS = ["vector", "lpg", "onto"]
SYSTEM_NAMES = {"vector": "벡터 RAG", "lpg": "Graph RAG(LPG)", "onto": "온톨로지 RAG"}


def main() -> int:
    kb = BankKnowledgeBase()
    docs = build_documents(kb)
    chunks = chunk_corpus(docs)
    retrievers = {
        "vector": lambda q: TfidfVectorRetriever.retrieve_context(vector, q, k=5),
        "lpg": lambda q: lpg.retrieve_context(q),
        "onto": lambda q: onto.retrieve_context(q),
    }
    vector = TfidfVectorRetriever(chunks)
    lpg = LpgGraphRetriever(kb)
    onto = GraphRetriever(kb)

    print(f"코퍼스: 문서 {len(docs)}개 → 청크 {len(chunks)}개 / "
          f"LPG: 노드 {len(lpg.nodes)}개, 엣지 {len(lpg.edges)}개\n")

    rows = []
    for q in QUESTIONS:
        contexts = {s: retrievers[s](q["question"]) for s in SYSTEMS}
        row = {"id": q["id"], "category": q["category"], "question": q["question"],
               "total": len(q["gold"])}
        for s in SYSTEMS:
            row[s] = sum(1 for g in q["gold"] if g in contexts[s])
            row[f"{s}_chars"] = len(contexts[s])
            row[f"{s}_missing"] = [g for g in q["gold"] if g not in contexts[s]]
        rows.append(row)
        print(f"  {q['id']:8s} " + "  ".join(
            f"{s} {row[s]}/{row['total']}" for s in SYSTEMS))

    neg_rows = []
    for q in NEGATIVE_QUESTIONS:
        contexts = {s: retrievers[s](q["question"]) for s in SYSTEMS}
        neg_rows.append({"id": q["id"], "question": q["question"],
                         **{f"{s}_chars": len(contexts[s]) for s in SYSTEMS}})
        print(f"  {q['id']:8s} " + "  ".join(
            f"{s} {len(contexts[s])}자" for s in SYSTEMS))

    def recall(items, system):
        return sum(r[system] for r in items) / sum(r["total"] for r in items)

    overall = {s: recall(rows, s) for s in SYSTEMS}
    perfect = {s: sum(1 for r in rows if r[s] == r["total"]) for s in SYSTEMS}
    neg_chars = {s: sum(r[f"{s}_chars"] for r in neg_rows) / len(neg_rows)
                 for s in SYSTEMS}

    print("\n전체 근거 재현율: " + "  ".join(
        f"{s} {overall[s]:.0%}" for s in SYSTEMS))

    md = []
    md.append("# 3-way 벤치마크: 벡터 RAG vs Graph RAG(LPG) vs 온톨로지 RAG\n")
    md.append("동일한 지식을 세 가지 검색 패러다임으로 제공했을 때, 정답에 필요한 근거를 "
              "컨텍스트로 가져오는지(근거 재현율)를 비교한다. 검색이 근거를 놓치면 LLM "
              "성능과 무관하게 정답이 불가능하므로 이 지표는 각 파이프라인의 **상한**이다. "
              "최종 답변 수준 비교는 `eval/run_answer_eval.py`(객관식 정확도 + LLM 심판) 참고.\n")
    md.append("## 실험 설정\n")
    md.append("| | 벡터 RAG | Graph RAG (LPG) | 온톨로지 RAG |")
    md.append("|---|---|---|---|")
    md.append("| 지식 표현 | 직렬화 텍스트 → 400자 청크 | 속성 그래프(노드/엣지, Neo4j식) | OWL 온톨로지(RDF) |")
    md.append("| 검색 | TF-IDF 코사인 top-5 | 개체 시드 → k-hop 이웃 서브그래프 | 개념 매칭 → 계층·속성·SPARQL |")
    md.append(f"| 규모 | 청크 {len(chunks)}개 | 노드 {len(lpg.nodes)} / 엣지 {len(lpg.edges)} | 트리플 {kb.stats()['triples']} |")
    md.append("| 시드 매칭 | (해당 없음) | 온톨로지 RAG와 동일 기준(LCS) | 동일 기준(LCS) |\n")
    md.append("## 종합 결과\n")
    md.append("| 지표 | 벡터 RAG | Graph RAG(LPG) | 온톨로지 RAG |")
    md.append("|---|---|---|---|")
    md.append(f"| **근거 재현율 (전체)** | {overall['vector']:.0%} | {overall['lpg']:.0%} "
              f"| **{overall['onto']:.0%}** |")
    md.append(f"| 완전 답변 가능 질문 | {perfect['vector']}/{len(rows)} "
              f"| {perfect['lpg']}/{len(rows)} | **{perfect['onto']}/{len(rows)}** |")
    md.append(f"| 답 없는 질문에 준 컨텍스트(환각 위험) | {neg_chars['vector']:,.0f}자 "
              f"| {neg_chars['lpg']:,.0f}자 | {neg_chars['onto']:,.0f}자 |\n")

    md.append("## 범주별 근거 재현율\n")
    md.append("| 범주 | 벡터 | LPG | 온톨로지 |")
    md.append("|---|---|---|---|")
    for cat, name in CATEGORY_NAMES.items():
        cat_rows = [r for r in rows if r["category"] == cat]
        md.append(f"| {name} ({cat}) | " + " | ".join(
            f"{recall(cat_rows, s):.0%}" for s in SYSTEMS) + " |")
    md.append("")

    md.append("## 질문별 상세\n")
    md.append("| ID | 질문 | 벡터 | LPG | 온톨로지 |")
    md.append("|---|---|---|---|---|")
    for r in rows:
        md.append(f"| {r['id']} | {r['question']} | " + " | ".join(
            f"{r[s]}/{r['total']}" for s in SYSTEMS) + " |")
    md.append("")

    md.append("## 존재하지 않는 개념 (환각 유도 질문)\n")
    md.append("| ID | 질문 | 벡터 | LPG | 온톨로지 |")
    md.append("|---|---|---|---|---|")
    for r in neg_rows:
        md.append(f"| {r['id']} | {r['question']} | {r['vector_chars']:,}자 "
                  f"| {r['lpg_chars']}자 | {r['onto_chars']}자 |")
    md.append("")

    md.append("""## 해석

**세 패러다임의 실패 지점이 서로 다르다:**

1. **벡터 RAG**는 다중 홉(청킹이 관계를 절단), 완전 열거(top-k는 완전성 미보장),
   조건 필터(유사도는 조건 평가가 아님)에서 무너지고, 답이 없는 질문에도 항상 top-k를
   반환해 환각 재료를 공급한다.
2. **Graph RAG(LPG)**는 관계를 물리적으로 따라가므로 다중 홉과 열거에 강하다.
   그러나 **스키마 의미론이 없다**: 속성의 정의역/치역(domain/range) 지식이 없어
   스키마 질의("대출계약에 어떤 당사자 정보가 필요한가")에 약하고, 속성 사용처 역색인이
   없어 집계형 질의("예금자보호 되는 상품")에서 시드를 못 잡으면 실패한다.
3. **온톨로지 RAG**는 LPG의 그래프 탐색에 더해 클래스 계층 추론, 속성 스키마,
   SPARQL 집계를 갖는다 — LPG가 실패하는 지점이 온톨로지 의미론의 기여분이다.

## 한계와 공정성

- 벡터 베이스라인은 재현성을 위해 어휘적(TF-IDF) 벡터를 사용했다. 의미 임베딩이면
  정의(DEF) 범주는 개선되나, 다중 홉·완전 열거·조건 평가의 실패는 청킹+유사도
  패러다임 자체의 한계로 임베딩 품질과 무관하다.
- LPG 베이스라인은 분류 체계를 노드로 함께 적재한 **관대한 변환**이며, 시드 매칭도
  온톨로지 RAG와 동일한 알고리즘을 사용한다 — 차이는 순수하게 스키마 의미론의
  유무에서 나온다. 실무의 text2cypher 방식은 집계가 가능하지만, 서브클래스 추론과
  표준 스키마가 없다는 구조적 차이는 남는다.
- 세 시스템 모두 LLM 없는 결정적 리트리버로 측정했다. 답변 수준 비교는
  `eval/run_answer_eval.py`로 실행한다.

*재생성: `python eval/run_retrieval_eval.py`*
""")

    REPORT_PATH.write_text("\n".join(md), encoding="utf-8")
    print(f"리포트 저장: {REPORT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
