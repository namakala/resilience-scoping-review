"""Graph-specific exceptions for node/edge CRUD and traversal operations.

Provides a clear exception hierarchy for referential integrity violations,
cycle detection, and other graph-domain error conditions.
"""


class ForeignKeyError(Exception):
    """Raised when a referenced node does not exist.

    For example, creating an edge whose source_id or target_id does not
    correspond to any row in the nodes table.
    """


class CycleError(Exception):
    """Raised when a cycle is detected in the graph during traversal.

    The tag hierarchy must be a DAG. A cycle indicates corrupted data or
    an invalid mutation.
    """
