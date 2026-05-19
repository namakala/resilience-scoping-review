"""Jinja2 prompt template loader and renderer for LLM inference.

Usage:
    from inference.prompts import (
        PromptBundle,
        render_code_prompt,
        render_theme_prompt,
        render_interpretation_prompt,
    )

    bundle = render_code_prompt(
        ontology_path=["root", "tag1"],
        tag_description="...",
        existing_codes=[...],
        exemplars=[...],
    )
    # bundle.system  -> system prompt (role, schema, rules)
    # bundle.user    -> user prompt (ontology, exemplars, codes)
    # bundle.fewshot -> optional few-shot demonstrations
"""

import os
from dataclasses import dataclass
from typing import cast

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=False,
)


@dataclass
class PromptBundle:
    """A fully rendered prompt split by message role.

    Attributes
    ----------
    system : str
        System prompt content (role, schema, rules).
    user : str
        User prompt content (batch-specific data).
    fewshot : list[dict] | None
        Optional few-shot demonstrations as alternating
        ``{"user": "...", "assistant": "..."}`` pairs.
    """

    system: str
    user: str
    fewshot: list[dict] | None = None


def render_code_prompt(
    fewshot: list[dict] | None = None,
    **context,
) -> PromptBundle:
    """Render code inference system + user prompts.

    Parameters
    ----------
    fewshot :
        Optional few-shot demonstrations as alternating
        ``{"user": ..., "assistant": ...}`` pairs.
    **context :
        Must include:
        - ontology_path : list[str]
        - tag_description : str
        - existing_codes : list[dict] with keys name, definition
        - exemplars : list[dict] with keys id, content, keywords

    Returns
    -------
    PromptBundle
        Split system and user prompt content.
    """
    system_tpl = _env.get_template("code_inference_system.j2")
    user_tpl = _env.get_template("code_inference_user.j2")
    return PromptBundle(
        system=cast(str, system_tpl.render()),
        user=cast(str, user_tpl.render(**context)),
        fewshot=fewshot,
    )


def render_theme_prompt(
    fewshot: list[dict] | None = None,
    **context,
) -> PromptBundle:
    """Render theme inference system + user prompts.

    Parameters
    ----------
    fewshot :
        Optional few-shot demonstrations as alternating
        ``{"user": ..., "assistant": ...}`` pairs.
    **context :
        Must include:
        - tag_name : str
        - tag_description : str
        - ontology_path : list[str]
        - codes : list[dict] with keys id, name, definition,
          exemplar_count, exemplar_contents (list of content strings)

    Returns
    -------
    PromptBundle
        Split system and user prompt content.
    """
    system_tpl = _env.get_template("theme_inference_system.j2")
    user_tpl = _env.get_template("theme_inference_user.j2")
    return PromptBundle(
        system=cast(str, system_tpl.render()),
        user=cast(str, user_tpl.render(**context)),
        fewshot=fewshot,
    )


def render_interpretation_prompt(
    fewshot: list[dict] | None = None,
    **context,
) -> PromptBundle:
    """Render interpretation synthesis system + user prompts.

    Parameters
    ----------
    fewshot :
        Optional few-shot demonstrations as alternating
        ``{"user": ..., "assistant": ...}`` pairs.
    **context :
        Must include:
        - tag_hierarchy : list[list[str]]
        - ontology_subtree : str
        - themes_by_tag : dict[str, list[dict]] with keys
          theme_name, narrative, code_ids, codes_detail
          where codes_detail is a list of dicts with keys
          name, definition, exemplar_ids, exemplar_contents

    Returns
    -------
    PromptBundle
        Split system and user prompt content.
    """
    system_tpl = _env.get_template("interpretation_synthesis_system.j2")
    user_tpl = _env.get_template("interpretation_synthesis_user.j2")
    return PromptBundle(
        system=cast(str, system_tpl.render()),
        user=cast(str, user_tpl.render(**context)),
        fewshot=fewshot,
    )
