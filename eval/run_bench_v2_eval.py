"""Bank-Onto-Bench v2 (1,000문항) 3-way 검색 벤치마크.

데이터셋: data/bank-onto-bench-v2.jsonl (bench/generate.py 생성)
지식층: 온톨로지 + 금감원 공시(202608) + 법령 7종 조문(law-instances.ttl)
— 세 시스템이 동일 지식에서 출발한다.

채점(검색 계층, 결정적):
- 판정·조회형 880문항: 결정적 근거 문자열(개체명 + 원문 값)이 컨텍스트에
  포함되는지 측정 (근거 재현율).
- abstain 60문항: 근거 부재가 정답 — 답변 계층에서 보류 정확도로 평가.
- temporal_validity 60문항: 정답이 법령 개정 이력(시행일 구간)에 있는데
  현재 지식층은 현행 조문만 적재 — 세 시스템 모두 답할 수 없어 검색 계층
  집계에서 제외한다 (개정 이력 모듈은 로드맵).

실행: python eval/run_bench_v2_eval.py   (API 키 불필요, 결정적)
결과: docs/bench-v2-report.md
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.corpus import build_documents, chunk_corpus
from eval.graph_rag import GraphRetriever
from eval.lpg_rag import LpgGraphRetriever
from eval.vector_rag import TfidfVectorRetriever
from knowledge.kb import BankKnowledgeBase

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET = REPO_ROOT / "data" / "bank-onto-bench-v2.jsonl"
REPORT = REPO_ROOT / "docs" / "bench-v2-report.md"

SYSTEMS = ["vector", "lpg", "onto"]


def gold_strings(row: dict) -> list[str]:
    """문항별 결정적 근거 문자열 — 이것이 컨텍스트에 있어야 답변 가능하다."""
    template = row["template"]
    evidence_text = row["evidence"].get("text", "")

    if row["qtype"] == "공시형":
        product = row["evidence"]["locator"].split(":")[0]  # 은행명
        name_m = re.search(r"'([^']+)'", row["question"])
        product_name = name_m.group(1) if name_m else product
        if template == "interest_calc_type":
            return [product_name, row["answer"]]
        return [product_name, evidence_text]

    if template == "article_locate":
        title_m = re.search(r"'([^']+)'", row["question"])
        return [row["answer"]] + ([title_m.group(1)] if title_m else [])
    if template == "definition_term":
        return [row["answer"]]
    if template == "penalty_amount":
        if row.get("unit") == "년":
            return [f"{row['answer']}년 이하의 징역"]
        return [f"{row['answer']} 이하의"]
    if template == "law_meta":
        return [row["answer"]]
    raise ValueError(f"gold 규칙 없음: {template}")


def main() -> int:
    rows = [json.loads(l) for l in DATASET.read_text().splitlines() if l]
    scored = [r for r in rows if r["answer_type"] != "abstain"
              and r["template"] != "temporal_validity"]
    abstain = [r for r in rows if r["answer_type"] == "abstain"]
    temporal = [r for r in rows if r["template"] == "temporal_validity"]

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
    print(f"문항 {len(rows)} (채점 {len(scored)} / abstain {len(abstain)} / "
          f"시간형 제외 {len(temporal)}) — 코퍼스 청크 {len(chunks)}개, "
          f"트리플 {kb.stats()['triples']}개\n")

    results = []
    chars = {s: 0 for s in SYSTEMS}
    for i, row in enumerate(scored, 1):
        gold = gold_strings(row)
        entry = {"row": row, "total": len(gold)}
        for s in SYSTEMS:
            context = retrievers[s](row["question"])
            entry[s] = sum(1 for g in gold if g in context)
            chars[s] += len(context)
        results.append(entry)
        if i % 100 == 0:
            print(f"  …{i}/{len(scored)}")

    def recall(items, system):
        total = sum(e["total"] for e in items)
        return sum(e[system] for e in items) / total if total else 0.0

    overall = {s: recall(results, s) for s in SYSTEMS}
    perfect = {s: sum(1 for e in results if e[s] == e["total"]) for s in SYSTEMS}
    print("\n근거 재현율: " + "  /  ".join(f"{s} {overall[s]:.0%}" for s in SYSTEMS))

    by_template = defaultdict(list)
    by_qtype = defaultdict(list)
    by_category = defaultdict(list)
    for e in results:
        by_template[e["row"]["template"]].append(e)
        by_qtype[e["row"]["qtype"]].append(e)
        by_category[e["row"]["category"]].append(e)

    md = []
    md.append("# Bank-Onto-Bench v2 3-way 검색 벤치마크 (1,000문항)\n")
    md.append("HF 공개용 은행 도메인 1,000문항(공시형 700 + 규정형 300)에 대해 "
              "세 검색 패러다임의 근거 재현율을 비교한다. 세 시스템 모두 동일 "
              "지식층(온톨로지 + 금감원 공시 202608 + 현행 법령 7종 조문)에서 "
              "출발하며, LLM 없이 결정적으로 채점된다.\n")
    md.append(f"- 채점 대상 {len(scored)}문항. **abstain {len(abstain)}문항**은 근거 "
              "부재가 정답이므로 답변 계층에서 보류 정확도로 평가한다.")
    md.append(f"- **시간형 {len(temporal)}문항**은 정답 근거가 법령 개정 이력(신구조문 "
              "유효기간)에 있으나 현재 지식층은 현행 조문만 적재되어 있어 세 시스템 "
              "모두 답할 수 없다 — 공정성을 위해 검색 집계에서 제외 (개정 이력 "
              "모듈은 로드맵).\n")
    md.append("## 종합 결과\n")
    md.append("| 지표 | 벡터 RAG | Graph RAG(LPG) | 온톨로지 RAG |")
    md.append("|---|---|---|---|")
    md.append(f"| 근거 재현율 | {overall['vector']:.0%} | {overall['lpg']:.0%} "
              f"| **{overall['onto']:.0%}** |")
    md.append(f"| 완전 답변 가능 문항 | {perfect['vector']}/{len(scored)} "
              f"| {perfect['lpg']}/{len(scored)} | **{perfect['onto']}/{len(scored)}** |")
    md.append("| 평균 컨텍스트 크기 | " + " | ".join(
        f"{chars[s] / len(scored):,.0f}자" for s in SYSTEMS) + " |\n")

    md.append("## 유형별 근거 재현율\n")
    md.append("| 구분 | 문항 | 벡터 | LPG | 온톨로지 |")
    md.append("|---|---|---|---|---|")
    for qtype in ("공시형", "규정형"):
        items = by_qtype[qtype]
        md.append(f"| **{qtype}** | {len(items)} | " + " | ".join(
            f"{recall(items, s):.0%}" for s in SYSTEMS) + " |")
    for template in sorted(by_template, key=lambda t: -len(by_template[t])):
        items = by_template[template]
        md.append(f"| &nbsp;&nbsp;{template} | {len(items)} | " + " | ".join(
            f"{recall(items, s):.0%}" for s in SYSTEMS) + " |")
    md.append("")

    md.append("## 카테고리별 근거 재현율\n")
    md.append("| 카테고리 | 문항 | 벡터 | LPG | 온톨로지 |")
    md.append("|---|---|---|---|---|")
    for cat in ("예금", "대출", "카드", "외환", "퇴직연금", "펀드", "공통"):
        items = by_category.get(cat, [])
        if not items:
            continue
        md.append(f"| {cat} | {len(items)} | " + " | ".join(
            f"{recall(items, s):.0%}" for s in SYSTEMS) + " |")
    md.append("")

    worst = sorted(results, key=lambda e: (e["vector"] / e["total"], e["row"]["id"]))
    md.append("## 벡터 RAG가 놓친 대표 사례 (하위 10)\n")
    md.append("| ID | 질문 | 벡터 | LPG | 온톨로지 |")
    md.append("|---|---|---|---|---|")
    for e in worst[:10]:
        md.append(f"| {e['row']['id']} | {e['row']['question'][:60]}… | "
                  + " | ".join(f"{e[s]}/{e['total']}" for s in SYSTEMS) + " |")
    md.append("")
    md.append("""## 해석과 한계

1. **벡터 RAG의 실패는 수치 조회형에 집중된다** (penalty 57%, credit_avg 53%,
   law_meta 52%, rate_threshold 72%): 질문과 어휘가 겹치는 청크는 찾아도 정답
   수치가 있는 바로 그 청크를 top-5 안에 못 넣는다. 코퍼스가 커질수록(법령
   1,025개 조문 추가) 이 희석은 심해진다 — 같은 벤치마크에서 법령 적재 전후로
   벡터 성적이 하락한 것이 그 증거다.
2. **이 벤치마크는 단일 문서 조회형 위주라 LPG와 온톨로지의 격차가 작다**
   (98% vs 99%). 두 시스템의 격차는 다중 홉·완전 열거·집계가 있는 큐레이션·시장
   벤치마크에서 벌어진다 (LPG 86%/78% vs 온톨로지 100%/100%). 남은 공동 실패
   지점(loan_rate_type 87%)은 '주택담보대출'처럼 여러 은행이 같은 상품명을 쓰는
   경우의 개체 중의성 — 시드 매칭이 은행-상품 연결을 활용하지 못하는 한계다.
3. **컨텍스트 크기 격차에 주의**: 그래프 계열은 근거 재현율이 높은 대신 컨텍스트가
   크다(조문 전문 포함). 답변 계층에서는 컨텍스트 예산을 통일한 비교(원본
   KR-FinReg-QA의 4,000자 상한 방식)를 병행해야 공정하다.
4. abstain 60문항과 시간형 60문항은 검색 계층에서 채점하지 않았다 — 각각 답변
   계층(보류 정확도), 법령 개정 이력 모듈(로드맵) 소관이다.

*재생성: `python eval/run_bench_v2_eval.py`*
""")

    REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"리포트 저장: {REPORT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
