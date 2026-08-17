"""FSS 공시 상품 명명 규칙 (인제스트·벤치마크 생성기 공유).

신용대출은 같은 상품명이 유형별(일반신용대출/마이너스한도대출/장기카드대출)로
중복 공시되므로 유형명으로 구분한다. 규칙은 KB 적재와 벤치마크 문항 생성이
동일하게 사용해야 한다 — 어긋나면 문항의 상품명이 지식층에 존재하지 않게 된다.
"""
from __future__ import annotations

import re


def clean_name(name: str) -> str:
    """FSS 원본 상품명의 개행·연속 공백을 단일 공백으로 정규화."""
    return re.sub(r"\s+", " ", name or "").strip()


def credit_name_resolver(base_list: list[dict]):
    """신용대출 baseList → 항목별 표시 이름 함수.

    같은 은행에 정규화된 상품명이 중복될 때만(일반/마이너스한도 등 유형 중복
    공시) 유형명을 병기한다 — 항상 병기하면 "가계신용대출(일반)(일반신용대출)"
    같은 이중 괄호가 생긴다.
    """
    from collections import Counter

    counts = Counter(
        (item["fin_co_no"], clean_name(item["fin_prdt_nm"])) for item in base_list)

    def name_of(item: dict) -> str:
        name = clean_name(item["fin_prdt_nm"])
        type_nm = clean_name(item.get("crdt_prdt_type_nm") or "")
        if counts[(item["fin_co_no"], name)] <= 1 or not type_nm or type_nm in name:
            return name
        if type_nm.startswith(name):
            return type_nm  # 장기카드대출 + 장기카드대출(카드론) → 후자
        return f"{name}({type_nm})"

    return name_of
