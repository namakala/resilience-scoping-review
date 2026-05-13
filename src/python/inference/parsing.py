"""Parse and validate structured LLM responses against Pydantic schemas.

Usage:
    from inference.parsing import parse_code_response

    raw = '{"codes": [{"exemplar_id": "E001", "code_name": "...", ...}]}'
    codes = parse_code_response(raw)
    for c in codes:
        print(c.code_name)
"""

import json
import re
from typing import Any

from pydantic import BaseModel, Field
from utils.exceptions import ParseError

__all__ = [
    "CodeInference",
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


class ThemeInference(BaseModel):
    """A theme grouping multiple related codes."""

    theme_name: str
    narrative: str
    code_ids: list[str]


class InterpretationInference(BaseModel):
    """A cross-tag interpretation synthesizing multiple themes."""

    interpretation_name: str
    narrative: str
    theme_ids: list[str]
    key_insights: list[str]


# ── Wrapper keys (must match template Output Schema keys) ─────────────────

_CODE_WRAPPER = "codes"
_THEME_WRAPPER = "themes"
_INTERP_WRAPPER = "interpretations"

# ── Internal helpers ──────────────────────────────────────────────────────


def _strip_fences(text: str) -> str:
    """Remove markdown code fences (`` ```json `` or ``````)."""
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()


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
        raise ParseError(f"Invalid JSON: {exc}", response_text=text)
    if not isinstance(data, dict):
        raise ParseError(
            f"Expected JSON object, got {type(data).__name__}",
            response_text=text,
        )
    items = _unwrap(data, wrapper_key)
    try:
        return [model_cls(**item) for item in items]
    except Exception as exc:
        raise ParseError(f"Schema validation failed: {exc}", response_text=text)


# ── Public API ────────────────────────────────────────────────────────────


def parse_code_response(text: str) -> list[CodeInference]:
    """Parse and validate a code inference LLM response.

    Expects ``{"codes": [{exemplar_id, code_name, definition,
    supporting_quote, related_existing_codes}, ...]}``.
    """
    return _parse_response(text, _CODE_WRAPPER, CodeInference)


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
