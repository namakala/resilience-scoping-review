"""Direct unit tests for semantic/corpus.py pure functions.

Covers:
- build_corpus_from_keywords: small corpus, empty corpus, single exemplar
- compute_corpus_hash: deterministic, different inputs -> different hashes, empty
"""

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

import polars as pl  # noqa: E402
from semantic.corpus import (  # noqa: E402
    build_corpus_from_keywords,
    compute_corpus_hash,
)


def _tokenizer(text: str) -> list[str]:
    return text.lower().split()


def _kw_lf(rows: list) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "keyword_id": [r[0] for r in rows],
            "exemplar_id": [r[1] for r in rows],
            "keyword_text": [r[2] for r in rows],
            "frequency": [r[3] for r in rows],
        },
        schema={
            "keyword_id": pl.Int64,
            "exemplar_id": pl.Int64,
            "keyword_text": pl.String,
            "frequency": pl.Int32,
        },
    ).lazy()


def test_build_corpus_small():
    rows = [(1, 101, "stress", 5), (2, 101, "anxiety", 3), (3, 102, "resilience", 4)]
    corpus, entity_map = build_corpus_from_keywords(_kw_lf(rows), _tokenizer)
    assert len(corpus) == 2
    assert entity_map[101] == 0
    assert entity_map[102] == 1
    assert all(isinstance(t, list) for t in corpus)
    assert all(isinstance(w, str) for t in corpus for w in t)


def test_build_corpus_empty():
    corpus, entity_map = build_corpus_from_keywords(_kw_lf([]), _tokenizer)
    assert corpus == []
    assert entity_map == {}


def test_build_corpus_single_exemplar():
    rows = [(1, 1, "coping", 2), (2, 1, "adaptation", 1)]
    corpus, entity_map = build_corpus_from_keywords(_kw_lf(rows), _tokenizer)
    assert len(corpus) == 1
    assert entity_map[1] == 0


def test_compute_hash_deterministic():
    corpus = [["stress", "anxiety"], ["resilience"]]
    h1 = compute_corpus_hash(corpus)
    h2 = compute_corpus_hash(corpus)
    assert h1 == h2
    assert len(h1) == 16


def test_compute_hash_different_inputs():
    c1 = [["stress"]]
    c2 = [["anxiety"]]
    assert compute_corpus_hash(c1) != compute_corpus_hash(c2)


def test_compute_hash_empty():
    h = compute_corpus_hash([])
    assert len(h) == 16
    assert isinstance(h, str)


def test_compute_hash_preserves_order():
    corpus = [["b", "a"], ["d", "c"]]
    h = compute_corpus_hash(corpus)
    assert isinstance(h, str)
    assert len(h) == 16
