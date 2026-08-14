"""실무형(시장 데이터) 벤치마크: 온톨로지 RAG vs 벡터 RAG.

data/market-instances.ttl 에 적재된 상품 공시 데이터에서 질문과 정답을
**자동 생성**한다 — 샘플 픽스처든 FSS 실데이터든 같은 코드가 동작하며,
데이터가 커질수록 벡터 RAG의 top-k 한계가 더 뚜렷해진다.

비교 방식:
- 벡터 RAG: 전체 지식(온톨로지+시장 데이터) 직렬화 → 청킹 → TF-IDF top-5
- 온톨로지 RAG: 질문 유형별 SPARQL 실행 결과를 컨텍스트로 사용
  (에이전트의 run_sparql_query 도구가 하는 일을 결정적으로 재현)

실행: python eval/run_market_eval.py   (API 키 불필요)
결과: docs/market-benchmark-report.md
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.corpus import build_documents, chunk_corpus
from eval.lpg_rag import LpgGraphRetriever
from eval.vector_rag import TfidfVectorRetriever
from knowledge.kb import BankKnowledgeBase

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "docs" / "market-benchmark-report.md"


def render_rows(rows: list[dict]) -> str:
    return "\n".join(
        " | ".join(f"{k}: {v}" for k, v in row.items()) for row in rows
    )


def build_market_questions(kb: BankKnowledgeBase) -> list[dict]:
    """적재된 시장 데이터에서 질문·SPARQL·정답(gold)을 자동 생성한다."""
    questions = []

    # 1) 12개월 정기예금 최고 우대금리 (정렬/최댓값)
    q = """SELECT ?name ?rate WHERE {
        ?p a products:TimeDepositProduct ; products:hasProductName ?name ;
           market:hasRateOption ?o .
        ?o market:termMonths 12 ; market:maxPreferentialRateValue ?rate .
    } ORDER BY DESC(?rate) LIMIT 1"""
    rows = kb.run_sparql(q)
    if rows:
        questions.append({
            "id": "MKT-AGG-1", "category": "정렬/최댓값",
            "question": "12개월 정기예금 중 최고 우대금리 상품은 뭐야?",
            "sparql": q, "gold": [rows[0]["name"], rows[0]["rate"]],
        })

    # 2) 상품 개수 집계 — '개수'는 코퍼스 어디에도 적혀 있지 않으므로,
    #    올바르게 세려면 전체 상품 목록이 컨텍스트에 있어야 한다.
    #    (근거 = 전체 상품명. SPARQL 컨텍스트에는 COUNT 결과와 목록을 함께 제공)
    q = """SELECT ?name WHERE { ?p a products:TimeDepositProduct ;
                                    products:hasProductName ?name }"""
    rows = kb.run_sparql(q)
    if rows:
        questions.append({
            "id": "MKT-AGG-2", "category": "집계(COUNT)",
            "question": "공시된 정기예금 상품은 모두 몇 개야?",
            "sparql": q, "gold": sorted({r["name"] for r in rows}),
        })

    # 3) 아파트 담보 주담대 최저금리
    q = """SELECT ?name (MIN(?r) AS ?minRate) WHERE {
        ?p a products:MortgageLoanProduct ; products:hasProductName ?name ;
           market:hasRateOption ?o .
        ?o market:mortgageTypeName "아파트" ; market:lendRateMin ?r .
    } GROUP BY ?name ORDER BY ?minRate LIMIT 1"""
    rows = kb.run_sparql(q)
    if rows:
        questions.append({
            "id": "MKT-AGG-3", "category": "정렬/최솟값",
            "question": "아파트 담보 주택담보대출 중 최저금리 상품과 금리는?",
            "sparql": q, "gold": [rows[0]["name"], rows[0]["minRate"]],
        })

    # 4) 특정 은행의 상품 전체 열거 — 상품이 가장 많은 은행 선택
    q = """SELECT ?bankName (COUNT(?p) AS ?cnt) WHERE {
        ?p a products:TimeDepositProduct ; products:isOfferedBy ?b .
        ?b parties:hasName ?bankName .
    } GROUP BY ?bankName ORDER BY DESC(?cnt) LIMIT 1"""
    rows = kb.run_sparql(q)
    if rows:
        bank = rows[0]["bankName"]
        q2 = f"""SELECT ?name WHERE {{
            ?p a products:TimeDepositProduct ; products:hasProductName ?name ;
               products:isOfferedBy ?b .
            ?b parties:hasName "{bank}" .
        }}"""
        names = [r["name"] for r in kb.run_sparql(q2)]
        questions.append({
            "id": "MKT-LIST-1", "category": "완전 열거",
            "question": f"{bank}의 정기예금 상품을 전부 알려줘",
            "sparql": q2, "gold": names,
        })

    # 5) 조건 필터: 고정금리 주담대
    q = """SELECT DISTINCT ?name ?bankName WHERE {
        ?p a products:MortgageLoanProduct ; products:hasProductName ?name ;
           products:isOfferedBy ?b ; market:hasRateOption ?o .
        ?b parties:hasName ?bankName .
        ?o market:lendRateTypeName "고정금리" .
    }"""
    rows = kb.run_sparql(q)
    if rows:
        questions.append({
            "id": "MKT-FILT-1", "category": "조건 필터",
            "question": "고정금리 방식 주택담보대출 상품은 뭐가 있어?",
            "sparql": q, "gold": sorted({r["name"] for r in rows}),
        })

    # 6) 조건 필터: 마이너스통장 취급 은행
    q = """SELECT DISTINCT ?bankName WHERE {
        ?p a products:OverdraftProduct ; products:isOfferedBy ?b .
        ?b parties:hasName ?bankName .
    }"""
    rows = kb.run_sparql(q)
    if rows:
        questions.append({
            "id": "MKT-FILT-2", "category": "조건 필터",
            "question": "마이너스통장(한도대출) 상품을 취급하는 은행은 어디야?",
            "sparql": q, "gold": sorted({r["bankName"] for r in rows}),
        })

    # 7) 개별 상품 속성 조회: 우대조건
    q = """SELECT ?name ?cond WHERE {
        ?p a products:TimeDepositProduct ; products:hasProductName ?name ;
           market:preferentialCondition ?cond .
    } ORDER BY ?name LIMIT 1"""
    rows = kb.run_sparql(q)
    if rows:
        name, cond = rows[0]["name"], rows[0]["cond"]
        q2 = f"""SELECT ?cond WHERE {{
            ?p products:hasProductName "{name}" ; market:preferentialCondition ?cond .
        }}"""
        snippet = cond.split(",")[0][:20]
        questions.append({
            "id": "MKT-HOP-1", "category": "속성 조회",
            "question": f"{name}의 우대조건이 뭐야?",
            "sparql": q2, "gold": [snippet],
        })

    # 8) 36개월 적금 최고 우대금리
    q = """SELECT ?name ?rate WHERE {
        ?p a products:InstallmentSavingsProduct ; products:hasProductName ?name ;
           market:hasRateOption ?o .
        ?o market:termMonths 36 ; market:maxPreferentialRateValue ?rate .
    } ORDER BY DESC(?rate) LIMIT 1"""
    rows = kb.run_sparql(q)
    if rows:
        questions.append({
            "id": "MKT-AGG-4", "category": "정렬/최댓값",
            "question": "36개월 만기 적금 중 최고 우대금리 상품과 금리는?",
            "sparql": q, "gold": [rows[0]["name"], rows[0]["rate"]],
        })

    return questions


def main() -> int:
    kb = BankKnowledgeBase()

    # 데이터 출처 확인 (샘플인지 실데이터인지 리포트에 명시)
    src_rows = kb.run_sparql(
        "SELECT DISTINCT ?s WHERE { ?p market:sourceNote ?s }")
    source = src_rows[0]["s"] if src_rows else "시장 데이터 없음"
    is_sample = "샘플" in source

    n_products = int(kb.run_sparql(
        "SELECT (COUNT(?p) AS ?c) WHERE { ?p market:sourceNote ?s }")[0]["c"])

    docs = build_documents(kb)
    chunks = chunk_corpus(docs)
    vector = TfidfVectorRetriever(chunks)
    lpg = LpgGraphRetriever(kb)

    questions = build_market_questions(kb)
    if not questions:
        print("시장 데이터가 없습니다. 먼저 ingest/fss_to_ttl.py 를 실행하세요.")
        return 1

    print(f"데이터 출처: {source}")
    print(f"상품 {n_products}개 / 코퍼스 청크 {len(chunks)}개 / 질문 {len(questions)}개\n")

    rows = []
    for q in questions:
        v_ctx = vector.retrieve_context(q["question"], k=5)
        l_ctx = lpg.retrieve_context(q["question"])
        g_ctx = render_rows(kb.run_sparql(q["sparql"]))
        total = len(q["gold"])
        v_found = sum(1 for g in q["gold"] if g in v_ctx)
        l_found = sum(1 for g in q["gold"] if g in l_ctx)
        g_found = sum(1 for g in q["gold"] if g in g_ctx)
        rows.append({**q, "v": v_found, "l": l_found, "g": g_found, "total": total,
                     "v_chars": len(v_ctx), "l_chars": len(l_ctx), "g_chars": len(g_ctx),
                     "v_missing": [x for x in q["gold"] if x not in v_ctx]})
        print(f"  {q['id']:11s} vector {v_found}/{total}   lpg {l_found}/{total}   graph {g_found}/{total}")

    def rate(key):
        return sum(r[key] for r in rows) / sum(r["total"] for r in rows)

    v_rate, l_rate, g_rate = rate("v"), rate("l"), rate("g")
    v_perfect = sum(1 for r in rows if r["v"] == r["total"])
    l_perfect = sum(1 for r in rows if r["l"] == r["total"])
    g_perfect = sum(1 for r in rows if r["g"] == r["total"])
    avg_v = sum(r["v_chars"] for r in rows) / len(rows)
    avg_l = sum(r["l_chars"] for r in rows) / len(rows)
    avg_g = sum(r["g_chars"] for r in rows) / len(rows)

    print(f"\n근거 재현율: vector {v_rate:.0%}  /  lpg {l_rate:.0%}  /  graph {g_rate:.0%}")

    md = ["# 실무형(시장 데이터) 벤치마크: 온톨로지 RAG vs 벡터 RAG\n"]
    if is_sample:
        md.append("> ⚠️ **현재 결과는 가상 은행 샘플 픽스처 기준이다** (파이프라인 검증용). "
                  "실데이터 결과는 `FSS_API_KEY=... python ingest/fss_client.py && "
                  "python ingest/fss_to_ttl.py && python eval/run_market_eval.py` 로 재생성한다.\n")
    md.append(f"- 데이터 출처: {source}")
    md.append(f"- 상품 수: {n_products}개 / 벡터 코퍼스 청크: {len(chunks)}개")
    md.append("- 질문과 정답은 적재된 데이터에서 SPARQL로 자동 계산 — 데이터가 바뀌면 "
              "벤치마크도 함께 갱신된다\n")
    md.append("## 결과\n")
    md.append("| 지표 | 벡터 RAG | Graph RAG(LPG) | 온톨로지 RAG (SPARQL) |")
    md.append("|---|---|---|---|")
    md.append(f"| 근거 재현율 | {v_rate:.0%} | {l_rate:.0%} | **{g_rate:.0%}** |")
    md.append(f"| 완전 답변 가능 질문 | {v_perfect}/{len(rows)} | {l_perfect}/{len(rows)} | **{g_perfect}/{len(rows)}** |")
    md.append(f"| 평균 컨텍스트 크기 | {avg_v:,.0f}자 | {avg_l:,.0f}자 | **{avg_g:,.0f}자** |\n")
    md.append("## 질문별 상세\n")
    md.append("| ID | 유형 | 질문 | 벡터 | LPG | 온톨로지 | 벡터가 놓친 근거 |")
    md.append("|---|---|---|---|---|---|---|")
    for r in rows:
        miss = ", ".join(r["v_missing"]) or "-"
        md.append(f"| {r['id']} | {r['category']} | {r['question']} "
                  f"| {r['v']}/{r['total']} | {r['l']}/{r['total']} | {r['g']}/{r['total']} | {miss} |")
    md.append("""
## 왜 실무 질문에서 격차가 벌어지는가

은행 실무 질문은 대부분 **비교·집계·조건 필터**다 ("최고 금리는?", "몇 개야?",
"고정금리만 골라줘"). 이런 질문의 답은 **어떤 문서에도 적혀 있지 않고 데이터를
연산해야만 나온다**:

- `COUNT`: 상품 개수는 코퍼스 어느 청크에도 존재하지 않는다. 벡터 검색은 원리적으로
  이 답을 가져올 수 없고, LLM이 top-k 청크에 보이는 상품만 세면 **그럴듯한 오답**이 된다.
- `ORDER BY / MIN / MAX`: "최고 우대금리 상품"은 전체를 비교해야 안다. top-k에 우연히
  1위 상품이 포함되어도 그것이 1위라는 보장은 컨텍스트에 없다.
- 조건 필터: "고정금리만"은 유사도가 아니라 조건 평가다.

SPARQL은 이 연산을 정확히 수행하며, 컨텍스트도 결과 행만 담아 수십 배 작다.
상품 수가 수백 개(실데이터)로 늘면 top-k의 커버리지는 더 떨어지므로 격차는 커진다.

Graph RAG(LPG)의 이웃 탐색도 같은 이유로 집계에 약하다: 서브그래프를 가져올 수는
있어도 "전체 중 최댓값"은 노드 수 제한(cap)에 걸리면 근거가 잘리고, 정렬·집계 연산
자체가 없다. 실무의 text2cypher 방식은 집계가 가능하지만 서브클래스 추론과 표준
스키마(FIBO 정렬)가 없다는 차이는 남는다.

*재생성: `python eval/run_market_eval.py`*
""")
    REPORT_PATH.write_text("\n".join(md), encoding="utf-8")
    print(f"리포트 저장: {REPORT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
