"""Nodes: Groq client init, batch preparation, code/theme/interpretation inference.

Pure functions where possible.  ``existing_codes`` and ``tag_metadata`` are
external inputs provided by the orchestration layer via Hamilton's ``inputs``
dict.  ``groq_client.complete()`` is a read-only API call.
"""

from __future__ import annotations

import networkx as nx
import polars as pl  # noqa: F401
from pipeline.config import Config
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "init_groq_client",
    "prepare_code_batches",
    "infer_codes",
    "prepare_code_nodes",
    "prepare_theme_batches",
    "infer_themes",
    "prepare_theme_nodes",
    "prepare_interpretation_spans",
    "infer_interpretations",
    "prepare_interpretation_nodes",
]


def init_groq_client(config: Config) -> dict:
    """Return Groq client metadata (triggers lazy client init on first use)."""
    return {"model": config.groq_model, "timeout": config.groq_timeout}


def prepare_code_batches(
    load_exemplars: pl.LazyFrame, resolve_tag_dag: nx.DiGraph, config: Config
) -> list:
    """Group exemplars by tag into inference batches (max 15 per batch)."""
    from inference.batching import group_by_tag as _group

    class _Item:
        def __init__(self, eid, tag):
            self.id = eid
            self.tag = tag

    df = load_exemplars.select(["id", "tag"]).collect()
    items = [_Item(row["id"], str(row["tag"])) for row in df.iter_rows(named=True)]
    return _group(items, max_per_batch=config.batch_size, prefix="code")


def infer_codes(
    prepare_code_batches: list,
    init_groq_client: dict,
    build_ontology_graph: nx.DiGraph,
    config: Config,
    existing_codes: list | None = None,
    tag_metadata: dict | None = None,
    dirty_flags: dict | None = None,
) -> list:
    """Run Groq code inference on prepared batches.

    ``existing_codes``, ``tag_metadata``, and ``dirty_flags`` are provided
    by the orchestration layer via Hamilton ``inputs``.  Batches whose tag
    is NOT dirty are skipped (clean nodes served from cache).
    """
    from inference.groq_client import complete as _complete
    from inference.parsing import parse_code_response
    from inference.prompts import render_code_prompt
    from pipeline.dirty import is_dirty

    results = []
    for batch in prepare_code_batches:
        batch_tag = getattr(batch, "tag", "")
        if (
            dirty_flags is not None
            and batch_tag
            and not is_dirty(batch_tag, dirty_flags)
        ):
            logger.debug(
                "Skipping clean code batch",
                extra={"tag": batch_tag, "batch_id": getattr(batch, "batch_id", "")},
            )
            continue

        bundle = render_code_prompt(
            fewshot=None,
            ontology_path=[],
            tag_description="",
            existing_codes=existing_codes or [],
            exemplars=[
                {"id": str(it.id), "content": "", "keywords": []}
                for it in getattr(batch, "items", [])
            ],
        )
        try:
            response = _complete(bundle)
            codes = parse_code_response(response.choices[0].message.content)
            for c in codes:
                c.tag = batch_tag
            results.extend(codes)
        except Exception as e:
            logger.error("Code inference batch failed", extra={"error": str(e)})
    return results


def prepare_code_nodes(infer_codes: list, config: Config) -> list:
    """Deduplicate inferred codes into unique {name, definition, tag} dicts."""
    seen = set()
    nodes = []
    for c in infer_codes:
        key = (c.code_name, c.tag)
        if key not in seen:
            seen.add(key)
            nodes.append(
                {"name": c.code_name, "definition": c.definition, "tag": c.tag}
            )
    return nodes


def prepare_theme_batches(
    review_codes: list, resolve_tag_dag: nx.DiGraph, config: Config
) -> list:
    """Group approved codes by tag into theme inference batches (max 5 per batch)."""
    from inference.batching import group_by_tag as _group

    class _CodeItem:
        def __init__(self, cid, tag):
            self.id = cid
            self.tag = tag

    items = [
        _CodeItem(c.get("id", hash(c.get("name", ""))), c.get("tag", ""))
        for c in review_codes
    ]
    return _group(items, max_per_batch=5, prefix="theme")


def infer_themes(
    prepare_theme_batches: list,
    init_groq_client: dict,
    build_ontology_graph: nx.DiGraph,
    config: Config,
    existing_theme_nodes: list | None = None,
    tag_metadata: dict | None = None,
    dirty_flags: dict | None = None,
) -> list:
    """Run Groq theme inference on prepared code batches.

    ``dirty_flags`` is provided by the orchestration layer.  Batches whose
    tag is NOT dirty are skipped.
    """
    from inference.groq_client import complete as _complete
    from inference.parsing import parse_theme_response
    from inference.prompts import render_theme_prompt
    from pipeline.dirty import is_dirty

    results = []
    for batch in prepare_theme_batches:
        batch_tag = getattr(batch, "tag", "")
        if (
            dirty_flags is not None
            and batch_tag
            and not is_dirty(batch_tag, dirty_flags)
        ):
            logger.debug(
                "Skipping clean theme batch",
                extra={"tag": batch_tag, "batch_id": getattr(batch, "batch_id", "")},
            )
            continue

        bundle = render_theme_prompt(
            fewshot=None,
            ontology_path=[],
            tag_description="",
            codes=getattr(batch, "items", []),
        )
        try:
            response = _complete(bundle)
            themes = parse_theme_response(response.choices[0].message.content)
            results.extend(themes)
        except Exception as e:
            logger.error("Theme inference batch failed", extra={"error": str(e)})
    return results


def prepare_theme_nodes(infer_themes: list, config: Config) -> list:
    """Extract unique theme dicts from inferred themes."""
    return [
        {
            "theme_name": t.theme_name,
            "narrative": t.narrative,
            "code_ids": list(t.code_ids),
        }
        for t in infer_themes
    ]


def prepare_interpretation_spans(
    review_themes: list, resolve_tag_dag: nx.DiGraph, config: Config
) -> list:
    """Group ready tags into interpretation spans (place holder)."""
    return (
        [list(set(t.get("tag", "") for t in review_themes if t.get("tag")))]
        if review_themes
        else []
    )


def infer_interpretations(
    prepare_interpretation_spans: list,
    init_groq_client: dict,
    build_ontology_graph: nx.DiGraph,
    config: Config,
    tag_metadata: dict | None = None,
    dirty_flags: dict | None = None,
) -> list:
    """Run Groq interpretation inference on theme spans.

    ``dirty_flags`` is provided by the orchestration layer.  Spans where
    NONE of the constituent tags are dirty are skipped.
    """
    from inference.groq_client import complete as _complete
    from inference.parsing import parse_interpretation_response
    from inference.prompts import render_interpretation_prompt
    from pipeline.dirty import any_tag_dirty

    results = []
    for span in prepare_interpretation_spans:
        if dirty_flags is not None and span and not any_tag_dirty(span, dirty_flags):
            logger.debug(
                "Skipping clean interpretation span",
                extra={"tags": span},
            )
            continue

        bundle = render_interpretation_prompt(
            fewshot=None,
            tag_hierarchy=[],
            ontology_subtree=[],
            themes_by_tag={},
        )
        try:
            response = _complete(bundle)
            interps = parse_interpretation_response(response.choices[0].message.content)
            results.extend(interps)
        except Exception as e:
            logger.error(
                "Interpretation inference batch failed", extra={"error": str(e)}
            )
    return results


def prepare_interpretation_nodes(infer_interpretations: list, config: Config) -> list:
    """Extract unique interpretation dicts, deduplicating by name."""
    seen = set()
    nodes = []
    for i in infer_interpretations:
        if i.interpretation_name not in seen:
            seen.add(i.interpretation_name)
            nodes.append(
                {
                    "interpretation_name": i.interpretation_name,
                    "narrative": i.narrative,
                    "theme_ids": list(getattr(i, "theme_ids", [])),
                }
            )
    return nodes
