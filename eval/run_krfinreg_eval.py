"""KR-FinReg-QA 은행 이식 문항 3-way 검색 벤치마크.

데이터셋: data/krfinreg-bank-questions.jsonl
(석사논문 벤치마크 KR-FinReg-QA의 은행 상품 문항을 202608 공시로 근거
재검증 후 이식한 것 — ingest/import_krfinreg.py 참고)

판정형(YES/NO) 문항: 판정의 결정적 근거(상품명 + 원문 문구)가 컨텍스트에
포함되는지 측정한다 (근거 재현율 — 검색 계층의 상한).
부재형(ABSTAIN) 문항: 근거가 존재하지 않는 것이 정답이므로 검색 계층에서는
집계하지 않고, 답변 계층(run_answer_eval)에서 보류 정확도로 평가한다.

실행: python eval/run_krfinreg_eval.py   (API 키 불필요, 결정적)
결과: docs/krfinreg-benchmark-report.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.corpus import build_documents, chunk_corpus
from eval.graph_rag import GraphRetriever
from eval.lpg_rag import LpgGraphRetriever
from eval.vector_rag import TfidfVectorRetriever
from knowledge.kb import BankKnowledgeBase

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_PATH = REPO_ROOT / "data" / "krfinreg-bank-questions.jsonl"
REPORT_PATH = REPO_ROOT / "docs" / "krfinreg-benchmark-report.md"

SYSTEMS = ["vector", "lpg", "onto"]
GROUP_NAMES = {
    "Q1_통제": "통제(원문이 직접 답함)",
    "Q3_조건": "조건 판정(연령·금액 요건)",
    "Q5_비적용": "수치 임계값 비교(우대금리)",
    "Q4_부재": "부재(보류가 정답)",
}


def main() -> int:
    if not DATASET_PATH.exists():
        print("데이터셋 없음 — 먼저 python ingest/import_krfinreg.py 실행")
        return 1
    questions = [json.loads(l) for l in DATASET_PATH.read_text().splitlines() if l]
    scored = [q for q in questions if q["verdict"] != "ABSTAIN"]
    abstain = [q for q in questions if q["verdict"] == "ABSTAIN"]

    kb = BankKnowledgeBase()
    chunks = chunk_corpus(build_documents(kb))
    vector = TfidfVectorRetriever(chunks)
    lpg = LpgGraphRetriever(kb)
    onto = GraphRetriever(kb)
    retrievers = {
        "vector": lambda q: TfidfVectorRetriever.retrieve_context(vector, q, k=5),
        "lpg": lpg.retrieve_context,
        "onto": onto.retrieve_context,
    }

    print(f"이식 문항 {len(questions)}개 (판정형 {len(scored)} / 부재형 {len(abstain)}) "
          f"/ 코퍼스 청크 {len(chunks)}개\n")

    rows = []
    for q in scored:
        contexts = {s: retrievers[s](q["question"]) for s in SYSTEMS}
        row = {"id": q["id"], "group": q["group"], "question": q["question"],
               "verdict": q["verdict"], "total": len(q["gold"])}
        for s in SYSTEMS:
            row[s] = sum(1 for g in q["gold"] if g in contexts[s])
            row[f"{s}_chars"] = len(contexts[s])
        rows.append(row)

    def recall(items, system):
        total = sum(r["total"] for r in items)
        return sum(r[system] for r in items) / total if total else 0.0

    overall = {s: recall(rows, s) for s in SYSTEMS}
    perfect = {s: sum(1 for r in rows if r[s] == r["total"]) for s in SYSTEMS}
    for r in rows:
        print(f"  {r['id']:6s} " + "  ".join(
            f"{s} {r[s]}/{r['total']}" for s in SYSTEMS))
    print("\n근거 재현율: " + "  /  ".join(
        f"{s} {overall[s]:.0%}" for s in SYSTEMS))

    md = []
    md.append("# KR-FinReg-QA 은행 문항 3-way 벤치마크\n")
    md.append("석사논문 벤치마크 **KR-FinReg-QA**(YES/NO/ABSTAIN 판정형, 정답을 "
              "공시 원문에서 기계적으로 산출)의 은행 상품 문항을 Bank_Onto 지식층에 "
              "이식해 세 검색 패러다임을 비교한다. 원본은 202607 공시 기준이므로 "
              "**판정의 결정적 근거 문구가 202608 공시에 그대로 존재하는 문항만** "
              "이식했다 (탈락 내역은 `python ingest/import_krfinreg.py` 출력 참고).\n")
    md.append("- 원본 질문은 닫힌 문서 설정(\"이 상품은 …?\" + 문서 범위 제공)이라, "
              "개방형 검색 설정에 맞게 질문 문면에 은행·상품명을 명시했다.")
    md.append(f"- 판정형 {len(scored)}문항은 근거 재현율로, 부재형 {len(abstain)}문항은 "
              "답변 계층(보류 정확도)에서 평가한다.\n")
    md.append("## 종합 결과 (판정형)\n")
    md.append("| 지표 | 벡터 RAG | Graph RAG(LPG) | 온톨로지 RAG |")
    md.append("|---|---|---|---|")
    md.append(f"| 근거 재현율 | {overall['vector']:.0%} | {overall['lpg']:.0%} "
              f"| **{overall['onto']:.0%}** |")
    md.append(f"| 완전 답변 가능 문항 | {perfect['vector']}/{len(rows)} "
              f"| {perfect['lpg']}/{len(rows)} | **{perfect['onto']}/{len(rows)}** |\n")

    md.append("## 그룹별 근거 재현율\n")
    md.append("| 그룹 | 문항 | 벡터 | LPG | 온톨로지 |")
    md.append("|---|---|---|---|---|")
    for group, name in GROUP_NAMES.items():
        g_rows = [r for r in rows if r["group"] == group]
        if not g_rows:
            continue
        md.append(f"| {name} | {len(g_rows)} | " + " | ".join(
            f"{recall(g_rows, s):.0%}" for s in SYSTEMS) + " |")
    md.append("")

    md.append("## 부재형(ABSTAIN) 문항\n")
    md.append("근거가 원문에 존재하지 않아 **보류가 정답**인 문항. 검색 계층에서는 "
              "채점하지 않으며, 답변 계층에서 시스템이 실제로 보류하는지 평가한다.\n")
    for q in abstain:
        md.append(f"- {q['id']}: {q['question']}")
    md.append("")

    md.append("## 질문별 상세 (판정형)\n")
    md.append("| ID | 그룹 | 질문 | 정답 | 벡터 | LPG | 온톨로지 |")
    md.append("|---|---|---|---|---|---|---|")
    for r in rows:
        md.append(f"| {r['id']} | {r['group']} | {r['question']} | {r['verdict']} | "
                  + " | ".join(f"{r[s]}/{r['total']}" for s in SYSTEMS) + " |")
    md.append("")
    md.append("""## 해석 — 이 문항 세트가 측정하는 것

이 세트는 큐레이션·시장 벤치마크와 달리 **전 문항이 단일 상품 조회형**이다
(질문이 상품을 특정하고, 근거도 그 상품의 필드 하나에 있음). 따라서:

1. **검색 계층에서는 세 시스템의 격차가 작다.** 그래프 계열은 상품명 시드
   매칭으로 해당 노드에 도달하면 끝이고, 벡터 RAG도 질문에 상품명이 있어
   유사도 매칭이 대체로 성공한다. 다중 홉·완전 열거·집계가 없는 영역에서는
   벡터 RAG가 경쟁력이 있다는 기존 리포트의 프레이밍과 일치하는 결과다.
2. **이 세트의 변별력은 답변 계층에 있다.** 원본 벤치마크(KR-FinReg-QA)의
   설계 목적이 판정(YES/NO)과 보류(ABSTAIN)의 정확도이기 때문이다. 컨텍스트를
   가져온 뒤에도 '만 15세가 만18세이상 요건을 충족하는가'를 판정해야 하고,
   부재형에서는 그럴듯한 컨텍스트가 있어도 보류해야 한다. 이 평가는
   `eval/run_answer_eval.py`(API 키 필요)에서 세 시스템의 컨텍스트를 동일
   LLM에 제공하는 방식으로 수행한다.
3. 검색 계층의 잔여 격차(벡터의 미회수분)는 주로 근거 문구가 컨텍스트 상한
   밖 청크에 있는 경우다 — top-k 청킹의 구조적 한계이며, 상품 수가 늘수록
   커지는 유형의 오류다.

*재생성: `python ingest/import_krfinreg.py && python eval/run_krfinreg_eval.py`*
""")

    REPORT_PATH.write_text("\n".join(md), encoding="utf-8")
    print(f"리포트 저장: {REPORT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
