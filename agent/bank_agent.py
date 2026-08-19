"""온톨로지 knowledge layer를 사용하는 은행 상담 에이전트.

Anthropic SDK의 tool runner가 에이전트 루프(도구 호출 → 실행 → 결과 반환)를
자동으로 처리한다. 지식은 knowledge/ 패키지의 온톨로지 도구를 통해 조회한다.

사용법:
    export ANTHROPIC_API_KEY=...   # 또는 `ant auth login` 프로필
    python agent/bank_agent.py "주택담보대출 받으려면 어떤 규제비율이 적용되나요?"
    python agent/bank_agent.py            # 대화형 모드
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic

from knowledge.tools import BANK_KB_TOOLS, get_kb

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """\
당신은 은행 업무 전문 상담 에이전트입니다.

당신의 지식 기반은 FIBO 스타일로 구축된 은행권 온톨로지입니다. 은행 개념(상품, 계좌, \
여신, 규제 등)에 대한 답변은 반드시 온톨로지 도구로 조회한 내용에 근거해야 합니다. \
온톨로지에 없는 내용은 일반 지식임을 명시하고, 온톨로지에서 확인한 내용과 구분하세요.

도구 사용 지침:
- 용어의 의미·정의를 물으면 get_concept_details를 사용하세요. 개념 이름이 불확실하면 \
search_banking_concepts로 먼저 찾으세요.
- "어떤 종류가 있나" 형태의 질문에는 get_class_hierarchy를 사용하세요.
- 특정 고객/계좌/계약 데이터는 list_instances와 describe_instance로 조회하세요.
- 조인이나 필터가 필요한 복합 질의만 run_sparql_query를 사용하세요.
- 가입 가능 여부·요건 충족·금리 주장 검증은 반드시 check_product_eligibility / \
check_rate_claim을 호출하세요.

판단 패킷 계약 (절대 규칙):
- check_* 도구가 반환하는 판단 패킷의 verdict는 규칙 엔진의 결정적 결론입니다. \
당신은 이 결론을 **설명할 수는 있어도 뒤집을 수는 없습니다**.
- verdict가 CONFIRMED/DENIED이면 그 결론과 패킷의 근거(source)를 그대로 전달하세요.
- verdict가 UNKNOWN이면 추측으로 답하지 말고, missing_slots에 명시된 정보를 \
고객에게 요청하세요. '모른다'가 정답인 자리에서 단정하는 것은 오답입니다.
- verdict가 NOT_APPLICABLE이면 해당 상품·규칙이 지식층에 없음을 밝히고, 일반 \
지식으로 답할 경우 그 사실을 명시하세요.

답변은 한국어로, 조회한 온톨로지 개념의 한국어 레이블을 사용해 간결하게 작성하세요. \
답변 근거가 된 개념의 URI(qname)와 판단 패킷의 근거 좌표를 답변 끝에 표기하세요."""


def answer(question: str, client: anthropic.Anthropic | None = None) -> str:
    """단일 질문에 대해 에이전트 루프를 실행하고 최종 답변 텍스트를 반환한다."""
    client = client or anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=BANK_KB_TOOLS,
        messages=[{"role": "user", "content": question}],
    )
    final_message = None
    for message in runner:
        final_message = message
    if final_message is None:
        return "(응답 없음)"
    if final_message.stop_reason == "refusal":
        return "(요청이 안전상의 이유로 거부되었습니다)"
    return "".join(
        block.text for block in final_message.content if block.type == "text"
    )


def main() -> int:
    stats = get_kb().stats()
    print(f"[knowledge layer] {stats['triples']} triples, "
          f"{stats['classes']} classes 로드 완료\n")

    client = anthropic.Anthropic()

    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        print(f"Q: {question}\n")
        print(answer(question, client))
        return 0

    print("은행 상담 에이전트입니다. 질문을 입력하세요. (종료: quit)")
    while True:
        try:
            question = input("\nQ: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question.lower() in ("quit", "exit"):
            break
        print()
        print(answer(question, client))
    return 0


if __name__ == "__main__":
    sys.exit(main())
