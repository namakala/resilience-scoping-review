"""KeyBERT-based keyword extraction for exemplars.

Extracts top-5 keywords per exemplar using KeyBERT with MMR diversity.
Writes immutable keywords.parquet. Extraction is one-shot (rerun guarded
by existence check). Phase 2 LLM refinement was evaluated but not needed:
KeyBERT alone provides sufficient quality for downstream inference.
"""

from pathlib import Path

import polars as pl
from keybert import KeyBERT
from persistence.loaders import load_exemplars, load_keywords
from tqdm import tqdm
from utils.logging import get_logger

logger = get_logger(__name__)

_KEYBERT_MODEL = "all-MiniLM-L6-v2"


def _get_keybert_model() -> KeyBERT:
    """Return a lazily-initialized KeyBERT singleton.

    Uses the same sentence-transformer model as the embedding layer
    (all-MiniLM-L6-v2) so no additional model download is needed.
    """
    return KeyBERT(model=_KEYBERT_MODEL)


def extract_keywords(
    force_rebuild: bool = False,
    top_n: int = 5,
    diversity: float = 0.5,
    ngram_range: tuple[int, int] = (1, 2),
) -> pl.LazyFrame:
    """Extract keywords from exemplars using KeyBERT with MMR.

    Reads exemplars via load_exemplars(), runs KeyBERT extraction with
    MMR diversity on each exemplar's content, and writes the resulting
    keywords to keywords.parquet. The artifact is immutable: if the file
    already exists and force_rebuild is False, the function returns early.

    Args:
        force_rebuild: If True, overwrite existing keywords.parquet.
        top_n: Number of keywords to extract per exemplar.
        diversity: MMR diversity parameter (0=min, 1=max).
        ngram_range: (min_n, max_n) for keyphrase n-grams.

    Returns:
        LazyFrame loaded from keywords.parquet (via load_keywords()).

    Raises:
        FileNotFoundError: If exemplars.parquet does not exist.
    """
    from persistence.loaders import KEYWORDS_PARQUET  # resolve dynamically

    output_path = Path(KEYWORDS_PARQUET)
    if output_path.exists() and not force_rebuild:
        logger.info("Keywords already extracted; skipping (force_rebuild to re-run)")
        load_keywords.cache_clear()
        return load_keywords()

    lf = load_exemplars().select(["id", "content"])
    df = lf.collect()
    total = df.height

    if total == 0:
        logger.info("No exemplars to extract keywords from")
        _write_empty(output_path)
        load_keywords.cache_clear()
        return load_keywords()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    kw_model = _get_keybert_model()

    rows: list[dict] = []
    kw_id = 0

    with tqdm(total=total, desc="Extracting keywords", unit="ex") as pbar:
        for row in df.iter_rows(named=True):
            eid = row["id"]
            content = row["content"]

            if not content or not content.strip():
                pbar.update(1)
                continue

            try:
                keywords = kw_model.extract_keywords(
                    content,
                    keyphrase_ngram_range=ngram_range,
                    use_mmr=True,
                    diversity=diversity,
                    top_n=top_n,
                    stop_words="english",
                )
            except Exception:
                logger.warning("KeyBERT failed for exemplar %s; skipping", eid)
                pbar.update(1)
                continue

            for kw_text, score in keywords:
                kw_id += 1
                rows.append(
                    {
                        "keyword_id": kw_id,
                        "exemplar_id": eid,
                        "keyword_text": kw_text,
                        "frequency": int(round(score * 10000)),
                    }
                )

            pbar.update(1)

    kw_df = pl.DataFrame(
        rows,
        schema={
            "keyword_id": pl.Int64,
            "exemplar_id": pl.Int64,
            "keyword_text": pl.String,
            "frequency": pl.Int32,
        },
    )

    kw_df.write_parquet(output_path, compression="snappy")
    logger.info(
        "Keywords extracted",
        extra={
            "exemplars": total,
            "keywords": kw_id,
            "path": str(output_path),
        },
    )

    load_keywords.cache_clear()
    return load_keywords()


def _write_empty(output_path: Path) -> None:
    """Write an empty keywords.parquet with the correct schema."""
    empty = pl.DataFrame(
        schema={
            "keyword_id": pl.Int64,
            "exemplar_id": pl.Int64,
            "keyword_text": pl.String,
            "frequency": pl.Int32,
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    empty.write_parquet(output_path, compression="snappy")
    logger.debug(
        "Empty keywords.parquet written",
        extra={"path": str(output_path)},
    )
