"""FSS 공시 상품 명명 규칙 (인제스트·벤치마크 생성기 공유).

신용대출은 같은 상품명이 유형별(일반신용대출/마이너스한도대출/장기카드대출)로
중복 공시되므로 유형명으로 구분한다. 규칙은 KB 적재와 벤치마크 문항 생성이
동일하게 사용해야 한다 — 어긋나면 문항의 상품명이 지식층에 존재하지 않게 된다.
"""
from __future__ import annotations


def credit_product_name(name: str, type_nm: str | None) -> str:
    """유형명이 상품명을 포함하면 유형명을 그대로, 아니면 괄호 병기."""
    if not type_nm or type_nm == name:
        return name
    if type_nm.startswith(name):
        return type_nm  # 예: 장기카드대출 + 장기카드대출(카드론) → 장기카드대출(카드론)
    return f"{name}({type_nm})"
