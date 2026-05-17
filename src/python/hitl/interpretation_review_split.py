"""Split action handlers for interpretation review HITL CLI.

``handle_split_interpretation`` divides an interpretation into two by
letting the user select a subset of themes for the first new
interpretation; the remaining themes form the second. Both new
interpretations must have contiguous ``tag_spans``. The original
interpretation is marked ``merged`` with ``derived-from`` edges to the
new nodes. All changes are atomic within a single DuckDB transaction.

``handle_split_interpretation_regroup`` is the same operation but with
LLM re-inference: each group of themes is sent to the LLM to generate
a new interpretation name, narrative, and key insights.  The original
is marked ``superseded``.
"""

import copy
import json
from pathlib import Path
from typing import Any, Optional

import duckdb
from config import interpretation_model, interpretation_temperature
from graph import clear_traversal_cache, create_edge, create_node, rebuild_graph
from graph.singleton import get_graph
from graph.transactions import _active_tx_conn, _active_tx_db_path
from inference.parsing import InterpretationInference, parse_interpretation_response
from inference.prompts import PromptBundle
from inference.retry import call_complete_with_retry
from ontology import is_contiguous_subtree
from persistence.state_updates import increment_user_action_count
from semantic.embedding_generation import generate_interpretation_embeddings
from utils.logging import get_logger

from .user_action_log import log_user_action

logger = get_logger(__name__)

__all__ = [
    "handle_split_interpretation",
    "handle_split_interpretation_regroup",
]


def _compute_tag_spans(
    theme_ids: list[int],
    con: duckdb.DuckDBPyConnection,
) -> set[str]:
    """Compute the union of tags for a set of themes.

    Each theme's tag is looked up from the nodes table.
    """
    tags: set[str] = set()
    for tid in theme_ids:
        row = con.execute("SELECT tag FROM nodes WHERE id = ?", [tid]).fetchone()
        if row:
            tags.add(str(row[0]))
    return tags


def _build_data_json(tag_spans: set[str]) -> dict[str, Any]:
    """Build the ``data_json`` payload dict for an interpretation node."""
    return {"tag_spans": sorted(tag_spans)}


def handle_split_interpretation(
    con: duckdb.DuckDBPyConnection,
    interp: dict[str, Any],
    first_theme_ids: list[int],
    second_theme_ids: list[int],
    first_name: str,
    second_name: str,
    first_narrative: str,
    second_narrative: str,
    db_path: Optional[Path] = None,
) -> tuple[int, int]:
    """Split *interp* into two new interpretations.

    The original interpretation is marked ``merged``. Two new
    interpretation nodes are created as ``draft`` with ``spans`` edges
    to their respective themes. ``derived-from`` edges link the original
    to both new nodes.

    Args:
        con: Active DuckDB connection.
        interp: Original interpretation dict (expects keys ``id``,
            ``name``, ``narrative``, ``tag``, ``data_json``).
        first_theme_ids: Theme IDs for the first new interpretation.
        second_theme_ids: Theme IDs for the second new interpretation.
        first_name: Name for the first new interpretation.
        second_name: Name for the second new interpretation.
        first_narrative: Narrative for the first new interpretation.
        second_narrative: Narrative for the second new interpretation.
        db_path: Optional DuckDB path for graph module.

    Returns:
        Tuple of ``(first_new_id, second_new_id)``.

    Raises:
        ValueError: If either theme list is empty or tag_spans are
            non-contiguous.
    """
    source_id = interp["id"]

    if not first_theme_ids or not second_theme_ids:
        raise ValueError("Both split interpretations must have at least one theme.")

    # Compute and validate tag_spans for both branches
    first_tags = _compute_tag_spans(first_theme_ids, con)
    second_tags = _compute_tag_spans(second_theme_ids, con)

    if len(first_tags) > 1 and not is_contiguous_subtree(first_tags):
        raise ValueError(
            f"First split has non-contiguous tag_spans: {sorted(first_tags)}"
        )
    if len(second_tags) > 1 and not is_contiguous_subtree(second_tags):
        raise ValueError(
            f"Second split has non-contiguous tag_spans: {sorted(second_tags)}"
        )

    # Determine root tags (first tag alphabetically as fallback)
    first_root = sorted(first_tags)[0] if first_tags else interp.get("tag", "")
    second_root = sorted(second_tags)[0] if second_tags else interp.get("tag", "")

    G = get_graph(db_path)
    snapshot = copy.deepcopy(G)

    con.execute("BEGIN TRANSACTION")
    _active_tx_conn.set(con)
    _active_tx_db_path.set(db_path)
    committed = False

    try:
        # Mark original as merged
        dj = interp.get("data_json") or {}
        dj["merged_info"] = {
            "split_into_first_name": first_name,
            "split_into_second_name": second_name,
        }
        con.execute(
            "UPDATE nodes SET status = 'merged', data_json = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [json.dumps(dj, ensure_ascii=False), source_id],
        )

        # Create first new interpretation
        first_id = create_node(
            node_type="interpretation",
            name=first_name,
            definition=first_narrative,
            tag=first_root,
            status="draft",
            data_json=_build_data_json(first_tags),
            db_path=db_path,
        )

        # Create second new interpretation
        second_id = create_node(
            node_type="interpretation",
            name=second_name,
            definition=second_narrative,
            tag=second_root,
            status="draft",
            data_json=_build_data_json(second_tags),
            db_path=db_path,
        )

        # Delete existing spans edges from original
        con.execute(
            "DELETE FROM edges WHERE source_id = ? AND edge_type = 'spans'",
            [source_id],
        )

        # Create new spans edges
        for tid in first_theme_ids:
            create_edge(
                source_id=first_id,
                target_id=tid,
                edge_type="spans",
                db_path=db_path,
            )
        for tid in second_theme_ids:
            create_edge(
                source_id=second_id,
                target_id=tid,
                edge_type="spans",
                db_path=db_path,
            )

        # Create derived-from edges
        create_edge(
            source_id=source_id,
            target_id=first_id,
            edge_type="derived-from",
            db_path=db_path,
        )
        create_edge(
            source_id=source_id,
            target_id=second_id,
            edge_type="derived-from",
            db_path=db_path,
        )

        log_user_action(
            con,
            "split",
            source_id,
            old_value={
                "status": interp.get("status", "draft"),
                "theme_ids": first_theme_ids + second_theme_ids,
            },
            new_value={
                "status": "merged",
                "split_into": [first_id, second_id],
            },
        )
        committed = True
        con.execute("COMMIT")
        increment_user_action_count(con)

    except Exception:
        if not committed:
            try:
                con.execute("ROLLBACK")
            except duckdb.TransactionException:
                logger.warning("Rollback failed; transaction may already be closed")
        raise

    finally:
        _active_tx_conn.set(None)
        _active_tx_db_path.set(None)
        if not committed:
            from graph import singleton as _g_singleton

            _g_singleton._graph = snapshot
            clear_traversal_cache()

    rebuild_graph(db_path)

    logger.info(
        "Interpretation %d split into %d and %d",
        source_id,
        first_id,
        second_id,
    )

    return first_id, second_id


# ── Regroup split with LLM re-inference ───────────────────────────────


def _themes_to_interpretation_context(
    con: duckdb.DuckDBPyConnection,
    theme_ids: list[int],
) -> str:
    """Build a text description of the given themes for the LLM prompt.

    Each theme's name, narrative, tag, and code details are included.
    """
    import io

    buf = io.StringIO()
    for tid in theme_ids:
        row = con.execute(
            "SELECT id, name, definition, tag, data_json "
            "FROM nodes WHERE id = ? AND type = 'theme'",
            [tid],
        ).fetchone()
        if not row:
            continue
        buf.write(f"- Theme: {row[1]}\n")
        buf.write(f"  ID: {row[0]}\n")
        buf.write(f"  Narrative: {row[2]}\n")
        buf.write(f"  Tag: {row[3]}\n")
        dj = json.loads(row[4]) if row[4] else {}
        code_ids = dj.get("code_ids", [])
        if code_ids:
            buf.write(f"  Code IDs: {', '.join(str(c) for c in code_ids)}\n")
            for cid in code_ids:
                c_row = con.execute(
                    "SELECT name, definition FROM nodes WHERE id = ?",
                    [int(cid)],
                ).fetchone()
                if c_row:
                    buf.write(f"    - {c_row[0]}: {c_row[1]}\n")
        buf.write("\n")
    return buf.getvalue()


def _infer_interpretation_for_group(
    con: duckdb.DuckDBPyConnection,
    theme_ids: list[int],
    batch_id: str,
) -> InterpretationInference:
    """Call LLM to infer a single interpretation from a group of themes.

    Returns a single ``InterpretationInference`` item.  Raises if LLM
    returns no interpretations.
    """
    theme_context = _themes_to_interpretation_context(con, theme_ids)

    system_prompt = (
        "You are a qualitative research assistant performing thematic "
        "analysis. Synthesize one cross-cutting interpretation from the "
        "provided themes.\n\n"
        "Respond with a valid JSON object wrapped in ```json ... ```.\n"
        "No other text, explanations, or markdown outside the fence.\n"
        'Return: {"interpretations": [{"interpretation_name": "...", '
        '"narrative": "...", "theme_ids": [...], '
        '"key_insights": ["...", "..."]}]}\n\n'
        "Each interpretation_name must be at least 15 words (a brief "
        "narrative capturing the cross-cutting insight).\n"
        "include all provided theme_ids in the output."
    )

    user_prompt = (
        "## Themes\n\n"
        f"{theme_context}\n"
        f"Synthesize a single interpretation from these {len(theme_ids)} "
        "themes."
    )

    prompt = PromptBundle(system=system_prompt, user=user_prompt)
    response = call_complete_with_retry(
        prompt,
        batch_id=batch_id,
        tag="interpretation_split",
        model=interpretation_model(),
        temperature=interpretation_temperature(),
        response_format={"type": "json_object"},
    )
    results = parse_interpretation_response(response.choices[0].message.content)
    if not results:
        raise ValueError(f"LLM returned no interpretations for batch {batch_id}")
    return results[0]


def _build_data_json_regroup(tag_spans: set[str]) -> dict[str, Any]:
    """Build ``data_json`` for a re-inferred interpretation node."""
    return {"tag_spans": sorted(tag_spans)}


def handle_split_interpretation_regroup(
    con: duckdb.DuckDBPyConnection,
    interp: dict[str, Any],
    groups: list[list[int]],
    db_path: Optional[Path] = None,
) -> list[int]:
    """Split *interp* into N new interpretations with LLM re-inference.

    Each group of themes is sent to the LLM to generate a new name,
    narrative, and key insights. The original interpretation is marked
    ``superseded``.

    Args:
        con: Active DuckDB connection.
        interp: Original interpretation dict.
        groups: List of theme-ID groups. Each group becomes one new
            interpretation. Must contain at least 2 groups.
        db_path: Optional DuckDB path for graph module.

    Returns:
        List of new interpretation node IDs, one per group.

    Raises:
        ValueError: If fewer than 2 groups, any group is empty, or
            any group has non-contiguous tag_spans.
    """
    source_id = interp["id"]

    if len(groups) < 2:
        raise ValueError("Split requires at least 2 groups of themes.")
    for i, g in enumerate(groups):
        if not g:
            raise ValueError(f"Group {i+1} must have at least one theme.")

    # Pre-compute per-group metadata (tag_spans, root tag)
    group_meta: list[dict[str, Any]] = []
    for i, theme_ids in enumerate(groups):
        tags = _compute_tag_spans(theme_ids, con)
        if len(tags) > 1 and not is_contiguous_subtree(tags):
            raise ValueError(
                f"Group {i+1} has non-contiguous tag_spans: {sorted(tags)}"
            )
        root_tag = sorted(tags)[0] if tags else interp.get("tag", "")
        group_meta.append(
            {
                "theme_ids": theme_ids,
                "tags": tags,
                "root_tag": root_tag,
            }
        )

    all_theme_ids = [tid for g in groups for tid in g]

    G = get_graph(db_path)
    snapshot = copy.deepcopy(G)

    # ── Transaction 1: Mark original as superseded ───────────────────
    con.execute("BEGIN TRANSACTION")
    _active_tx_conn.set(con)
    _active_tx_db_path.set(db_path)
    committed = False

    try:
        dj = interp.get("data_json") or {}
        dj["merged_info"] = {
            "split_groups": groups,
        }
        con.execute(
            "UPDATE nodes SET status = 'superseded', data_json = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [json.dumps(dj, ensure_ascii=False), source_id],
        )

        con.execute(
            "DELETE FROM edges WHERE source_id = ? AND edge_type = 'spans'",
            [source_id],
        )

        committed = True
        con.execute("COMMIT")
    except Exception:
        if not committed:
            try:
                con.execute("ROLLBACK")
            except duckdb.TransactionException:
                logger.warning(
                    "Rollback failed during interpretation split; "
                    "transaction may already be closed"
                )
        raise
    finally:
        _active_tx_conn.set(None)
        _active_tx_db_path.set(None)
        if not committed:
            from graph import singleton as _g_singleton

            _g_singleton._graph = snapshot
            clear_traversal_cache()

    # ── Step 2: LLM re-inference for each group ──────────────────────
    try:
        interp_results = []
        for i, gd in enumerate(group_meta):
            result = _infer_interpretation_for_group(
                con, gd["theme_ids"], f"split_{source_id}_part{i+1}"
            )
            interp_results.append(result)
    except Exception as exc:
        logger.error(
            "Interpretation re-inference failed for split (interp %d): %s",
            source_id,
            exc,
        )
        rebuild_graph(db_path)
        raise

    # ── Step 3: Create nodes inside a new transaction ─────────────────
    node_ids: list[int] = []
    con.execute("BEGIN TRANSACTION")
    _active_tx_conn.set(con)
    _active_tx_db_path.set(db_path)
    committed = False

    try:
        for gd, interp_result in zip(group_meta, interp_results):
            nid = create_node(
                node_type="interpretation",
                name=interp_result.interpretation_name,
                definition=interp_result.narrative,
                tag=gd["root_tag"],
                status="draft",
                data_json=_build_data_json_regroup(gd["tags"]),
                db_path=db_path,
            )
            node_ids.append(nid)

            for tid in gd["theme_ids"]:
                create_edge(
                    source_id=nid,
                    target_id=tid,
                    edge_type="spans",
                    db_path=db_path,
                )

            create_edge(
                source_id=source_id,
                target_id=nid,
                edge_type="derived-from",
                db_path=db_path,
            )

        log_user_action(
            con,
            "split",
            source_id,
            old_value={
                "status": interp.get("status", "draft"),
                "theme_ids": all_theme_ids,
            },
            new_value={
                "status": "superseded",
                "split_into": node_ids,
            },
        )
        committed = True
        con.execute("COMMIT")
        increment_user_action_count(con)
    except Exception:
        if not committed:
            try:
                con.execute("ROLLBACK")
            except duckdb.TransactionException:
                logger.warning(
                    "Rollback failed during interpretation node creation; "
                    "transaction may already be closed"
                )
        raise
    finally:
        _active_tx_conn.set(None)
        _active_tx_db_path.set(None)
        if not committed:
            from graph import singleton as _g_singleton

            _g_singleton._graph = snapshot
            clear_traversal_cache()

    # ── Step 4: Generate embeddings ──────────────────────────────────
    try:
        generate_interpretation_embeddings(con)
    except Exception as exc:
        logger.warning(
            "Embedding generation failed after interpretation split: %s",
            exc,
        )

    rebuild_graph(db_path)

    logger.info(
        "Interpretation %d split into %d new nodes via re-inference",
        source_id,
        len(node_ids),
    )

    return node_ids
