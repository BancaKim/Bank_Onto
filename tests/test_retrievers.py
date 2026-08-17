#!/usr/bin/env python3
"""리트리버 회귀 테스트 (API 키 불필요).

검증 항목:
1. 그래프·LPG 리트리버가 프로세스 해시 시드와 무관하게 결정적으로 동작
2. 다중 홉 질문(HOP-3)의 근거가 시드 노이즈(실데이터 상품명)에 밀려나지 않음
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_CONTEXT_SNIPPET = r"""
import hashlib
from knowledge.kb import BankKnowledgeBase
from eval.graph_rag import GraphRetriever
from eval.lpg_rag import LpgGraphRetriever

kb = BankKnowledgeBase()
questions = [
    "김민준이 가입한 정기예금 상품의 금리는 몇 %야?",
    "주택담보대출 상품에는 어떤 것들이 있어?",
    "예금자보호가 적용되는 상품은 어떤 거야?",
]
for retriever in (GraphRetriever(kb), LpgGraphRetriever(kb)):
    for q in questions:
        digest = hashlib.sha256(retriever.retrieve_context(q).encode()).hexdigest()
        print(f"{type(retriever).__name__}:{digest}")
"""


def _run_with_hash_seed(seed: str) -> str:
    env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=str(REPO_ROOT))
    result = subprocess.run(
        [sys.executable, "-c", _CONTEXT_SNIPPET],
        capture_output=True, text=True, env=env, cwd=REPO_ROOT, check=True,
    )
    return result.stdout


def test_retrievers_deterministic_across_hash_seeds():
    out_a = _run_with_hash_seed("0")
    out_b = _run_with_hash_seed("1")
    assert out_a == out_b, (
        "리트리버 컨텍스트가 PYTHONHASHSEED에 따라 달라짐 (비결정적):\n"
        f"seed=0:\n{out_a}\nseed=1:\n{out_b}"
    )


def test_graph_retriever_multihop_survives_seed_noise():
    from knowledge.kb import BankKnowledgeBase
    from eval.graph_rag import GraphRetriever

    kb = BankKnowledgeBase()
    retriever = GraphRetriever(kb)
    context = retriever.retrieve_context("김민준이 가입한 정기예금 상품의 금리는 몇 %야?")
    assert "3.50" in context, (
        "HOP-3 근거(정기예금 금리 3.50)가 컨텍스트에 없음 — "
        "시장 데이터 시드가 BFS 예산을 잠식했을 가능성"
    )


def test_market_eval_gold_excludes_example_fixtures():
    """시장 벤치마크의 정답은 금감원 공시 데이터에서만 나와야 한다.

    examples/의 가상 시나리오 상품(한빛 정기예금 등)이 '공시된 상품' 집계에
    섞이면 실데이터 리포트의 신뢰성이 깨진다.
    """
    from knowledge.kb import BankKnowledgeBase
    from eval.run_market_eval import build_market_questions

    kb = BankKnowledgeBase()
    for question in build_market_questions(kb):
        assert "한빛 정기예금" not in question["gold"], (
            f"{question['id']}: 예시 픽스처 상품이 gold에 포함됨"
        )


def main() -> int:
    tests = [
        test_retrievers_deterministic_across_hash_seeds,
        test_graph_retriever_multihop_survives_seed_noise,
        test_market_eval_gold_excludes_example_fixtures,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  [PASS] {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  [FAIL] {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
