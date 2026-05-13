"""CRUD operations for graph nodes: create, read, update, delete.

Provides atomic insertion of nodes into DuckDB and in-memory NetworkX.
All operations respect the dual-representation architecture (ADR-004).
"""

import json
from pathlib import Path
from typing import Any, Optional

import duckdb
from persistence.duckdb_connection import get_connection
from utils.logging import get_logger

from .singleton import get_graph

logger = get_logger(__name__)


def create_node(
    node_type: str,
    name: str,
    definition: str,
    tag: Optional[str],
    status: str,
    data_json: Optional[dict[str, Any]] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Create a new node atomically in DuckDB and in-memory NetworkX graph.

    Inserts a row into the `nodes` table and adds a vertex to the global graph
    singleton with identical attributes. The node ID is auto-incremented by
    DuckDB and returned as an integer.

    Duplicate detection: a node with the same (type, name) pair already exists
    in the database is considered a duplicate and rejected with ValueError.
    The check is performed before insertion to provide early feedback.

    Args:
        node_type: One of 'code', 'theme', 'interpretation', 'tag'.
        name: Human-readable name for the node (unique within type).
        definition: Detailed description or narrative explaining the node.
        tag: Ontology tag this node belongs to (NULL for tag nodes themselves).
        status: Lifecycle status — for mutable nodes: 'draft', 'approved',
            'merged', 'rejected'; for tag nodes: 'immutable'.
        data_json: Optional JSON-serializable dict of flexible attributes.
            Stored as JSON string in DuckDB; retained as dict in NetworkX.
            Default: None (stored as NULL).
        db_path: Path to DuckDB file. Defaults to session DB location.

    Returns:
        int: The newly assigned node ID (auto-incremented primary key).

    Raises:
        ValueError: If a node with the same (type, name) already exists.
        duckdb.Error: If the database query fails (e.g., constraint violation,
            connection error). In such cases, no node is inserted and the
            in-memory graph remains unchanged.

    Example:
        >>> node_id = create_node(
        ...     node_type='code',
        ...     name='Transportation Barrier',
        ...     definition='Lack of reliable transport limits access',
        ...     tag='Problem.Cause',
        ...     status='draft',
        ...     data_json={'exemplar_count': 3}
        ... )
        >>> print(node_id)
        42
    """
    # Ensure graph is initialized (lazy build)
    G = get_graph(db_path)

    # Serialize data_json early to catch JSON errors before DB write
    data_json_str: Optional[str]
    if data_json is None:
        data_json_str = None
    else:
        try:
            data_json_str = json.dumps(data_json, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            logger.error(
                "Failed to serialize data_json to JSON",
                extra={"data_json": data_json, "error": str(e)},
            )
            raise ValueError(f"data_json not JSON-serializable: {e}") from e

    con = None
    try:
        con = get_connection(db_path)

        # 1. Duplicate check: (type, name) must be unique across all nodes
        row = con.execute(
            "SELECT 1 FROM nodes WHERE type = ? AND name = ? LIMIT 1",
            [node_type, name],
        ).fetchone()
        if row is not None:
            logger.warning(
                "Duplicate node creation attempted",
                extra={"node_type": node_type, "node_name": name},
            )
            raise ValueError(f"Node {node_type}/{name} already exists")

        # 2. Insert into DuckDB nodes table
        # Insert with explicit columns; id auto-increments via sequence,
        # created_at defaults to CURRENT_TIMESTAMP.
        con.execute(
            """
            INSERT INTO nodes (type, name, definition, tag, status, data_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                node_type,
                name,
                definition,
                tag,
                status,
                data_json_str,
            ],
        )

        # 3. Retrieve the generated node ID.
        # Try currval('nodes_id_seq'). If that fails (e.g., no prior nextval
        # in this session), fall back to MAX(id).
        try:
            node_id_row = con.execute("SELECT currval('nodes_id_seq')").fetchone()
            node_id = int(node_id_row[0]) if node_id_row else None
        except duckdb.Error:
            # Fallback: query max id (not safe under concurrency, but should
            # never happen in single-threaded session after our insert)
            max_row = con.execute("SELECT MAX(id) FROM nodes").fetchone()
            node_id = int(max_row[0]) if max_row and max_row[0] is not None else None

        if node_id is None:
            raise RuntimeError("Failed to retrieve node ID after insert")

        # 4. Add to in-memory NetworkX graph with identical attributes
        # Store data_json as the original dict (not the JSON string) for
        # consistency with sync_node behavior and downstream query convenience.
        G.add_node(
            node_id,
            type=node_type,
            name=name,
            definition=definition,
            tag=tag,
            status=status,
            data_json=data_json,  # dict or None
        )

        logger.info(
            "Node created",
            extra={
                "node_id": node_id,
                "node_type": node_type,
                "node_name": name,
                "tag": tag,
                "status": status,
            },
        )
        return node_id

    except duckdb.Error as e:
        logger.error(
            "create_node: database operation failed",
            extra={"node_type": node_type, "node_name": name, "error": str(e)},
        )
        raise
    finally:
        if con:
            con.close()
