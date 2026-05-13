"""Context manager for atomic batch graph operations.

Wraps multiple node/edge CRUD calls in a single DuckDB transaction
with NetworkX snapshot/restore for dual-representation consistency.

Usage:
    with graph_transaction(db_path=...):
        nid = create_node(...)
        create_edge(nid, ..., ...)
        # On any exception: both DuckDB and NetworkX roll back.
"""

import copy
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

import duckdb
from persistence.duckdb_connection import get_connection
from utils.logging import get_logger

from . import singleton

logger = get_logger(__name__)

# Context variables so CRUD functions detect and share the tx connection.
_active_tx_conn: ContextVar[Optional[duckdb.DuckDBPyConnection]] = ContextVar(
    "_active_tx_conn", default=None
)
_active_tx_db_path: ContextVar[Optional[Path]] = ContextVar(
    "_active_tx_db_path", default=None
)


class GraphTransactionError(RuntimeError):
    """Raised when a transaction operation is invalid (e.g., nesting)."""


def get_active_connection() -> Optional[duckdb.DuckDBPyConnection]:
    """Return the active transaction connection, or *None* outside a tx."""
    return _active_tx_conn.get()


def is_in_transaction() -> bool:
    """Return *True* if the current call is inside a ``graph_transaction``."""
    return _active_tx_conn.get() is not None


class graph_transaction:
    """Context manager for atomic batch graph operations.

    On entry:
    - Initialises the NetworkX graph (lazy) and takes a deep copy.
    - Opens a DuckDB connection and executes ``BEGIN TRANSACTION``.

    On success exit:
    - Executes ``COMMIT``; NetworkX changes are kept.

    On error exit:
    - Executes ``ROLLBACK``; NetworkX graph is restored from the snapshot.
    - Traversal cache is cleared.

    Nested usage raises ``GraphTransactionError``.
    A deadlock on ``COMMIT`` is retried once automatically.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path
        self._con: Optional[duckdb.DuckDBPyConnection] = None
        self._snapshot = None
        self._entered = False

    def __enter__(self) -> "graph_transaction":
        if is_in_transaction():
            raise GraphTransactionError("Nested graph transactions are not supported")

        # Ensure the graph is built, then snapshot it.
        G = singleton.get_graph(self._db_path)
        self._snapshot = copy.deepcopy(G)

        # Open connection and begin the database transaction.
        self._con = get_connection(self._db_path)
        self._con.execute("BEGIN TRANSACTION")

        _active_tx_conn.set(self._con)
        _active_tx_db_path.set(self._db_path)
        self._entered = True

        logger.debug("graph_transaction started")
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[object],
    ) -> None:
        self._entered = False
        try:
            if exc_type is not None:
                self._rollback()
                logger.info(
                    "graph_transaction rolled back",
                    extra={"exc_type": exc_type.__name__},
                )
            else:
                self._commit()
                logger.debug("graph_transaction committed")
        finally:
            _active_tx_conn.set(None)
            _active_tx_db_path.set(None)
            if self._con is not None:
                try:
                    self._con.close()
                except duckdb.Error:
                    logger.warning("Failed to close transaction connection")

    def _rollback(self) -> None:
        """Roll back DuckDB and restore in-memory graph from snapshot."""
        if self._con is not None:
            try:
                self._con.execute("ROLLBACK")
            except duckdb.Error as e:
                logger.error("DuckDB rollback failed", extra={"error": str(e)})
        if self._snapshot is not None:
            singleton._graph = self._snapshot
            from .traversal import clear_traversal_cache

            clear_traversal_cache()

    def _commit(self) -> None:
        """Commit DuckDB transaction; retry once on deadlock."""
        if self._con is None:
            return
        try:
            self._con.execute("COMMIT")
        except duckdb.Error as e:
            err_str = str(e).lower()
            if "lock" in err_str:
                logger.warning(
                    "Deadlock on commit, retrying once",
                    extra={"error": str(e)},
                )
                try:
                    self._con.execute("COMMIT")
                    return
                except duckdb.Error as e2:
                    self._rollback()
                    raise RuntimeError(
                        "Transaction commit failed after " f"deadlock retry: {e2}"
                    ) from e2
            self._rollback()
            raise RuntimeError(f"Transaction commit failed: {e}") from e
