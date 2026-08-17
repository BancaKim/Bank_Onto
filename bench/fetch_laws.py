"""국가법령정보센터(law.go.kr) DRF API로 벤치마크용 법령 원문 수집.

카테고리별 근거 법령의 현행 조문을 구조화 JSON으로 받아
data/laws/{slug}.json 으로 저장한다 (기본정보 + 조문 목록만 트림).

법령 데이터는 공공데이터(무료·출처표시)이며, OC=test 게스트 계정으로 접근한다.

실행: python bench/fetch_laws.py
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "data" / "laws"

# (검색용 정확한 법령명, slug, 벤치마크 카테고리)
LAWS = [
    ("은행법", "banking-act", "공통"),
    ("예금자보호법", "depositor-protection-act", "예금"),
    ("금융소비자 보호에 관한 법률", "financial-consumer-protection-act", "공통"),
    ("여신전문금융업법", "specialized-credit-finance-act", "카드"),
    ("외국환거래법", "foreign-exchange-transactions-act", "외환"),
    ("근로자퇴직급여 보장법", "retirement-benefit-act", "퇴직연금"),
    ("자본시장과 금융투자업에 관한 법률", "capital-markets-act", "펀드"),
]

BASE = "https://www.law.go.kr/DRF"
HEADERS = {"User-Agent": "Mozilla/5.0 (bank-onto-bench builder)"}


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def find_current_mst(name: str) -> tuple[str, dict]:
    query = urllib.parse.quote(name)
    data = get_json(f"{BASE}/lawSearch.do?OC=test&target=law&type=JSON"
                    f"&query={query}&display=50")
    laws = data["LawSearch"]["law"]
    if isinstance(laws, dict):
        laws = [laws]
    for law in laws:
        if law["법령명한글"] == name and law["현행연혁코드"] == "현행":
            return law["법령일련번호"], law
    raise LookupError(f"현행 법령을 찾지 못함: {name}")


def flatten_article_text(article: dict) -> str:
    """조문내용 + 항/호/목 텍스트를 하나의 문자열로 평탄화."""
    parts = [str(article.get("조문내용", ""))]

    def walk(node):
        if isinstance(node, dict):
            for key in ("항내용", "호내용", "목내용"):
                if node.get(key):
                    parts.append(str(node[key]))
            for key in ("항", "호", "목"):
                if node.get(key):
                    walk(node[key])
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(article.get("항"))
    text = "\n".join(p for p in parts if p and p != "None")
    return re.sub(r"<[^>]+>", "", text)  # 각주 등 태그 제거


def fetch_law(name: str, slug: str, category: str) -> dict:
    mst, meta = find_current_mst(name)
    data = get_json(f"{BASE}/lawService.do?OC=test&target=law&MST={mst}&type=JSON")
    law = data["법령"]
    info = law["기본정보"]

    articles = []
    units = law["조문"]["조문단위"]
    if isinstance(units, dict):
        units = [units]
    for unit in units:
        if unit.get("조문여부") != "조문":
            continue  # 장·절 제목 등 제외
        number = str(unit.get("조문번호", ""))
        branch = str(unit.get("조문가지번호") or "")
        label = f"제{number}조" + (f"의{branch}" if branch and branch != "0" else "")
        title = str(unit.get("조문제목") or "").strip()
        text = flatten_article_text(unit)
        if "삭제" in text[:30] and len(text) < 40:
            continue  # 삭제된 조문
        articles.append({"label": label, "title": title, "text": text,
                         "effective": str(unit.get("조문시행일자") or "")})

    return {
        "name": info["법령명_한글"],
        "slug": slug,
        "category": category,
        "law_type": info.get("법종구분", {}).get("content", ""),
        "effective_date": str(info.get("시행일자", "")),
        "promulgation_date": str(info.get("공포일자", "")),
        "ministry": info.get("소관부처", {}).get("content", ""),
        "mst": mst,
        "source_url": f"https://www.law.go.kr{meta.get('법령상세링크', '')}",
        "fetched_from": "국가법령정보센터 Open API (www.law.go.kr)",
        "articles": articles,
    }


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, slug, category in LAWS:
        out = OUTPUT_DIR / f"{slug}.json"
        law = fetch_law(name, slug, category)
        out.write_text(json.dumps(law, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        print(f"  {law['name']}: 조문 {len(law['articles'])}개 "
              f"(시행 {law['effective_date']}) → {out.name}")
        time.sleep(0.5)  # API 예의
    return 0


if __name__ == "__main__":
    sys.exit(main())
