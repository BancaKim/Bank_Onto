"""RAG 시나리오 매트릭스 답변(생성) 평가 — Bank-Onto-Bench v2.

검색 평가(run_scenario_eval.py)와 같은 문항·같은 시나리오에 대해 **같은 LLM**이
답하게 하고, Bench v2의 answer_type별로 **결정적으로 채점**한다 (LLM 심판 없음).
이로써 논문(Chen et al. 2026)이 지적한 retrieval-generation gap — 검색 지표가
좋아져도 답변이 비례해 좋아지지 않음 — 을 같은 표에서 직접 확인할 수 있다.

시나리오:
- S1~S9: eval/scenarios.py의 결정적 리트리버 + 컨텍스트 예산(기본 4,000자) + 단일 호출
- A1 agentic-basic: LLM이 `search_documents` 도구(S4 색인)를 여러 번 호출하며 계획
- A2 agentic-onto: Bank_Onto 에이전트(온톨로지 조회·SPARQL·규칙 판정 도구)

채점 (answer_type):
- boolean: YES/NO 추출 후 일치      - numeric: 수치 추출 후 동등(허용오차 1e-6)
- span: 정규화 후 포함 일치          - abstain: 보류 표현("해당 정보 없음" 등) 검출
답변 형식을 강제해 파싱 오류를 줄인다: 마지막 줄 "답: <값>".

실행 (ANTHROPIC_API_KEY 또는 `ant auth login` 프로필 필요):
    python eval/run_scenario_answer_eval.py --sample 200            # 층화 표본
    python eval/run_scenario_answer_eval.py --scenarios S1,S6,S9,A2 # 일부만
결과: docs/scenario-answer-report.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic
from anthropic import beta_tool

from agent.bank_agent import answer as onto_agent_answer
from eval.run_bench_v2_eval import gold_strings
from eval.run_scenario_eval import stratified_sample
from eval.scenarios import DEFAULT_BUDGET, ScenarioSuite, assemble, retrieval_metrics
from knowledge.kb import BankKnowledgeBase

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET = REPO_ROOT / "data" / "bank-onto-bench-v2.jsonl"
REPORT = REPO_ROOT / "docs" / "scenario-answer-report.md"
MODEL = "claude-opus-5"
ABSTAIN_TEXT = "공시에 해당 정보 없음"

ANSWER_FORMAT = f"""\
답변 규칙:
- 반드시 마지막 줄을 "답: <값>" 형식으로 끝내세요.
- 예/아니오 질문이면 "답: YES" 또는 "답: NO".
- 수치 질문이면 단위 없이 숫자만 (예: "답: 3.85").
- 조문 위치·용어 등은 그 값만 (예: "답: 제34조").
- 제공된 정보로 답할 수 없으면 반드시 "답: {ABSTAIN_TEXT}"."""

CONTEXT_SYSTEM = f"""\
당신은 은행 상담 챗봇입니다. 아래 제공된 컨텍스트만을 근거로 답하세요.
컨텍스트에 근거가 없으면 지어내지 말고 보류하세요.
{ANSWER_FORMAT}"""

AGENT_BASIC_SYSTEM = f"""\
당신은 은행 상담 에이전트입니다. search_documents 도구로 지식 베이스를 검색해
근거를 모은 뒤 답하세요. 여러 번 검색해도 됩니다(최대 6회). 근거가 없으면 보류하세요.
{ANSWER_FORMAT}"""


# ----------------------------------------------------------------------
# 채점
# ----------------------------------------------------------------------
def final_answer_line(text: str) -> str:
    for line in reversed(text.strip().splitlines()):
        if line.strip().startswith("답:"):
            return line.split(":", 1)[1].strip()
    return text.strip().splitlines()[-1].strip() if text.strip() else ""


def _norm(s: str) -> str:
    return re.sub(r"[\s\"'‘’“”()\[\]·,.]", "", s).lower()


def is_abstain(ans: str) -> bool:
    return any(k in ans for k in ("정보 없음", "알 수 없", "정보가 없", "확인할 수 없",
                                  "해당 정보", "알수없"))


def score(row: dict, ans: str) -> int:
    kind, gold = row["answer_type"], str(row["answer"])
    if kind == "abstain":
        return int(is_abstain(ans))
    if is_abstain(ans):
        return 0
    if kind == "boolean":
        up = ans.upper()
        yes = "YES" in up or up.startswith("예") or "예." in up
        no = "NO" in up or "아니" in up
        return int((gold == "YES" and yes and not no) or (gold == "NO" and no and not yes))
    if kind == "numeric":
        nums = re.findall(r"-?\d[\d,]*\.?\d*", ans)
        try:
            g = float(gold.replace(",", ""))
        except ValueError:
            return int(_norm(gold) in _norm(ans))
        for n in nums:
            try:
                if abs(float(n.replace(",", "")) - g) <= 1e-6 * max(1.0, abs(g)):
                    return 1
            except ValueError:
                continue
        return 0
    return int(_norm(gold) == _norm(ans) or _norm(gold) in _norm(ans))


# ----------------------------------------------------------------------
# 답변 생성
# ----------------------------------------------------------------------
def llm_text(response) -> str:
    if response.stop_reason == "refusal":
        return f"답: {ABSTAIN_TEXT}"
    return "".join(b.text for b in response.content if b.type == "text")


def context_answer(client, context: str, question: str) -> tuple[str, int]:
    resp = client.messages.create(
        model=MODEL, max_tokens=1024, system=CONTEXT_SYSTEM,
        messages=[{"role": "user",
                   "content": f"[컨텍스트]\n{context or '(없음)'}\n\n[질문]\n{question}"}],
    )
    return llm_text(resp), resp.usage.input_tokens + resp.usage.output_tokens


def agentic_basic_answer(client, suite: ScenarioSuite, question: str) -> tuple[str, int]:
    @beta_tool
    def search_documents(query: str) -> str:
        """지식 베이스(개체 문서 + 관계 문서)를 검색해 관련 문서 top-5를 반환한다.
        상품명·은행명·법령명·조문 번호 등 구체적 키워드로 검색하면 정확도가 높다.

        Args:
            query: 검색어.
        """
        return "\n---\n".join(suite.idx_combined.retrieve(query, k=5))

    runner = client.beta.messages.tool_runner(
        model=MODEL, max_tokens=2048, system=AGENT_BASIC_SYSTEM,
        tools=[search_documents], max_iterations=6,
        messages=[{"role": "user", "content": question}],
    )
    final, tokens = None, 0
    for message in runner:
        final = message
        tokens += message.usage.input_tokens + message.usage.output_tokens
    return (llm_text(final) if final else f"답: {ABSTAIN_TEXT}"), tokens


# ----------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=200)
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    parser.add_argument("--scenarios", default="S1,S2,S4,S5,S6,S7,S8,S9,A1,A2")
    args = parser.parse_args()
    wanted = args.scenarios.split(",")

    rows = [json.loads(l) for l in DATASET.read_text().splitlines() if l]
    rows = [r for r in rows if r["template"] != "temporal_validity"]  # abstain 포함
    sample = stratified_sample(rows, args.sample) if args.sample else rows

    client = anthropic.Anthropic()
    kb = BankKnowledgeBase()
    suite = ScenarioSuite(kb)
    print(f"문항 {len(sample)} / 시나리오 {wanted} / 예산 {args.budget}자")

    results: dict[str, list[dict]] = defaultdict(list)
    t0 = time.time()
    for i, row in enumerate(sample, 1):
        q = row["question"]
        gold = gold_strings(row) if row["answer_type"] != "abstain" else []
        for sid in wanted:
            if sid.startswith("S"):
                units = suite.by_id(sid).retrieve(q)
                ctx = assemble(units, args.budget)
                ans, tokens = context_answer(client, ctx, q)
                r4k = retrieval_metrics(units, gold)["recall@4000"] if gold else None
            elif sid == "A1":
                ans, tokens = agentic_basic_answer(client, suite, q)
                r4k = None
            elif sid == "A2":
                ans = onto_agent_answer(f"{q}\n\n{ANSWER_FORMAT}", client)
                tokens, r4k = 0, None
            else:
                continue
            line = final_answer_line(ans)
            results[sid].append({
                "id": row["id"], "template": row["template"],
                "answer_type": row["answer_type"], "gold": row["answer"],
                "answer": line, "correct": score(row, line),
                "tokens": tokens, "recall4k": r4k,
            })
        if i % 10 == 0:
            done = {s: sum(r["correct"] for r in results[s]) / len(results[s]) for s in wanted}
            print(f"  {i}/{len(sample)}  " + "  ".join(f"{s} {v:.0%}" for s, v in done.items())
                  + f"  ({time.time() - t0:.0f}s)")

    # ------------------------------------------------------------------
    def acc(items):
        return sum(r["correct"] for r in items) / len(items) if items else 0.0

    md = ["# RAG 시나리오 매트릭스 — 답변 정확도 (결정적 채점)\n"]
    md.append(f"모델 `{MODEL}` 동일, 컨텍스트 예산 {args.budget:,}자, 문항 {len(sample)}"
              f"{' (템플릿 층화 표본)' if args.sample else ''}. "
              "채점은 `answer_type`별 결정적 규칙 — LLM 심판 없음.\n")
    md.append("## 종합\n")
    md.append("| ID | 정확도 | boolean | numeric | span | **abstain(보류)** | 평균 R@4K | 문항당 토큰 |")
    md.append("|---|---|---|---|---|---|---|---|")
    for sid in wanted:
        items = results[sid]
        by = {k: [r for r in items if r["answer_type"] == k]
              for k in ("boolean", "numeric", "span", "abstain")}
        r4 = [r["recall4k"] for r in items if r["recall4k"] is not None]
        md.append(f"| {sid} | **{acc(items):.0%}** | {acc(by['boolean']):.0%} | {acc(by['numeric']):.0%} "
                  f"| {acc(by['span']):.0%} | {acc(by['abstain']):.0%} "
                  f"| {(sum(r4)/len(r4)) if r4 else float('nan'):.0%} "
                  f"| {sum(r['tokens'] for r in items)/len(items):,.0f} |")
    md.append("")
    md.append("## 템플릿별 정확도\n")
    templates = sorted({r["template"] for r in results[wanted[0]]})
    md.append("| 템플릿 | n | " + " | ".join(wanted) + " |")
    md.append("|---|---|" + "---|" * len(wanted))
    for t in templates:
        n = sum(1 for r in results[wanted[0]] if r["template"] == t)
        md.append(f"| {t} | {n} | " + " | ".join(
            f"{acc([r for r in results[s] if r['template'] == t]):.0%}" for s in wanted) + " |")
    md.append("""
## 읽는 법

- **retrieval-generation gap**: 평균 R@4K(근거가 컨텍스트에 있었던 비율)와 정확도의
  차이. 근거가 있어도 LLM이 계산·집계·판정에서 틀리면 간극이 생긴다 — 논문의
  관찰을 이 표에서 직접 확인한다.
- **abstain 열**이 환각 억제 지표다. 근거 없는 60문항에서 보류하지 않고 값을 말하면 0점.
- A2(온톨로지 에이전트)는 검색이 아니라 SPARQL·규칙 판정으로 값을 *연산*하므로
  집계·계산·판정 템플릿에서 간극이 작아야 한다 — 그것이 온톨로지 RAG의 논지다.

*재생성: `python eval/run_scenario_answer_eval.py --sample N`*
""")
    REPORT.write_text("\n".join(md), encoding="utf-8")
    (REPO_ROOT / "docs" / "scenario-answer-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n리포트 저장: {REPORT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
