"""Post-processing validators for interpretation synthesis results.

Provides pure-function validators: deduplicate interpretation names,
flag overlapping theme references, and validate theme-ID belonging.

Usage:
    from inference.interpretation_postprocess import (
        dedup_interpretation_names,
        flag_overlapping_themes,
        validate_theme_ids_exist,
    )

    interps = dedup_interpretation_names(interps)
    interps = flag_overlapping_themes(interps)
    validate_theme_ids_exist(interps, valid_theme_ids)
"""

from __future__ import annotations

from utils.logging import get_logger

from .parsing import InterpretationInference

logger = get_logger(__name__)

__all__ = [
    "dedup_interpretation_names",
    "flag_overlapping_themes",
    "validate_theme_ids_exist",
]


def dedup_interpretation_names(
    interpretations: list[InterpretationInference],
) -> list[InterpretationInference]:
    """Deduplicate interpretation names by appending ``_1``, ``_2`` on collision.

    Logs a warning on each rename. Mutates ``interpretation_name`` in
    place and returns the same list for convenience.
    """
    seen: set[str] = set()
    for interp in interpretations:
        name = interp.interpretation_name
        if name in seen:
            counter = 1
            while f"{name}_{counter}" in seen:
                counter += 1
            interp.interpretation_name = f"{name}_{counter}"
            logger.warning(
                "Duplicate interpretation name resolved: '%s' -> '%s'",
                name,
                interp.interpretation_name,
            )
        seen.add(interp.interpretation_name)
    return interpretations


def flag_overlapping_themes(
    interpretations: list[InterpretationInference],
) -> list[InterpretationInference]:
    """Log a warning if two interpretations reference the same theme ID.

    Each theme should ideally belong to exactly one interpretation.
    This is a non-blocking advisory for the HITL review stage.
    """
    theme_to_interp: dict[str, str] = {}
    for interp in interpretations:
        for tid in interp.theme_ids:
            if tid in theme_to_interp:
                logger.warning(
                    "Theme '%s' appears in both '%s' and '%s'",
                    tid,
                    theme_to_interp[tid],
                    interp.interpretation_name,
                )
            else:
                theme_to_interp[tid] = interp.interpretation_name
    return interpretations


def validate_theme_ids_exist(
    interpretations: list[InterpretationInference],
    valid_theme_ids: set[str],
) -> list[InterpretationInference]:
    """Verify every ``theme_id`` in every interpretation exists in *valid_theme_ids*.

    Logs a warning for any theme ID that falls outside the span's
    approved theme set (LLM hallucination detection).
    """
    for interp in interpretations:
        for tid in interp.theme_ids:
            if tid not in valid_theme_ids:
                logger.warning(
                    "Interpretation '%s' references theme '%s' "
                    "not in the current span's approved themes",
                    interp.interpretation_name,
                    tid,
                )
    return interpretations
