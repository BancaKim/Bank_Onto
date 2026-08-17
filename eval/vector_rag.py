"""벡터 RAG 베이스라인 리트리버.

문자 n-gram TF-IDF 코사인 유사도 기반의 오프라인 벡터 검색.
(외부 임베딩 API 없이 재현 가능하도록 한 어휘적(lexical) 벡터 베이스라인이다.
 의미 임베딩으로 교체하려면 `embed` 함수만 갈아끼우면 된다 — run_e2e.py 참고.)
"""
from __future__ import annotations

import math
from collections import Counter


def char_ngrams(text: str, sizes: tuple[int, ...] = (2, 3)) -> Counter:
    text = text.lower()
    grams: Counter = Counter()
    for n in sizes:
        for i in range(len(text) - n + 1):
            grams[text[i:i + n]] += 1
    return grams


class TfidfVectorRetriever:
    """청크 단위 TF-IDF 코사인 유사도 top-k 검색."""

    def __init__(self, chunks: list[str]):
        self.chunks = chunks
        self._doc_grams = [char_ngrams(c) for c in chunks]

        df: Counter = Counter()
        for grams in self._doc_grams:
            for gram in grams:
                df[gram] += 1
        n_docs = len(chunks)
        self._idf = {g: math.log(n_docs / (1 + count)) + 1 for g, count in df.items()}
        self._default_idf = math.log(n_docs) + 1

        self._doc_vecs = [self._vectorize(g) for g in self._doc_grams]
        self._doc_norms = [
            math.sqrt(sum(w * w for w in vec.values())) or 1.0 for vec in self._doc_vecs
        ]
        # 역색인 (gram → [(doc_idx, weight)]): 점수 계산과 결과는 동일하고,
        # 질의 시 전체 문서 대신 해당 gram을 포함한 문서만 순회한다.
        self._postings: dict[str, list[tuple[int, float]]] = {}
        for idx, vec in enumerate(self._doc_vecs):
            for gram, weight in vec.items():
                self._postings.setdefault(gram, []).append((idx, weight))

    def _vectorize(self, grams: Counter) -> dict[str, float]:
        return {g: tf * self._idf.get(g, self._default_idf) for g, tf in grams.items()}

    def retrieve(self, query: str, k: int = 5) -> list[str]:
        query_vec = self._vectorize(char_ngrams(query))
        query_norm = math.sqrt(sum(w * w for w in query_vec.values())) or 1.0

        dots: dict[int, float] = {}
        for gram, weight in query_vec.items():
            for idx, doc_weight in self._postings.get(gram, ()):
                dots[idx] = dots.get(idx, 0.0) + weight * doc_weight
        scored = [(dot / (query_norm * self._doc_norms[idx]), idx)
                  for idx, dot in dots.items() if dot > 0]
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [self.chunks[idx] for _, idx in scored[:k]]

    def retrieve_context(self, query: str, k: int = 5) -> str:
        chunks = self.retrieve(query, k=k)
        return "\n---\n".join(chunks)
