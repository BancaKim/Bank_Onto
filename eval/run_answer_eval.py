"""답변(생성) 수준 3-way 비교: 벡터 RAG vs Graph RAG(LPG) vs 온톨로지 RAG.

세 파이프라인 모두 같은 LLM(claude-opus-5)으로 답변을 생성하며,
컨텍스트 공급 방식만 다르다:
- 벡터 RAG:    TF-IDF top-5 청크 → 단일 호출
- Graph RAG:   LPG k-hop 서브그래프 → 단일 호출
- 온톨로지 RAG: 에이전트가 온톨로지 도구(SPARQL 포함)를 직접 호출

채점 방식 3종 (--scoring 으로 선택, 기본 all):
- mcq:  4지선다 객관식 정확도 — 완전히 결정적, 심판 편향 없음
- judge: 자유 답변을 LLM 심판이 모범답안 대비 0~2점 채점
- sim:  자유 답변과 모범답안의 TF-IDF 코사인 유사도 (보조 지표, 오프라인 계산)

실행 (ANTHROPIC_API_KEY 또는 `ant auth login` 프로필 필요):
    python eval/run_answer_eval.py                # 전체
    python eval/run_answer_eval.py --scoring mcq  # 객관식만
결과: docs/answer-eval-report.md
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic

from agent.bank_agent import answer as agent_answer
from eval.benchmark_questions import NEGATIVE_QUESTIONS, QUESTIONS
from eval.corpus import build_documents, chunk_corpus
from eval.lpg_rag import LpgGraphRetriever
from eval.mcq_questions import MCQ_NEGATIVE, MCQ_QUESTIONS
from eval.vector_rag import TfidfVectorRetriever, char_ngrams
from knowledge.kb import BankKnowledgeBase

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "docs" / "answer-eval-report.md"
MODEL = "claude-opus-5"
SYSTEMS = ["vector", "lpg", "onto"]
SYSTEM_NAMES = {"vector": "벡터 RAG", "lpg": "Graph RAG(LPG)", "onto": "온톨로지 RAG"}

CONTEXT_SYSTEM = """\
당신은 은행 상담 챗봇입니다. 아래 제공된 컨텍스트만을 근거로 답하세요.
컨텍스트에 근거가 없으면 반드시 "제공된 정보로는 알 수 없습니다"라고 답하세요."""

JUDGE_SYSTEM = """\
당신은 QA 채점자입니다. 질문, 모범답안, 시스템 답변을 보고 0~2점으로 채점하세요.
- 2: 모범답안의 핵심 내용을 정확하고 완전하게 담음
- 1: 부분적으로 정답 (일부 항목 누락 또는 부정확)
- 0: 오답이거나, 근거 없는 내용을 지어냄(환각)
모범답안이 "모른다고 답해야 함"인 경우: 모른다고 답하면 2, 지어내면 0.
숫자 하나만 출력하세요."""


def llm_text(response) -> str:
    if response.stop_reason == "refusal":
        return "(거부됨)"
    return "".join(b.text for b in response.content if b.type == "text")


def context_answer(client, context: str, prompt: str) -> str:
    return llm_text(client.messages.create(
        model=MODEL, max_tokens=1024, system=CONTEXT_SYSTEM,
        messages=[{"role": "user",
                   "content": f"[컨텍스트]\n{context}\n\n{prompt}"}],
    ))


def tfidf_similarity(a: str, b: str) -> float:
    ga, gb = char_ngrams(a), char_ngrams(b)
    dot = sum(ga[k] * gb[k] for k in ga if k in gb)
    na = math.sqrt(sum(v * v for v in ga.values())) or 1.0
    nb = math.sqrt(sum(v * v for v in gb.values())) or 1.0
    return dot / (na * nb)


def judge(client, question: str, gold: str, system_answer: str) -> int:
    text = llm_text(client.messages.create(
        model=MODEL, max_tokens=8, system=JUDGE_SYSTEM,
        messages=[{"role": "user",
                   "content": (f"[질문]\n{question}\n\n[모범답안]\n{gold}\n\n"
                               f"[시스템 답변]\n{system_answer}\n\n점수:")}],
    )).strip()
    for ch in text:
        if ch in "012":
            return int(ch)
    return 0


def get_answers(client, retrievers, question_text: str, prompt: str) -> dict[str, str]:
    """세 시스템의 답변을 생성한다. prompt는 질문(+객관식 보기)을 포함."""
    return {
        "vector": context_answer(client, retrievers["vector"](question_text), prompt),
        "lpg": context_answer(client, retrievers["lpg"](question_text), prompt),
        "onto": agent_answer(prompt, client),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scoring", choices=["mcq", "free", "all"], default="all")
    args = parser.parse_args()

    client = anthropic.Anthropic()
    kb = BankKnowledgeBase()
    vector = TfidfVectorRetriever(chunk_corpus(build_documents(kb)))
    lpg = LpgGraphRetriever(kb)
    retrievers = {
        "vector": lambda q: vector.retrieve_context(q, k=5),
        "lpg": lambda q: lpg.retrieve_context(q),
    }

    md = ["# 답변 수준 3-way 비교 (동일 LLM, 컨텍스트 공급 방식만 상이)\n",
          f"모델: `{MODEL}` (3개 시스템 동일)\n"]

    # ------------------------------------------------------------------
    # 1) 객관식 (MCQ) — 결정적 채점
    # ------------------------------------------------------------------
    if args.scoring in ("mcq", "all"):
        letters = "ABCD"
        mcq_rows = []
        for q in MCQ_QUESTIONS + MCQ_NEGATIVE:
            options = "\n".join(f"{letters[i]}. {o}" for i, o in enumerate(q["options"]))
            prompt = (f"[질문]\n{q['question']}\n\n[보기]\n{options}\n\n"
                      "정답 보기의 알파벳 하나만 출력하세요.")
            answers = get_answers(client, retrievers, q["question"], prompt)
            row = {"id": q["id"], "question": q["question"]}
            for s in SYSTEMS:
                picked = next((c for c in answers[s].strip().upper() if c in letters), "?")
                row[s] = int(picked == letters[q["answer"]])
            mcq_rows.append(row)
            print(f"[MCQ {q['id']}] " + "  ".join(f"{s} {'O' if row[s] else 'X'}"
                                                  for s in SYSTEMS))
        md.append("## 객관식 정확도 (결정적 채점)\n")
        md.append("| 시스템 | 정확도 |")
        md.append("|---|---|")
        for s in SYSTEMS:
            correct = sum(r[s] for r in mcq_rows)
            md.append(f"| {SYSTEM_NAMES[s]} | {correct}/{len(mcq_rows)} "
                      f"({correct/len(mcq_rows):.0%}) |")
        md.append("\n| ID | 벡터 | LPG | 온톨로지 |")
        md.append("|---|---|---|---|")
        for r in mcq_rows:
            md.append(f"| {r['id']} | " + " | ".join(
                "O" if r[s] else "X" for s in SYSTEMS) + " |")
        md.append("")

    # ------------------------------------------------------------------
    # 2) 자유 답변 — LLM 심판 + TF-IDF 유사도
    # ------------------------------------------------------------------
    if args.scoring in ("free", "all"):
        free_rows = []
        for q in QUESTIONS + NEGATIVE_QUESTIONS:
            answers = get_answers(client, retrievers, q["question"],
                                  f"[질문]\n{q['question']}")
            row = {"id": q["id"], "question": q["question"], "answers": answers}
            for s in SYSTEMS:
                row[f"{s}_judge"] = judge(client, q["question"], q["answer"], answers[s])
                row[f"{s}_sim"] = tfidf_similarity(answers[s], q["answer"])
            free_rows.append(row)
            print(f"[FREE {q['id']}] " + "  ".join(
                f"{s} {row[f'{s}_judge']}/2" for s in SYSTEMS))
        n = len(free_rows)
        md.append("## 자유 답변 — LLM 심판(0~2) + 유사도(보조)\n")
        md.append("| 시스템 | 심판 총점 | 평균 유사도 |")
        md.append("|---|---|---|")
        for s in SYSTEMS:
            total = sum(r[f"{s}_judge"] for r in free_rows)
            sim = sum(r[f"{s}_sim"] for r in free_rows) / n
            md.append(f"| {SYSTEM_NAMES[s]} | {total}/{2*n} ({total/(2*n):.0%}) "
                      f"| {sim:.2f} |")
        md.append("\n### 답변 전문\n")
        for r in free_rows:
            md.append(f"#### {r['id']}: {r['question']}\n")
            for s in SYSTEMS:
                md.append(f"**{SYSTEM_NAMES[s]} ({r[f'{s}_judge']}/2)**:\n"
                          f"> {r['answers'][s]}\n")

    REPORT_PATH.write_text("\n".join(md), encoding="utf-8")
    print(f"\n리포트 저장: {REPORT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
