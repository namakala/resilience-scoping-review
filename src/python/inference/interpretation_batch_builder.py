"""Build ``Batch`` objects from contiguous tag spans for interpretation synthesis.

Each span produces one ``Batch`` holding a single
``_InterpretationSpanItem``  with pre-loaded approved themes.

Usage:
    from inference.interpretation_batch_builder import build_interpretation_batches

    batches = build_interpretation_batches(spans)
"""

from __future__ import annotations

from utils.logging import get_logger

from .batching import Batch
from .interpretation_span_processor import _InterpretationSpanItem
from .theme_loading_for_interpretation import load_approved_themes_grouped

logger = get_logger(__name__)


def build_interpretation_batches(spans: list[set[str]]) -> list[Batch]:
    """Convert contiguous tag spans into ``Batch`` objects.

    Each batch holds one ``_InterpretationSpanItem``.  Spans with zero
    approved themes across all tags are skipped.
    """
    batches: list[Batch] = []
    for idx, span in enumerate(sorted(spans, key=lambda s: sorted(s)[0])):
        themes_by_tag = load_approved_themes_grouped(span)
        if not themes_by_tag:
            logger.info("No approved themes in span %s; skipping", sorted(span))
            continue
        first_tag = sorted(span)[0]
        item = _InterpretationSpanItem(
            tag=first_tag,
            id=f"interp_span_{idx:02d}",
            span_tags=tuple(sorted(span)),
            themes_by_tag=themes_by_tag,
        )
        batch = Batch(
            tag=first_tag,
            items=[item],
            batch_index=idx,
            total_batches=len(spans),
        )
        batch._prefix = "interp"
        batches.append(batch)
    return batches
