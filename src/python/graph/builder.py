"""Graph builder: construct NetworkX DiGraph from DuckDB nodes and edges.

Pure function — no side effects, no singleton access. Accepts a DuckDB
connection, returns fully populated DiGraph. Designed to be importable
by singleton lifecycle manager and test fixtures.
"""

import json
from typing import Optional

import duckdb
import networkx as nx
from utils.logging import get_logger

logger = get_logger(__name__)


def build_graph(con: duckdb.DuckDBPyConnection) -> nx.DiGraph:
    """Build a fresh NetworkX DiGraph from all nodes and edges in DuckDB.

    Args:
        con: Active DuckDB connection pointing to the session database.

    Returns:
        nx.DiGraph: Newly constructed graph with fully populated attributes.

    Raises:
        RuntimeError: If required tables are missing or queries fail.
    """
    G = nx.DiGraph()

    try:
        # Load nodes — select columns matching nodes schema
        node_rows = con.execute(
            "SELECT id, type, name, definition, tag, status FROM nodes"
        ).fetchall()

        for row in node_rows:
            node_id = row[0]
            attrs = {
                "type": row[1],
                "name": row[2],
                "definition": row[3],
                "tag": row[4],
                "status": row[5],
            }
            G.add_node(node_id, **attrs)

        # Load edges — select columns matching edges schema
        edge_rows = con.execute(
            "SELECT source_id, target_id, edge_type, metadata_json FROM edges"
        ).fetchall()

        for row in edge_rows:
            source_id = row[0]
            target_id = row[1]
            edge_type = row[2]
            metadata_json = row[3]

            metadata = _parse_metadata(metadata_json, source_id, target_id, edge_type)

            G.add_edge(
                source_id,
                target_id,
                type=edge_type,
                metadata=metadata,
            )

    except duckdb.Error as e:
        logger.error("Failed to build graph from DuckDB", extra={"error": str(e)})
        raise RuntimeError(
            "Graph construction failed — ensure database is initialized"
        ) from e

    return G


def _parse_metadata(
    metadata_json: Optional[str],
    source_id: int,
    target_id: int,
    edge_type: str,
) -> object | None:
    """Deserialize edge metadata_json, falling back to raw string on error."""
    if metadata_json is None:
        return None
    try:
        return json.loads(metadata_json)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(
            "Failed to parse edge metadata_json; storing raw string",
            extra={
                "edge": (source_id, target_id, edge_type),
                "error": str(e),
            },
        )
        return metadata_json
