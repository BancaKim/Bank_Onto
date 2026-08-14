"""End-to-end 답변 품질 비교: 온톨로지 RAG vs 벡터 RAG.

두 파이프라인 모두 같은 LLM(claude-opus-5)으로 최종 답변을 생성하되,
컨텍스트 공급 방식만 다르다:
- 벡터 RAG: TF-IDF top-5 청크를 컨텍스트로 주고 단일 호출로 답변
- 온톨로지 RAG: 에이전트가 온톨로지 도구를 직접 호출하며 답변 (agent/bank_agent.py)

각 답변은 LLM 심판(judge)이 모범답안 대비 0~2점으로 채점한다:
  2 = 정확하고 완전, 1 = 부분 정답, 0 = 오답/환각.
NEG 질문은 "모른다"고 답하면 2점, 지어내면 0점.

실행 (ANTHROPIC_API_KEY 또는 `ant auth login` 프로필 필요):
    python eval/run_e2e.py
결과: docs/benchmark-e2e-report.md
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic

from agent.bank_agent import answer as agent_answer
from eval.benchmark_questions import NEGATIVE_QUESTIONS, QUESTIONS
from eval.corpus import build_documents, chunk_corpus
from eval.vector_rag import TfidfVectorRetriever
from knowledge.kb import BankKnowledgeBase

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "docs" / "benchmark-e2e-report.md"
MODEL = "claude-opus-5"

VECTOR_RAG_SYSTEM = """\
당신은 은행 상담 챗봇입니다. 아래 제공된 컨텍스트만을 근거로 답하세요.
컨텍스트에 근거가 없으면 반드시 "제공된 정보로는 알 수 없습니다"라고 답하세요."""

JUDGE_SYSTEM = """\
당신은 QA 채점자입니다. 질문, 모범답안, 시스템 답변을 보고 0~2점으로 채점하세요.
- 2: 모범답안의 핵심 내용을 정확하고 완전하게 담음
- 1: 부분적으로 정답 (일부 항목 누락 또는 부정확)
- 0: 오답이거나, 근거 없는 내용을 지어냄(환각)
모범답안이 "모른다고 답해야 함"인 경우: 모른다고 답하면 2, 지어내면 0.
숫자 하나만 출력하세요."""


def vector_rag_answer(client: anthropic.Anthropic, retriever: TfidfVectorRetriever,
                      question: str) -> str:
    context = retriever.retrieve_context(question, k=5)
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=VECTOR_RAG_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"[컨텍스트]\n{context}\n\n[질문]\n{question}",
        }],
    )
    if response.stop_reason == "refusal":
        return "(거부됨)"
    return "".join(b.text for b in response.content if b.type == "text")


def judge(client: anthropic.Anthropic, question: str, gold_answer: str,
          system_answer: str) -> int:
    response = client.messages.create(
        model=MODEL,
        max_tokens=8,
        system=JUDGE_SYSTEM,
        messages=[{
            "role": "user",
            "content": (f"[질문]\n{question}\n\n[모범답안]\n{gold_answer}\n\n"
                        f"[시스템 답변]\n{system_answer}\n\n점수:"),
        }],
    )
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    for ch in text:
        if ch in "012":
            return int(ch)
    return 0


def main() -> int:
    client = anthropic.Anthropic()
    kb = BankKnowledgeBase()
    retriever = TfidfVectorRetriever(chunk_corpus(build_documents(kb)))

    all_questions = QUESTIONS + NEGATIVE_QUESTIONS
    rows = []
    for q in all_questions:
        print(f"[{q['id']}] {q['question']}")
        v_answer = vector_rag_answer(client, retriever, q["question"])
        g_answer = agent_answer(q["question"], client)
        v_score = judge(client, q["question"], q["answer"], v_answer)
        g_score = judge(client, q["question"], q["answer"], g_answer)
        print(f"    vector {v_score}/2   graph {g_score}/2")
        rows.append({**q, "vector_answer": v_answer, "graph_answer": g_answer,
                     "vector_score": v_score, "graph_score": g_score})

    v_total = sum(r["vector_score"] for r in rows)
    g_total = sum(r["graph_score"] for r in rows)
    max_total = 2 * len(rows)

    md = ["# E2E 답변 품질 비교 (LLM 채점)\n"]
    md.append(f"모델: `{MODEL}` (양쪽 동일) / 심판: LLM 채점 0~2점\n")
    md.append("| 지표 | 벡터 RAG | 온톨로지 RAG |")
    md.append("|---|---|---|")
    md.append(f"| 총점 | {v_total}/{max_total} ({v_total/max_total:.0%}) "
              f"| **{g_total}/{max_total} ({g_total/max_total:.0%})** |\n")
    md.append("## 질문별 결과\n")
    md.append("| ID | 질문 | 벡터 | 그래프 |")
    md.append("|---|---|---|---|")
    for r in rows:
        md.append(f"| {r['id']} | {r['question']} | {r['vector_score']}/2 | {r['graph_score']}/2 |")
    md.append("\n## 답변 전문\n")
    for r in rows:
        md.append(f"### {r['id']}: {r['question']}\n")
        md.append(f"**모범답안**: {r['answer']}\n")
        md.append(f"**벡터 RAG ({r['vector_score']}/2)**:\n> {r['vector_answer']}\n")
        md.append(f"**온톨로지 RAG ({r['graph_score']}/2)**:\n> {r['graph_answer']}\n")

    REPORT_PATH.write_text("\n".join(md), encoding="utf-8")
    print(f"\n총점: vector {v_total}/{max_total}  /  graph {g_total}/{max_total}")
    print(f"리포트 저장: {REPORT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
