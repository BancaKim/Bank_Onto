"""RAG 시나리오 매트릭스 검색 평가 — Bank-Onto-Bench v2 (880 채점 문항).

Chen et al. (2026) "Is GraphRAG Needed?"의 비교 구도를 따라 9개 결정적
시나리오(eval/scenarios.py)를 같은 지식층·같은 질문·같은 채점으로 비교한다.

지표 (검색 계층, LLM 불개입):
- Hit@1: 첫 유닛에 근거 전부 포함 비율
- MRR: 근거가 전부 갖춰지는 최소 랭크의 역수 평균 (다중 문서 근거 대응)
- Recall@B: 컨텍스트 예산 B(2K/4K/8K자)로 잘랐을 때 근거 재현율 — 논문이 지적한
  "컨텍스트 과잉"을 예산 제약으로 드러낸다
- Recall@∞: 예산 없음 (기존 bench-v2-report 수치와 대응)
- 평균 컨텍스트 크기(자)

실행: python eval/run_scenario_eval.py [--sample N]   (API 키 불필요)
결과: docs/scenario-report.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.run_bench_v2_eval import gold_strings
from eval.scenarios import BUDGETS, ScenarioSuite, retrieval_metrics
from knowledge.kb import BankKnowledgeBase

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET = REPO_ROOT / "data" / "bank-onto-bench-v2.jsonl"
REPORT = REPO_ROOT / "docs" / "scenario-report.md"
METRICS = ["hit1", "mrr"] + [f"recall@{b}" for b in BUDGETS] + ["recall@inf", "chars"]


def stratified_sample(rows: list[dict], n: int) -> list[dict]:
    """템플릿별 균등 층화 표본 (결정적: 각 템플릿의 앞에서부터)."""
    by_t = defaultdict(list)
    for r in rows:
        by_t[r["template"]].append(r)
    per = max(1, n // len(by_t))
    out = []
    for t in sorted(by_t):
        out += by_t[t][:per]
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=0,
                        help="템플릿 층화 표본 크기 (0 = 전체)")
    args = parser.parse_args()

    rows = [json.loads(l) for l in DATASET.read_text().splitlines() if l]
    scored = [r for r in rows if r["answer_type"] != "abstain"
              and r["template"] != "temporal_validity"]
    if args.sample:
        scored = stratified_sample(scored, args.sample)

    t0 = time.time()
    kb = BankKnowledgeBase()
    suite = ScenarioSuite(kb)
    print(f"지식층 {suite.sizes} — 색인 {time.time() - t0:.0f}s / 채점 문항 {len(scored)}")

    per_scenario: dict[str, list[dict]] = {s.id: [] for s in suite.scenarios}
    for s in suite.scenarios:
        t = time.time()
        for row in scored:
            m = retrieval_metrics(s.retrieve(row["question"]), gold_strings(row))
            m["template"] = row["template"]
            m["qtype"] = row["qtype"]
            per_scenario[s.id].append(m)
        avg = {k: sum(m[k] for m in per_scenario[s.id]) / len(scored) for k in METRICS}
        print(f"  {s.id} {s.name:16s} hit@1 {avg['hit1']:.2f}  mrr {avg['mrr']:.2f}  "
              f"r@4k {avg['recall@4000']:.2f}  r@inf {avg['recall@inf']:.2f}  "
              f"{avg['chars']:8,.0f}자  ({time.time() - t:.0f}s)")

    def avg_of(items, key):
        return sum(m[key] for m in items) / len(items) if items else 0.0

    md = ["# RAG 시나리오 매트릭스 — Bank-Onto-Bench v2 검색 평가\n"]
    md.append("Chen et al. (2026) *Is GraphRAG Needed? From Basic RAG to Graph-/Agentic "
              "Solutions with Context Optimization* (ACL 2026 GEM)의 9-시나리오 비교 구도를 "
              "Bank_Onto 지식층에 이식했다. 모든 시나리오는 **같은 KB**(온톨로지 + 금감원 공시 "
              "202608 + 법령 7종 조문)에서 파생된 표현(텍스트 청크 / 속성 그래프 / 온톨로지)을 "
              "쓰고, **같은 880문항**을 **같은 결정적 근거 문자열**로 채점한다. LLM은 관여하지 "
              "않는다 (에이전틱 시나리오와 답변 계층은 `run_scenario_answer_eval.py`).\n")
    if args.sample:
        md.append(f"> ⚠️ 템플릿 층화 표본 {len(scored)}문항 기준. 전체는 `--sample 0`.\n")
    md.append(f"- 지식층: 트리플 {suite.sizes['triples']:,} / 청크 {suite.sizes['chunks']:,} / "
              f"개체 문서 {suite.sizes['entity_docs']:,} / 관계 문서 {suite.sizes['relation_docs']:,} / "
              f"LPG 노드 {suite.sizes['lpg_nodes']:,}·엣지 {suite.sizes['lpg_edges']:,}")
    md.append("- 컨텍스트 예산은 문자 수 기준 (한국어 ≈ 0.5~0.7 토큰/자). 4,000자가 기본 비교점.\n")

    md.append("## 시나리오\n")
    md.append("| ID | 이름 | 계열 | 구성 |")
    md.append("|---|---|---|---|")
    for s in suite.scenarios:
        md.append(f"| {s.id} | {s.name} | {s.family} | {s.description} |")
    md.append("")

    md.append("## 종합 결과\n")
    md.append("| ID | 시나리오 | Hit@1 | MRR | R@2K | **R@4K** | R@8K | R@∞ | 평균 컨텍스트 |")
    md.append("|---|---|---|---|---|---|---|---|---|")
    for s in suite.scenarios:
        items = per_scenario[s.id]
        md.append(f"| {s.id} | {s.name} | {avg_of(items, 'hit1'):.2f} | {avg_of(items, 'mrr'):.2f} "
                  f"| {avg_of(items, 'recall@2000'):.0%} | **{avg_of(items, 'recall@4000'):.0%}** "
                  f"| {avg_of(items, 'recall@8000'):.0%} | {avg_of(items, 'recall@inf'):.0%} "
                  f"| {avg_of(items, 'chars'):,.0f}자 |")
    md.append("")

    md.append("## 템플릿별 Recall@4K\n")
    templates = sorted({m["template"] for m in per_scenario["S1"]},
                       key=lambda t: -sum(1 for m in per_scenario["S1"] if m["template"] == t))
    md.append("| 템플릿 | n | " + " | ".join(s.id for s in suite.scenarios) + " |")
    md.append("|---|---|" + "---|" * len(suite.scenarios))
    for t in templates:
        n = sum(1 for m in per_scenario["S1"] if m["template"] == t)
        cells = []
        for s in suite.scenarios:
            items = [m for m in per_scenario[s.id] if m["template"] == t]
            cells.append(f"{avg_of(items, 'recall@4000'):.0%}")
        md.append(f"| {t} | {n} | " + " | ".join(cells) + " |")
    md.append("")

    md.append("## 유형별 Recall@4K / Recall@∞\n")
    md.append("| 유형 | " + " | ".join(s.id for s in suite.scenarios) + " |")
    md.append("|---|" + "---|" * len(suite.scenarios))
    for qtype in ("공시형", "규정형"):
        cells = []
        for s in suite.scenarios:
            items = [m for m in per_scenario[s.id] if m["qtype"] == qtype]
            cells.append(f"{avg_of(items, 'recall@4000'):.0%} / {avg_of(items, 'recall@inf'):.0%}")
        md.append(f"| {qtype} | " + " | ".join(cells) + " |")
    md.append("")

    md.append("""## 읽는 법

- **R@∞ vs R@4K의 간극**이 논문이 말한 "컨텍스트 과잉"이다. 그래프·온톨로지 계열은
  예산이 없으면 근거를 거의 다 가져오지만, 실제 LLM 컨텍스트 예산 안에서는 관련
  없는 이웃·클래스 계층이 근거를 밀어낸다. 컨텍스트 엔지니어링(S8/S9)이 이 간극을
  얼마나 메우는지가 핵심 관찰점이다.
- **Hit@1·MRR**은 "필요한 근거가 얼마나 앞에 오는가"다. 다중 문서 근거(집계·비교)는
  한 유닛에 다 들어갈 수 없어 Hit@1이 구조적으로 낮다 — R@B와 함께 봐야 한다.
- 검색 지표가 높다고 답이 맞는 것은 아니다(논문의 retrieval-generation gap).
  답변 정확도는 `run_scenario_answer_eval.py`가 같은 문항을 `answer_type`별로
  결정적 채점해 산출한다 (API 키 필요).

## 공정성·한계

- 기본 RAG 계열(S1~S4)은 재현성을 위해 어휘적 TF-IDF를 쓴다. 의미 임베딩으로 교체
  가능하나(`TfidfVectorRetriever` 인터페이스만 맞추면 됨), 다중 문서 종합·집계의
  실패는 top-k 청킹 패러다임의 한계라 임베딩 품질로 해소되지 않는다.
- 논문의 "계산된 KG"(LLM이 텍스트에서 추출한 그래프)와 에이전틱 시나리오는 LLM이
  필요해 이 결정적 평가에 넣지 않았다. 에이전틱은 답변 하네스에서 A1/A2로 비교한다.
- 시간형 60문항(법령 개정 이력 필요)과 abstain 60문항은 제외 — 각각 로드맵과
  답변 계층 소관.

*재생성: `python eval/run_scenario_eval.py`*
""")
    REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"\n리포트 저장: {REPORT.relative_to(REPO_ROOT)}  (총 {time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
