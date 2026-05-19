"""Per-span LLM callback for interpretation synthesis.

Holds the ``_InterpretationSpanItem`` dataclass (satisfies
``BatchableItem`` protocol) and ``_process_interpretation_span``,
the run_batches callback for one contiguous tag span.

Usage:
    from inference.interpretation_span_processor import (
        _InterpretationSpanItem,
        _process_interpretation_span,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial

from config import (
    fewshot_count,
    fewshot_enabled,
    fewshot_shuffle,
    interpretation_model,
    interpretation_temperature,
)
from utils.logging import get_logger

from .batch_processor import record_tokens
from .batching import Batch
from .fewshot_loader import load_fewshot
from .inference_status_types import ENTITY_THEME, STAGE_INTERPRETATION
from .interpretation_postprocess import (
    dedup_interpretation_names,
    flag_overlapping_themes,
    validate_theme_ids_exist,
)
from .interpretation_span_grouping import build_ontology_subtree, build_tag_hierarchy
from .parsing import InterpretationInference, parse_interpretation_response
from .prompts import PromptBundle, render_interpretation_prompt
from .retry import infer_batch_with_retry
from .status_updates import mark_success
from .theme_loading_for_interpretation import _ThemeRow

logger = get_logger(__name__)


@dataclass
class _InterpretationSpanItem:
    """A single item representing one contiguous span in a Batch.

    Satisfies the ``BatchableItem`` protocol via ``tag`` and ``id``.
    The batch contains exactly one such item; the process callback
    reads the full span metadata from it.
    """

    tag: str
    id: str
    span_tags: tuple[str, ...] = field(default_factory=tuple)
    themes_by_tag: dict[str, list[_ThemeRow]] = field(default_factory=dict)


def _render_interpretation_prompt_for_batch(
    batch: Batch,
    fewshot: list[dict] | None,
    tag_hierarchy: list[list[str]],
    ontology_subtree: str,
    themes_by_tag: dict,
) -> PromptBundle:
    """Render interpretation prompt for a single span batch."""
    return render_interpretation_prompt(
        fewshot=fewshot,
        tag_hierarchy=tag_hierarchy,
        ontology_subtree=ontology_subtree,
        themes_by_tag=themes_by_tag,
    )


def _process_interpretation_span(
    con,
    batch: Batch,
    tracker,
) -> list[InterpretationInference]:
    """Process a single span batch: render, infer, parse, post-process."""
    item: _InterpretationSpanItem = batch.items[0]

    themes_dict = {
        tag: [
            {
                "id": t.id,
                "theme_name": t.theme_name,
                "narrative": t.narrative,
                "code_ids": t.code_ids,
                "codes_detail": [
                    {
                        "name": cd["name"],
                        "definition": cd["definition"],
                        "exemplar_ids": cd["exemplar_ids"],
                        "exemplar_contents": cd["exemplar_contents"],
                    }
                    for cd in t.codes_detail
                ],
            }
            for t in themes
        ]
        for tag, themes in item.themes_by_tag.items()
    }
    fewshot = (
        load_fewshot(
            "interpretation_synthesis",
            count=fewshot_count(),
            shuffle=fewshot_shuffle(),
        )
        if fewshot_enabled()
        else None
    )

    responses = infer_batch_with_retry(
        batch=batch,
        render_fn=partial(
            _render_interpretation_prompt_for_batch,
            fewshot=fewshot,
            tag_hierarchy=build_tag_hierarchy(set(item.span_tags)),
            ontology_subtree=build_ontology_subtree(set(item.span_tags)),
            themes_by_tag=themes_dict,
        ),
        temperature=interpretation_temperature(),
        model=interpretation_model(),
        response_format={"type": "json_object"},
    )

    for resp in responses:
        record_tokens(resp, tracker, STAGE_INTERPRETATION, batch.batch_id)

    interpretations: list[InterpretationInference] = []
    for resp in responses:
        interpretations.extend(
            parse_interpretation_response(resp.choices[0].message.content)
        )

    interpretations = dedup_interpretation_names(interpretations)
    interpretations = flag_overlapping_themes(interpretations)

    valid_ids = {
        str(t.id) for tag_themes in item.themes_by_tag.values() for t in tag_themes
    }
    validate_theme_ids_exist(interpretations, valid_ids)

    for tag_themes in item.themes_by_tag.values():
        for theme in tag_themes:
            mark_success(con, theme.id, ENTITY_THEME, STAGE_INTERPRETATION)

    return interpretations
