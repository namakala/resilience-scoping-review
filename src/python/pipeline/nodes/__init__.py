"""Node functions for the Hamilton DAG.

Each module defines pure functions that Hamilton auto-discovers as DAG nodes.
Dependencies are resolved by matching parameter names to upstream function names.

Groups:
- ``artifact_nodes`` — loading raw data
- ``embedding_nodes`` — embedding model init + exemplar/keyword embedding
- ``index_nodes`` — BM25 + ontology graph construction
- ``retrieval_nodes`` — hybrid candidate retrieval
- ``inference_nodes`` — Groq client init, prompt building,
  code/theme/interpretation inference
- ``review_nodes`` — HITL review stubs
- ``export_nodes`` — result export
"""

from . import artifact_nodes as artifact_nodes
from . import embedding_nodes as embedding_nodes
from . import export_nodes as export_nodes
from . import index_nodes as index_nodes
from . import inference_nodes as inference_nodes
from . import retrieval_nodes as retrieval_nodes
from . import review_nodes as review_nodes

__all__ = [
    "artifact_nodes",
    "embedding_nodes",
    "export_nodes",
    "index_nodes",
    "inference_nodes",
    "retrieval_nodes",
    "review_nodes",
]
