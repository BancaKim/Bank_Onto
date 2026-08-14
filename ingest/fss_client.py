"""금융감독원 금융상품통합비교공시("금융상품한눈에") Open API 다운로더.

합법적 데이터 소스: finlife.fss.or.kr Open API는 공시 데이터의 활용을 위해
공식 제공되는 API다 (무료 키 발급 필요).

사용법:
    export FSS_API_KEY=발급받은키
    python ingest/fss_client.py            # 은행권(020000) 전 상품 다운로드
    python ingest/fss_client.py --group 030300   # 저축은행

결과: data/fss/{deposit,saving,mortgage,rent,credit}.json
API 키는 환경변수로만 전달하며 저장소에 커밋하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "data" / "fss"

BASE_URL = "https://finlife.fss.or.kr/finlifeapi"

ENDPOINTS = {
    "deposit": "depositProductsSearch.json",    # 정기예금
    "saving": "savingProductsSearch.json",      # 적금
    "mortgage": "mortgageLoanProductsSearch.json",  # 주택담보대출
    "rent": "rentHouseLoanProductsSearch.json",     # 전세자금대출
    "credit": "creditLoanProductsSearch.json",      # 개인신용대출
}


def fetch_all_pages(endpoint: str, auth: str, top_fin_grp_no: str) -> dict:
    """페이지네이션을 따라 baseList/optionList를 병합해 반환한다."""
    base_list, option_list = [], []
    page = 1
    while True:
        params = urllib.parse.urlencode({
            "auth": auth, "topFinGrpNo": top_fin_grp_no, "pageNo": page,
        })
        url = f"{BASE_URL}/{endpoint}?{params}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            payload = json.load(resp)
        result = payload.get("result", {})
        err = result.get("err_cd")
        if err and err != "000":
            raise RuntimeError(f"{endpoint} p{page}: API 오류 {err} {result.get('err_msg')}")
        base_list.extend(result.get("baseList") or [])
        option_list.extend(result.get("optionList") or [])
        max_page = int(result.get("max_page_no") or 1)
        if page >= max_page:
            break
        page += 1
    return {"baseList": base_list, "optionList": option_list}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", default="020000",
                        help="권역코드 (020000 은행, 030300 저축은행 등)")
    args = parser.parse_args()

    auth = os.environ.get("FSS_API_KEY")
    if not auth:
        print("FSS_API_KEY 환경변수를 설정하세요 (finlife.fss.or.kr에서 무료 발급).")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, endpoint in ENDPOINTS.items():
        print(f"[{name}] 다운로드 중...")
        data = fetch_all_pages(endpoint, auth, args.group)
        out = OUTPUT_DIR / f"{name}.json"
        out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  상품 {len(data['baseList'])}개, 금리옵션 {len(data['optionList'])}개 "
              f"→ {out.relative_to(REPO_ROOT)}")
    print("\n완료. 다음 단계: python ingest/fss_to_ttl.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
