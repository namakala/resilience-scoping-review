"""Batch-encode exemplar content into embedding_cache; immutable.

Loads exemplars from load_exemplars(), determines which need encoding via
cache lookup with content_hash validation, batch-encodes via
generate_embeddings(). Also provides shared helpers used by
keyword_embedding.py.
"""

import time
from collections.abc import Callable

import duckdb
import polars as pl
from persistence.embedding_cache import put_embedding
from persistence.loaders import load_exemplars
from semantic.embeddings import generate_embeddings, get_model_hash
from tqdm import tqdm
from utils.logging import get_logger

logger = get_logger(__name__)


# ── Generic helpers (shared with keyword_embedding) ────────────────────────


def _get_existing_cache_map_generic(
    con: duckdb.DuckDBPyConnection,
    entity_ids: list[str],
    entity_type: str,
    model_hash: str,
) -> dict[str, str]:
    """Query embedding_cache for entries matching entity_type + model_hash.

    Returns dict mapping entity_id (str) -> stored content_hash.
    """
    if not entity_ids:
        return {}

    placeholders = ",".join("?" for _ in entity_ids)
    rows = con.execute(
        f"""
        SELECT entity_id, content_hash
        FROM embedding_cache
        WHERE entity_type = ?
          AND entity_id IN ({placeholders})
          AND model_hash = ?
        """,
        [entity_type] + entity_ids + [model_hash],
    ).fetchall()

    return {row[0]: row[1] for row in rows}


def _identify_uncached(
    items: list[tuple[str, str, str]],
    stored_map: dict[str, str],
) -> list[tuple[str, str, str]]:
    """Return items needing encoding.

    Each item is (entity_id, text, content_hash). Items already present
    in stored_map with matching content_hash are skipped.
    """
    to_encode: list[tuple[str, str, str]] = []
    for entity_id, text, ch in items:
        if entity_id in stored_map and stored_map[entity_id] == ch:
            continue
        to_encode.append((entity_id, text, ch))
    return to_encode


def _encode_and_store_generic(
    con: duckdb.DuckDBPyConnection,
    to_encode: list[tuple[str, str, str]],
    entity_type: str,
    model_hash: str,
    batch_size: int,
    desc: str,
    unit: str,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> int:
    """Batch-encode items and store in cache.

    Args:
        con: DuckDB connection.
        to_encode: List of (entity_id, text, content_hash).
        entity_type: Type tag for cache ('exemplar' or 'keyword').
        model_hash: Current model version hash.
        batch_size: Encode batch size.
        desc: tqdm progress bar description.
        unit: tqdm progress bar unit label.
        progress_callback: Optional callback ``(total, completed, desc)``
            for TUI progress reporting.

    Returns:
        Number of items encoded.
    """
    count = len(to_encode)
    if count == 0:
        return 0

    texts = [item[1] for item in to_encode]

    with tqdm(total=count, desc=desc, unit=unit) as pbar:
        for i in range(0, count, batch_size):
            batch_items = to_encode[i : i + batch_size]  # noqa: E203
            batch_texts = texts[i : i + batch_size]  # noqa: E203

            embeddings = generate_embeddings(batch_texts, batch_size)

            for (entity_id, _, content_hash), emb in zip(batch_items, embeddings):
                put_embedding(
                    con, entity_id, entity_type, emb, model_hash, content_hash
                )

            pbar.update(len(batch_items))

            if progress_callback:
                progress_callback(count, pbar.n, desc)

    return count


# ── Exemplar embedding generation ──────────────────────────────────────────


def generate_exemplar_embeddings(
    con: duckdb.DuckDBPyConnection,
    batch_size: int = 32,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Batch-generate embeddings for all uncached exemplars.

    Loads exemplars via load_exemplars(), queries embedding_cache to find
    which already have valid cached embeddings, and encodes only missing or
    stale (content_hash mismatch) exemplars.

    Args:
        con: Active DuckDB connection for cache queries.
        batch_size: Number of exemplars to encode per model-level batch.

    Returns:
        Dict with keys:
            - total: total exemplars found
            - cached: exemplars already in cache with valid content_hash
            - generated: exemplars newly encoded
            - duration_seconds: total wall-clock time
    """
    start = time.perf_counter()

    exemplars = _collect_exemplars()
    total = len(exemplars)
    if total == 0:
        logger.info("No exemplars to embed")
        return {
            "total": 0,
            "cached": 0,
            "generated": 0,
            "duration_seconds": 0.0,
        }

    model_hash = get_model_hash()

    to_encode = _identify_uncached_exemplars(con, exemplars, model_hash)
    cached_count = total - len(to_encode)

    generated_count = _encode_and_store_exemplars(
        con,
        to_encode,
        model_hash,
        batch_size,
        progress_callback=progress_callback,
    )

    elapsed = time.perf_counter() - start
    logger.info(
        "Exemplar embedding complete",
        extra={
            "total": total,
            "cached": cached_count,
            "generated": generated_count,
            "duration_seconds": round(elapsed, 2),
        },
    )
    return {
        "total": total,
        "cached": cached_count,
        "generated": generated_count,
        "duration_seconds": round(elapsed, 2),
    }


def _collect_exemplars() -> pl.DataFrame:
    """Load exemplars and collect id, content, content_hash eagerly."""
    lf = load_exemplars().select(["id", "content", "content_hash"])
    return lf.collect()


def _identify_uncached_exemplars(
    con: duckdb.DuckDBPyConnection,
    exemplars: pl.DataFrame,
    model_hash: str,
) -> list[tuple[str, str, str]]:
    """Return list of (entity_id, content, content_hash) needing encoding."""
    items = [
        (str(row["id"]), row["content"], row["content_hash"])
        for row in exemplars.iter_rows(named=True)
    ]
    ids = [item[0] for item in items]
    stored = _get_existing_cache_map_generic(con, ids, "exemplar", model_hash)
    return _identify_uncached(items, stored)


def _encode_and_store_exemplars(
    con: duckdb.DuckDBPyConnection,
    to_encode: list[tuple[str, str, str]],
    model_hash: str,
    batch_size: int,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> int:
    """Batch-encode exemplars and store in cache.

    Returns number of exemplars encoded.
    """
    return _encode_and_store_generic(
        con,
        to_encode,
        "exemplar",
        model_hash,
        batch_size,
        desc="Embedding exemplars",
        unit="ex",
        progress_callback=progress_callback,
    )


# ── Code embedding generation ──────────────────────────────────────────────────


def _build_code_text(node: dict) -> tuple[str, str]:
    """Build embedding text for a code node.

    Returns (text, content_hash) tuple.
    """
    name = node.get("name", "")
    definition = node.get("definition", "")
    tag = node.get("tag", "")
    text = f"{name}: {definition} [Tag: {tag}]"
    import hashlib

    ch = hashlib.sha256(text.encode()).hexdigest()[:16]
    return text, ch


def _collect_codes() -> list[dict]:
    """Load all draft/approved code nodes from graph."""
    from graph import get_nodes_by_type_and_tag

    nodes = get_nodes_by_type_and_tag("code", None)
    return [n for n in nodes if n.get("status") in ("draft", "approved")]


def _identify_uncached_codes(
    con: duckdb.DuckDBPyConnection,
    codes: list[dict],
    model_hash: str,
) -> list[tuple[str, str, str]]:
    """Return list of (entity_id, text, content_hash) needing encoding."""
    items = []
    for node in codes:
        text, ch = _build_code_text(node)
        items.append((str(node["id"]), text, ch))
    ids = [item[0] for item in items]
    stored = _get_existing_cache_map_generic(con, ids, "code", model_hash)
    return _identify_uncached(items, stored)


def generate_code_embeddings(
    con: duckdb.DuckDBPyConnection,
    batch_size: int = 32,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Batch-generate embeddings for all uncached code nodes.

    Loads code nodes from graph, queries embedding_cache to find
    which already have valid cached embeddings, and encodes only missing or
    stale (content_hash mismatch) codes.

    Args:
        con: Active DuckDB connection for cache queries.
        batch_size: Number of codes to encode per model-level batch.

    Returns:
        Dict with keys:
            - total: total codes found
            - cached: codes already in cache with valid content_hash
            - generated: codes newly encoded
            - duration_seconds: total wall-clock time
    """
    start = time.perf_counter()

    codes = _collect_codes()
    total = len(codes)
    if total == 0:
        logger.info("No codes to embed")
        return {
            "total": 0,
            "cached": 0,
            "generated": 0,
            "duration_seconds": 0.0,
        }

    model_hash = get_model_hash()

    to_encode = _identify_uncached_codes(con, codes, model_hash)
    cached_count = total - len(to_encode)

    generated_count = _encode_and_store_generic(
        con,
        to_encode,
        "code",
        model_hash,
        batch_size,
        desc="Embedding codes",
        unit="codes",
        progress_callback=progress_callback,
    )

    elapsed = time.perf_counter() - start
    logger.info(
        "Code embedding complete",
        extra={
            "total": total,
            "cached": cached_count,
            "generated": generated_count,
            "duration_seconds": round(elapsed, 2),
        },
    )
    return {
        "total": total,
        "cached": cached_count,
        "generated": generated_count,
        "duration_seconds": round(elapsed, 2),
    }


# ── Theme embedding generation ───────────────────────────────────────────────


def _build_theme_text(node: dict) -> tuple[str, str]:
    """Build embedding text for a theme node."""
    name = node.get("name", "")
    definition = node.get("definition", "")
    tag = node.get("tag", "")
    text = f"{name}: {definition} [Tag: {tag}]"
    import hashlib

    ch = hashlib.sha256(text.encode()).hexdigest()[:16]
    return text, ch


def _collect_themes() -> list[dict]:
    """Load all draft/approved theme nodes from graph."""
    from graph import get_nodes_by_type_and_tag

    nodes = get_nodes_by_type_and_tag("theme", None)
    return [n for n in nodes if n.get("status") in ("draft", "approved")]


def _identify_uncached_themes(
    con: duckdb.DuckDBPyConnection,
    themes: list[dict],
    model_hash: str,
) -> list[tuple[str, str, str]]:
    """Return list of (entity_id, text, content_hash) needing encoding."""
    items = []
    for node in themes:
        text, ch = _build_theme_text(node)
        items.append((str(node["id"]), text, ch))
    ids = [item[0] for item in items]
    stored = _get_existing_cache_map_generic(con, ids, "theme", model_hash)
    return _identify_uncached(items, stored)


def generate_theme_embeddings(
    con: duckdb.DuckDBPyConnection,
    batch_size: int = 32,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Batch-generate embeddings for all uncached theme nodes."""
    start = time.perf_counter()

    themes = _collect_themes()
    total = len(themes)
    if total == 0:
        logger.info("No themes to embed")
        return {
            "total": 0,
            "cached": 0,
            "generated": 0,
            "duration_seconds": 0.0,
        }

    model_hash = get_model_hash()

    to_encode = _identify_uncached_themes(con, themes, model_hash)
    cached_count = total - len(to_encode)

    generated_count = _encode_and_store_generic(
        con,
        to_encode,
        "theme",
        model_hash,
        batch_size,
        desc="Embedding themes",
        unit="themes",
        progress_callback=progress_callback,
    )

    elapsed = time.perf_counter() - start
    logger.info(
        "Theme embedding complete",
        extra={
            "total": total,
            "cached": cached_count,
            "generated": generated_count,
            "duration_seconds": round(elapsed, 2),
        },
    )
    return {
        "total": total,
        "cached": cached_count,
        "generated": generated_count,
        "duration_seconds": round(elapsed, 2),
    }


# ── Interpretation embedding generation ──────────────────────────────────────


def _build_interpretation_text(node: dict) -> tuple[str, str]:
    """Build embedding text for an interpretation node."""
    name = node.get("name", "")
    narrative = node.get("data_json", {}).get("narrative", "")
    tags = node.get("data_json", {}).get("tags", [])
    tag_str = ",".join(tags) if isinstance(tags, list) else str(tags)
    text = f"{name}: {narrative} [Tags: {tag_str}]"
    import hashlib

    ch = hashlib.sha256(text.encode()).hexdigest()[:16]
    return text, ch


def _collect_interpretations() -> list[dict]:
    """Load all draft/approved interpretation nodes from graph."""
    from graph import get_nodes_by_type_and_tag

    nodes = get_nodes_by_type_and_tag("interpretation", None)
    return [n for n in nodes if n.get("status") in ("draft", "approved")]


def _identify_uncached_interpretations(
    con: duckdb.DuckDBPyConnection,
    interpretations: list[dict],
    model_hash: str,
) -> list[tuple[str, str, str]]:
    """Return list of (entity_id, text, content_hash) needing encoding."""
    items = []
    for node in interpretations:
        text, ch = _build_interpretation_text(node)
        items.append((str(node["id"]), text, ch))
    ids = [item[0] for item in items]
    stored = _get_existing_cache_map_generic(con, ids, "interpretation", model_hash)
    return _identify_uncached(items, stored)


def generate_interpretation_embeddings(
    con: duckdb.DuckDBPyConnection,
    batch_size: int = 32,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Batch-generate embeddings for all uncached interpretation nodes."""
    start = time.perf_counter()

    interpretations = _collect_interpretations()
    total = len(interpretations)
    if total == 0:
        logger.info("No interpretations to embed")
        return {
            "total": 0,
            "cached": 0,
            "generated": 0,
            "duration_seconds": 0.0,
        }

    model_hash = get_model_hash()

    to_encode = _identify_uncached_interpretations(con, interpretations, model_hash)
    cached_count = total - len(to_encode)

    generated_count = _encode_and_store_generic(
        con,
        to_encode,
        "interpretation",
        model_hash,
        batch_size,
        desc="Embedding interpretations",
        unit="interps",
        progress_callback=progress_callback,
    )

    elapsed = time.perf_counter() - start
    logger.info(
        "Interpretation embedding complete",
        extra={
            "total": total,
            "cached": cached_count,
            "generated": generated_count,
            "duration_seconds": round(elapsed, 2),
        },
    )
    return {
        "total": total,
        "cached": cached_count,
        "generated": generated_count,
        "duration_seconds": round(elapsed, 2),
    }
