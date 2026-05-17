"""Parse and validate structured LLM responses against Pydantic schemas.

Usage:
    from inference.parsing import parse_code_response

    raw = '{"codes": [{"exemplar_ids": ["E001"], "code_name": "...", ...}]}'
    codes = parse_code_response(raw)
    for c in codes:
        print(c.code_name)
"""

import json
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator
from utils.exceptions import ParseError
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "CodeInference",
    "CodeClusterResponse",
    "ThemeInference",
    "InterpretationInference",
    "parse_code_response",
    "parse_theme_response",
    "parse_interpretation_response",
]

# ── Pydantic Schemas ──────────────────────────────────────────────────────


class CodeInference(BaseModel):
    """A single code generated from one exemplar."""

    exemplar_id: str
    code_name: str
    definition: str
    supporting_quote: str
    related_existing_codes: list[str] = Field(default_factory=list)
    tag: str = ""


class CodeClusterResponse(BaseModel):
    """A cluster code returned by LLM with array of exemplar IDs.

    This intermediate type is parsed from the LLM response before expanding
    into individual CodeInference objects.
    """

    exemplar_ids: list[str]
    code_name: str
    definition: str
    related_existing_codes: list[str] = Field(default_factory=list)


class ThemeInference(BaseModel):
    """A theme grouping multiple related codes."""

    theme_name: str
    narrative: str
    code_ids: list[str]
    tag: str = ""


class InterpretationInference(BaseModel):
    """A cross-tag interpretation synthesizing multiple themes."""

    interpretation_name: str
    narrative: str
    theme_ids: list[str]
    key_insights: list[str]
    tag: str = ""

    @field_validator("theme_ids", mode="before")
    @classmethod
    def coerce_ids_to_strs(cls, v):
        return [str(x) for x in v]


# ── Wrapper keys (must match template Output Schema keys) ─────────────────

_CODE_WRAPPER = "codes"
_THEME_WRAPPER = "themes"
_INTERP_WRAPPER = "interpretations"

# ── Internal helpers ──────────────────────────────────────────────────────


def _strip_fences(text: str) -> str:
    """Remove markdown code fences (`` ```json `` or ``````)."""
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()


def _has_trailing_comma(text: str) -> bool:
    """Check if JSON text has trailing comma before closing bracket/brace."""
    return bool(re.search(r",\s*[}\]]", text))


def _unwrap(data: dict[str, Any], wrapper_key: str) -> list[dict[str, Any]]:
    """Extract the item list from a wrapper object.

    Parameters
    ----------
    data : dict
        Parsed JSON object, expected to contain ``wrapper_key``.
    wrapper_key : str
        Key holding the item array (e.g. ``"codes"``).

    Returns
    -------
    list[dict]
        The list of item dicts.

    Raises
    ------
    ParseError
        If the wrapper key is missing or does not hold a list.
    """
    items = data.get(wrapper_key)
    if items is None:
        raise ParseError(
            f"Missing wrapper key {wrapper_key!r} in response. "
            f"Available keys: {list(data.keys())}"
        )
    if not isinstance(items, list):
        raise ParseError(
            f"Wrapper key {wrapper_key!r} must contain a list, "
            f"got {type(items).__name__}"
        )
    return items


def _parse_response(
    text: str,
    wrapper_key: str,
    model_cls: type[BaseModel],
) -> list[BaseModel]:
    """Generic parse pipeline: strip fences, load JSON, unwrap, validate.

    Parameters
    ----------
    text : str
        Raw LLM response text.
    wrapper_key : str
        Key that wraps the array in the response object.
    model_cls : type[BaseModel]
        Pydantic model to validate each item against.

    Returns
    -------
    list[BaseModel]
        Validated model instances.
    """
    text = _strip_fences(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error(
            "Failed to parse LLM response: %s\nRaw text: %s",
            exc,
            text,
        )
        if _has_trailing_comma(text):
            raise ParseError(
                "Trailing comma detected in JSON response",
                response_text=text,
            )
        raise ParseError(f"Invalid JSON: {exc}", response_text=text)
    if not isinstance(data, dict):
        raise ParseError(
            f"Expected JSON object, got {type(data).__name__}",
            response_text=text,
        )
    items = _unwrap(data, wrapper_key)
    validated: list[BaseModel] = []
    for item in items:
        extra_keys = set(item) - set(model_cls.model_fields)
        if extra_keys:
            logger.warning(
                "Extra fields in %s: %s",
                model_cls.__name__,
                sorted(extra_keys),
            )
        try:
            validated.append(model_cls(**item))
        except Exception as exc:
            raise ParseError(
                f"Schema validation failed: {exc}",
                response_text=text,
            )
    return validated


# ── Public API ────────────────────────────────────────────────────────────


def _normalize_exemplar_id(eid: str) -> str:
    """Strip leading alphabetic prefix from an exemplar ID.

    The LLM may prefix exemplar IDs (e.g. "E7633323") following the pattern
    shown in system prompt examples. This normalizer strips any leading
    alphabetic characters so the ID matches the system's bare numeric format.
    """
    import re

    return re.sub(r"^[A-Za-z]+", "", eid)


def parse_code_response(text: str) -> list[CodeInference]:
    """Parse and validate a code inference LLM response.

    Expects ``{"codes": [{exemplar_ids: [...], code_name, definition,
    related_existing_codes}, ...]}``.

    The ``exemplar_ids`` array is expanded into individual ``CodeInference``
    objects, each with ``supporting_quote`` set to empty string (filled
    later by post-processing in the inference pipeline).
    The ``_normalize_exemplar_id`` transformation is applied after expansion.
    """
    clusters = _parse_response(text, _CODE_WRAPPER, CodeClusterResponse)
    expanded: list[CodeInference] = []
    for cluster in clusters:
        for raw in cluster.exemplar_ids:
            eid = _normalize_exemplar_id(raw)
            expanded.append(
                CodeInference(
                    exemplar_id=eid,
                    code_name=cluster.code_name,
                    definition=cluster.definition,
                    supporting_quote="",  # filled by post-processing
                    related_existing_codes=cluster.related_existing_codes,
                    tag="",
                )
            )
    return expanded


# ── Theme/Interpretation parsing (unchanged) ────────────────────────────────────


def parse_theme_response(text: str) -> list[ThemeInference]:
    """Parse and validate a theme inference LLM response.

    Expects ``{"themes": [{theme_name, narrative, code_ids}, ...]}``.
    """
    return _parse_response(text, _THEME_WRAPPER, ThemeInference)


def parse_interpretation_response(text: str) -> list[InterpretationInference]:
    """Parse and validate an interpretation synthesis LLM response.

    Expects ``{"interpretations": [{interpretation_name, narrative,
    theme_ids, key_insights}, ...]}``.
    """
    return _parse_response(text, _INTERP_WRAPPER, InterpretationInference)
