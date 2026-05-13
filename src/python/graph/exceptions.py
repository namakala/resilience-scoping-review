"""Graph-specific exceptions for node/edge CRUD operations.

Provides a clear exception hierarchy for referential integrity violations
and other graph-domain error conditions.
"""


class ForeignKeyError(Exception):
    """Raised when a referenced node does not exist.

    For example, creating an edge whose source_id or target_id does not
    correspond to any row in the nodes table.
    """
