"""Group items by tag into fixed-size batches for LLM inference.

Usage:
    from inference.batching import group_by_tag

    batches = group_by_tag(exemplars, max_per_batch=15)
    for batch in batches:
        print(batch.batch_id, batch.item_count)
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from utils.logging import get_logger

logger = get_logger(__name__)


@runtime_checkable
class BatchableItem(Protocol):
    """Protocol for items that can be grouped into batches.

    Any object with ``.tag`` (str) and ``.id`` (int or str) satisfies
    this protocol at runtime via structural subtyping.
    """

    tag: str
    id: int | str


@dataclass
class Batch:
    """A single batch of items sharing a parent tag.

    Attributes
    ----------
    tag : str
        The parent tag for all items in this batch.
    items : list
        The items assigned to this batch.
    batch_index : int
        0-based index of this batch among all batches for its tag.
    total_batches : int
        Total number of batches created for this tag.
    item_count : int
        Number of items in this batch (computed from ``items``).
    """

    tag: str
    items: list
    batch_index: int
    total_batches: int
    item_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.item_count = len(self.items)

    @property
    def batch_id(self) -> str:
        """Return a human-readable batch identifier.

        Format: ``{prefix}_{tag}_batch_{batch_index:02d}`` where
        *prefix* is the *prefix* argument passed to ``group_by_tag``
        (default ``"tag"``).

        The tag's dots are preserved to keep the ontology path visible
        in the identifier.
        """
        return f"{self._prefix}_{self.tag}_batch_{self.batch_index:02d}"

    # Internal: set by group_by_tag to avoid threading prefix through
    # every constructor call. Not part of the public interface.
    _prefix: str = field(default="tag", repr=False)


def _chunk_list(items: list, chunk_size: int) -> list[list]:
    """Split *items* into chunks of at most *chunk_size*.

    The last chunk may be smaller. Returns a list of lists.
    """
    result: list[list] = []
    for start in range(0, len(items), chunk_size):
        result.append(items[start : start + chunk_size])
    return result


def group_items_by_tag(items: list) -> dict[str, list]:
    """Group *items* by ``.tag`` into a plain dict.

    Items with a falsy ``.tag`` get key ``""``. The caller decides
    how to handle empty tags (raise, skip, etc.).  Insertion order
    is preserved (Python 3.7+).

    Returns
    -------
    dict[str, list]
        Mapping from tag string to list of items sharing that tag.
    """
    groups: dict[str, list] = defaultdict(list)
    for item in items:
        groups[item.tag or ""].append(item)
    return dict(groups)


def group_by_tag(
    items: list,
    max_per_batch: int = 15,
    prefix: str = "tag",
) -> list[Batch]:
    """Group *items* by ``.tag`` and split into batches of *max_per_batch*.

    Items without a truthy ``.tag`` are silently skipped. Items within
    each tag are sorted by ``.id`` (ascending) before chunking. Batch
    order preserves the first-appearance order of tags.

    Parameters
    ----------
    items :
        Iterable of objects with ``.tag`` (str) and ``.id`` (int or
        str) attributes. Passing objects that don't satisfy the
        ``BatchableItem`` protocol will raise ``AttributeError``.
    max_per_batch :
        Maximum number of items per batch (default ``15``). Must be >= 1.
    prefix :
        Prefix string embedded in each batch's ``batch_id`` property
        (default ``"tag"``).

    Returns
    -------
    list[Batch]
        Flat list of ``Batch`` objects, one per chunk.

    Raises
    ------
    AttributeError
        If any item lacks a ``.tag`` or ``.id`` attribute.
    """
    if max_per_batch < 1:
        raise ValueError(f"max_per_batch must be >= 1, got {max_per_batch}")

    # Group by tag, preserving insertion order (Python 3.7+)
    items_by_tag = group_items_by_tag(items)
    items_by_tag.pop("", None)  # group_by_tag silently skips falsy tags

    batches: list[Batch] = []
    for tag, tag_items in items_by_tag.items():
        # Sort by id ascending for deterministic ordering
        tag_items.sort(key=lambda i: i.id)

        chunks = _chunk_list(tag_items, max_per_batch)
        total = len(chunks)
        for idx, chunk in enumerate(chunks):
            batch = Batch(
                tag=tag,
                items=chunk,
                batch_index=idx,
                total_batches=total,
            )
            batch._prefix = prefix
            batches.append(batch)

        logger.info("Prepared %d batches for tag %s", total, tag)

    return batches


def split_batch_in_half(batch: Batch) -> list[Batch]:
    """Split *batch* items into two roughly equal halves.

    First half gets ``ceil(N/2)`` items; second gets remainder.
    ``batch_index`` and ``total_batches`` are set appropriately.
    The original batch's ``_prefix`` is preserved.
    """
    items = batch.items
    mid = (len(items) + 1) // 2
    half1 = Batch(
        tag=batch.tag,
        items=items[:mid],
        batch_index=0,
        total_batches=2,
    )
    half2 = Batch(
        tag=batch.tag,
        items=items[mid:],
        batch_index=1,
        total_batches=2,
    )
    prefix = getattr(batch, "_prefix", "tag")
    half1._prefix = prefix
    half2._prefix = prefix
    return [half1, half2]


__all__ = [
    "Batch",
    "BatchableItem",
    "group_by_tag",
    "group_items_by_tag",
    "split_batch_in_half",
]
