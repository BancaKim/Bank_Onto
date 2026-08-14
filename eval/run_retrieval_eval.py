"""검색(retrieval) 수준 비교 평가: 온톨로지 RAG vs 벡터 RAG.

측정 지표:
- 근거 재현율(evidence recall): 정답에 필요한 근거가 컨텍스트에 포함된 비율.
  검색이 근거를 못 가져오면 LLM이 아무리 좋아도 정답 불가능하므로,
  이 지표는 RAG 파이프라인 품질의 상한을 결정한다.
- 컨텍스트 크기: 같은 질문에 대해 제공한 컨텍스트 문자 수.
- NEG(존재하지 않는 개념) 질문에 대한 컨텍스트 제공량 — 0에 가까울수록
  환각 위험이 낮다(모르는 것을 모른다고 할 수 있음).

실행: python eval/run_retrieval_eval.py   (API 키 불필요)
결과: docs/benchmark-report.md
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.benchmark_questions import NEGATIVE_QUESTIONS, QUESTIONS
from eval.corpus import build_documents, chunk_corpus
from eval.graph_rag import GraphRetriever
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


def evidence_recall(context: str, gold: list[str]) -> tuple[int, int]:
    found = sum(1 for g in gold if g in context)
    return found, len(gold)


def main() -> int:
    kb = BankKnowledgeBase()
    docs = build_documents(kb)
    chunks = chunk_corpus(docs)
    vector = TfidfVectorRetriever(chunks)
    graph = GraphRetriever(kb)

    print(f"코퍼스: 문서 {len(docs)}개 → 청크 {len(chunks)}개 (400자/80자 중첩)\n")

    rows = []
    for q in QUESTIONS:
        v_ctx = vector.retrieve_context(q["question"], k=5)
        g_ctx = graph.retrieve_context(q["question"])
        v_found, total = evidence_recall(v_ctx, q["gold"])
        g_found, _ = evidence_recall(g_ctx, q["gold"])
        rows.append({
            "id": q["id"], "category": q["category"], "question": q["question"],
            "total": total,
            "vector_found": v_found, "graph_found": g_found,
            "vector_chars": len(v_ctx), "graph_chars": len(g_ctx),
            "vector_missing": [g for g in q["gold"] if g not in v_ctx],
            "graph_missing": [g for g in q["gold"] if g not in g_ctx],
        })
        print(f"  {q['id']:8s} vector {v_found}/{total}   graph {g_found}/{total}")

    neg_rows = []
    for q in NEGATIVE_QUESTIONS:
        v_ctx = vector.retrieve_context(q["question"], k=5)
        g_ctx = graph.retrieve_context(q["question"])
        neg_rows.append({
            "id": q["id"], "question": q["question"],
            "vector_chars": len(v_ctx), "graph_chars": len(g_ctx),
        })
        print(f"  {q['id']:8s} vector {len(v_ctx)}자 제공   graph {len(g_ctx)}자 제공")

    # ------------------------------------------------------------------
    # 집계
    # ------------------------------------------------------------------
    def rate(items, key_found):
        found = sum(r[key_found] for r in items)
        total = sum(r["total"] for r in items)
        return found / total if total else 0.0

    overall_v, overall_g = rate(rows, "vector_found"), rate(rows, "graph_found")
    per_cat = {}
    for cat in CATEGORY_NAMES:
        cat_rows = [r for r in rows if r["category"] == cat]
        per_cat[cat] = (rate(cat_rows, "vector_found"), rate(cat_rows, "graph_found"))

    perfect_v = sum(1 for r in rows if r["vector_found"] == r["total"])
    perfect_g = sum(1 for r in rows if r["graph_found"] == r["total"])
    avg_chars_v = sum(r["vector_chars"] for r in rows) / len(rows)
    avg_chars_g = sum(r["graph_chars"] for r in rows) / len(rows)

    print(f"\n전체 근거 재현율: vector {overall_v:.0%}  /  graph {overall_g:.0%}")
    print(f"완전 답변 가능 질문: vector {perfect_v}/{len(rows)}  /  graph {perfect_g}/{len(rows)}")

    # ------------------------------------------------------------------
    # 리포트 작성
    # ------------------------------------------------------------------
    md = []
    md.append("# 온톨로지 RAG vs 벡터 RAG 벤치마크 리포트\n")
    md.append("동일한 온톨로지 지식을 두 방식으로 검색했을 때, 정답에 필요한 근거를 "
              "컨텍스트로 가져올 수 있는지(근거 재현율)를 비교한다. 검색이 근거를 놓치면 "
              "LLM 성능과 무관하게 정답이 불가능하므로, 이 지표는 각 RAG 파이프라인의 "
              "**품질 상한**을 결정한다.\n")
    md.append("## 실험 설정\n")
    md.append("| 항목 | 벡터 RAG (베이스라인) | 온톨로지 RAG |")
    md.append("|---|---|---|")
    md.append("| 지식 소스 | 온톨로지 전체를 텍스트로 직렬화 후 400자 청크(80자 중첩) | 온톨로지 그래프 직접 질의 |")
    md.append(f"| 검색 방식 | 문자 n-gram TF-IDF 코사인, top-5 | 개념 매칭 → 계층/속성/BFS 이웃 탐색 |")
    md.append(f"| 코퍼스 규모 | 문서 {len(docs)}개, 청크 {len(chunks)}개 | 트리플 {kb.stats()['triples']}개 |")
    md.append("| LLM 사용 | 없음(검색 단계만 평가, 결정적·재현 가능) | 없음(동일) |\n")
    md.append("## 종합 결과\n")
    md.append("| 지표 | 벡터 RAG | 온톨로지 RAG |")
    md.append("|---|---|---|")
    md.append(f"| **근거 재현율 (전체)** | {overall_v:.0%} | **{overall_g:.0%}** |")
    md.append(f"| 완전 답변 가능 질문 수 | {perfect_v}/{len(rows)} | **{perfect_g}/{len(rows)}** |")
    md.append(f"| 평균 컨텍스트 크기 | {avg_chars_v:,.0f}자 | {avg_chars_g:,.0f}자 |")
    neg_v = sum(r["vector_chars"] for r in neg_rows) / len(neg_rows)
    neg_g = sum(r["graph_chars"] for r in neg_rows) / len(neg_rows)
    md.append(f"| 답 없는 질문에 제공한 컨텍스트(환각 위험) | {neg_v:,.0f}자 | **{neg_g:,.0f}자** |\n")

    md.append("## 범주별 근거 재현율\n")
    md.append("| 범주 | 벡터 RAG | 온톨로지 RAG |")
    md.append("|---|---|---|")
    for cat, name in CATEGORY_NAMES.items():
        v, g = per_cat[cat]
        md.append(f"| {name} ({cat}) | {v:.0%} | {g:.0%} |")
    md.append("")

    md.append("## 질문별 상세\n")
    md.append("| ID | 질문 | 벡터 | 그래프 | 벡터가 놓친 근거 |")
    md.append("|---|---|---|---|---|")
    for r in rows:
        miss = ", ".join(r["vector_missing"]) or "-"
        md.append(f"| {r['id']} | {r['question']} | {r['vector_found']}/{r['total']} "
                  f"| {r['graph_found']}/{r['total']} | {miss} |")
    md.append("")

    md.append("## 존재하지 않는 개념 (환각 유도 질문)\n")
    md.append("정답이 지식에 없는 질문이다. 이때 컨텍스트를 제공하면 LLM이 관련 없어 보이는 "
              "내용으로 그럴듯한 답을 지어낼 위험이 커진다. 온톨로지 RAG는 매칭 개념이 없음을 "
              "구조적으로 판별해 빈 컨텍스트를 반환한다(→ \"모릅니다\" 답변 유도).\n")
    md.append("| ID | 질문 | 벡터 RAG 제공 컨텍스트 | 온톨로지 RAG 제공 컨텍스트 |")
    md.append("|---|---|---|---|")
    for r in neg_rows:
        md.append(f"| {r['id']} | {r['question']} | {r['vector_chars']:,}자 (top-5 청크 무조건 반환) "
                  f"| {r['graph_chars']}자 |")
    md.append("")

    md.append("""## 해석

**벡터 RAG가 구조적으로 실패하는 지점**이 결과에 그대로 드러난다:

1. **다중 홉(MULTIHOP)**: "김민준 대출의 담보 가치"는 고객 → 차주 역할 → 대출계약 →
   담보 → 감정가로 4개 개체를 건너야 한다. 청킹은 이 연결을 물리적으로 절단하므로
   유사도 검색이 중간 고리를 놓치면 복원할 방법이 없다. 그래프는 관계를 따라가면 된다.
2. **분류 열거(HIER)**: "은행 종류 전부"는 하위 클래스 4개가 **빠짐없이** 필요하다.
   top-k 검색은 몇 개를 가져올진 몰라도 전부 가져온다는 보장이 없다. 그래프의
   `rdfs:subClassOf` 탐색은 완전성이 보장된다.
3. **집계(AGG)**: "예금자보호 되는 상품"은 조건 필터다. 유사도는 조건 평가가 아니므로
   우연에 기댄다. 그래프/SPARQL은 조건을 정확히 평가한다.
4. **환각 방지(NEG)**: 벡터 검색은 답이 없어도 항상 top-k를 반환해 LLM에 오답 재료를
   공급한다. 온톨로지는 "해당 개념 없음"을 판별할 수 있다.

## 한계와 공정성

- 벡터 베이스라인은 외부 API 없이 재현 가능하도록 **어휘적(TF-IDF) 벡터**를 사용했다.
  의미 임베딩(예: text-embedding 모델)이면 DEF 범주는 더 좋아질 수 있으나, 다중 홉의
  "연결 절단" 문제와 열거의 "완전성 미보장", 집계의 "조건 평가 불가"는 임베딩 품질과
  무관한 **청킹+유사도 패러다임 자체의 한계**다.
- 온톨로지 리트리버는 LLM 없이 결정적으로 동작하는 버전이다. 실제 에이전트
  (`agent/bank_agent.py`)는 LLM이 도구·SPARQL을 선택하므로 이 수치는 그래프 접근의
  **하한**이다.
- 답변 품질(LLM 최종 답) 수준의 비교는 `eval/run_e2e.py`로 실행할 수 있다
  (ANTHROPIC_API_KEY 필요).

*이 리포트는 `python eval/run_retrieval_eval.py`로 재생성할 수 있다.*
""")

    REPORT_PATH.write_text("\n".join(md), encoding="utf-8")
    print(f"\n리포트 저장: {REPORT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
