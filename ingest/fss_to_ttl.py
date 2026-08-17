"""FSS 금융상품한눈에 JSON → 온톨로지 인스턴스(TTL) 변환기.

data/fss/*.json (fss_client.py 다운로드 결과)을 읽어
data/market-instances.ttl 로 변환한다. 상품은 기존 온톨로지 클래스에 매핑된다:

    deposit  → products:TimeDepositProduct       (정기예금)
    saving   → products:InstallmentSavingsProduct (적금)
    mortgage → products:MortgageLoanProduct       (주택담보대출)
    rent     → products:JeonseLoanProduct         (전세자금대출)
    credit   → products:CreditLoanProduct / OverdraftProduct (신용/마이너스한도)

사용법:
    python ingest/fss_to_ttl.py            # data/fss/ 의 실데이터 변환
    python ingest/fss_to_ttl.py --sample   # data/fss/sample/ 픽스처로 파이프라인 검증
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.fss_naming import clean_name, credit_name_resolver  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "data" / "market-instances.ttl"

MARKET = Namespace("https://w3id.org/bank-onto/market/")
MKTD = Namespace("https://w3id.org/bank-onto/market/data/")
PRODUCTS = Namespace("https://w3id.org/bank-onto/products/")
PARTIES = Namespace("https://w3id.org/bank-onto/parties/")

# FSS 공시 코드 → 텍스트 (금융상품한눈에 API 명세의 join_deny 코드)
JOIN_DENY_TEXT = {"1": "제한없음", "2": "서민전용", "3": "일부제한"}

PRODUCT_CLASS = {
    "deposit": PRODUCTS.TimeDepositProduct,
    "saving": PRODUCTS.InstallmentSavingsProduct,
    "mortgage": PRODUCTS.MortgageLoanProduct,
    "rent": PRODUCTS.JeonseLoanProduct,
    "credit": PRODUCTS.CreditLoanProduct,
}


def slug(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", str(text)).strip("_")


def add_if(graph: Graph, subj, pred, value, datatype=None):
    if value is None or value == "":
        return
    if datatype:
        graph.add((subj, pred, Literal(value, datatype=datatype)))
    else:
        graph.add((subj, pred, Literal(str(value))))


def decimal_of(value):
    if value is None or value == "":
        return None
    return Decimal(str(value))


def convert(input_dir: Path, source_note: str) -> Graph:
    graph = Graph()
    graph.bind("market", MARKET)
    graph.bind("mktd", MKTD)
    graph.bind("products", PRODUCTS)
    graph.bind("parties", PARTIES)

    banks: dict[str, URIRef] = {}
    n_products = n_options = 0

    for kind, cls in PRODUCT_CLASS.items():
        path = input_dir / f"{kind}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))

        # 상품 기본 정보
        products_by_code: dict[tuple, URIRef] = {}
        credit_name = credit_name_resolver(data.get("baseList", []))
        for item in data.get("baseList", []):
            co_no, prdt_cd = item["fin_co_no"], item["fin_prdt_cd"]

            bank = banks.get(co_no)
            if bank is None:
                bank = MKTD[f"bank_{slug(co_no)}"]
                banks[co_no] = bank
                graph.add((bank, RDF.type, PARTIES.Bank))
                graph.add((bank, PARTIES.hasName, Literal(item["kor_co_nm"])))
                add_if(graph, bank, MARKET.finCompanyNo, co_no)

            product_cls = cls
            if kind == "credit" and str(item.get("crdt_prdt_type")) == "2":
                product_cls = PRODUCTS.OverdraftProduct  # 마이너스한도대출

            product = MKTD[f"prdt_{slug(co_no)}_{slug(prdt_cd)}"]
            products_by_code[(co_no, prdt_cd)] = product
            n_products += 1
            graph.add((product, RDF.type, product_cls))
            display_name = credit_name(item) if kind == "credit" \
                else clean_name(item["fin_prdt_nm"])
            graph.add((product, PRODUCTS.hasProductName, Literal(display_name)))
            graph.add((product, PRODUCTS.hasProductCode, Literal(prdt_cd)))
            graph.add((product, PRODUCTS.isOfferedBy, bank))
            add_if(graph, product, MARKET.disclosureMonth, item.get("dcls_month"))
            add_if(graph, product, MARKET.joinWay, item.get("join_way"))
            add_if(graph, product, MARKET.joinMember, item.get("join_member"))
            add_if(graph, product, MARKET.preferentialCondition, item.get("spcl_cnd"))
            add_if(graph, product, MARKET.joinDenyNote,
                   JOIN_DENY_TEXT.get(str(item.get("join_deny", "")).strip()))
            add_if(graph, product, MARKET.etcNote, item.get("etc_note"))
            add_if(graph, product, MARKET.maxLimitNote,
                   item.get("max_limit") or item.get("loan_lmt"))
            add_if(graph, product, MARKET.sourceNote, source_note)

        # 금리 옵션
        for i, opt in enumerate(data.get("optionList", [])):
            product = products_by_code.get((opt["fin_co_no"], opt["fin_prdt_cd"]))
            if product is None:
                continue
            n_options += 1
            option = URIRef(str(product) + f"_opt{i}")
            graph.add((product, MARKET.hasRateOption, option))

            if kind in ("deposit", "saving"):
                graph.add((option, RDF.type, MARKET.RateOption))
                add_if(graph, option, MARKET.termMonths,
                       int(opt["save_trm"]), XSD.integer)
                add_if(graph, option, MARKET.baseRateValue,
                       decimal_of(opt.get("intr_rate")), XSD.decimal)
                add_if(graph, option, MARKET.maxPreferentialRateValue,
                       decimal_of(opt.get("intr_rate2")), XSD.decimal)
                add_if(graph, option, MARKET.interestCalcType, opt.get("intr_rate_type_nm"))
                add_if(graph, option, MARKET.reserveType, opt.get("rsrv_type_nm"))
            elif kind in ("mortgage", "rent"):
                graph.add((option, RDF.type, MARKET.LendRateOption))
                add_if(graph, option, MARKET.lendRateTypeName, opt.get("lend_rate_type_nm"))
                add_if(graph, option, MARKET.repaymentTypeName, opt.get("rpay_type_nm"))
                add_if(graph, option, MARKET.mortgageTypeName, opt.get("mrtg_type_nm"))
                add_if(graph, option, MARKET.lendRateMin,
                       decimal_of(opt.get("lend_rate_min")), XSD.decimal)
                add_if(graph, option, MARKET.lendRateMax,
                       decimal_of(opt.get("lend_rate_max")), XSD.decimal)
                add_if(graph, option, MARKET.lendRateAvg,
                       decimal_of(opt.get("lend_rate_avg")), XSD.decimal)
            elif kind == "credit":
                if opt.get("crdt_lend_rate_type") != "A":
                    continue  # 대출금리 행만 사용 (기준/가산금리 행 제외)
                graph.add((option, RDF.type, MARKET.LendRateOption))
                add_if(graph, option, MARKET.lendRateAvg,
                       decimal_of(opt.get("crdt_grad_avg")), XSD.decimal)

    print(f"변환: 은행 {len(banks)}개, 상품 {n_products}개, 금리옵션 {n_options}개, "
          f"트리플 {len(graph)}개")
    return graph


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true",
                        help="data/fss/sample/ 픽스처로 파이프라인 검증")
    args = parser.parse_args()

    if args.sample:
        input_dir = REPO_ROOT / "data" / "fss" / "sample"
        source_note = "샘플 픽스처(가상 은행) — 파이프라인 검증용"
    else:
        input_dir = REPO_ROOT / "data" / "fss"
        source_note = "금융감독원 금융상품통합비교공시 Open API (finlife.fss.or.kr)"
        if not any(input_dir.glob("*.json")):
            print("data/fss/ 에 다운로드된 데이터가 없습니다. "
                  "먼저 `FSS_API_KEY=... python ingest/fss_client.py` 를 실행하거나 "
                  "--sample 로 픽스처를 사용하세요.")
            return 1

    graph = convert(input_dir, source_note)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(OUTPUT_PATH, format="turtle")
    print(f"저장: {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
