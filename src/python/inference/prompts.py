"""Jinja2 prompt template loader and renderer for LLM inference.

Usage:
    from inference.prompts import (
        render_code_prompt,
        render_theme_prompt,
        render_interpretation_prompt,
    )

    prompt = render_code_prompt(
        ontology_path=["root", "tag1"],
        tag_description="...",
        existing_codes=[...],
        exemplars=[...],
    )
"""

import os
from typing import cast

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=False,
)


def render_code_prompt(**context) -> str:
    """Render the code inference prompt template.

    Parameters
    ----------
    **context :
        Must include:
        - ontology_path : list[str]
        - tag_description : str
        - existing_codes : list[dict] with keys name, definition
        - exemplars : list[dict] with keys id, content, keywords

    Returns
    -------
    str
        Rendered prompt text.
    """
    template = _env.get_template("code_inference.j2")
    return cast(str, template.render(**context))


def render_theme_prompt(**context) -> str:
    """Render the theme inference prompt template.

    Parameters
    ----------
    **context :
        Must include:
        - tag_name : str
        - tag_description : str
        - ontology_path : list[str]
        - codes : list[dict] with keys id, name, definition,
          exemplar_count

    Returns
    -------
    str
        Rendered prompt text.
    """
    template = _env.get_template("theme_inference.j2")
    return cast(str, template.render(**context))


def render_interpretation_prompt(**context) -> str:
    """Render the interpretation synthesis prompt template.

    Parameters
    ----------
    **context :
        Must include:
        - tag_hierarchy : list[list[str]]
        - ontology_subtree : str
        - themes_by_tag : dict[str, list[dict]] with keys
          theme_name, narrative, code_ids

    Returns
    -------
    str
        Rendered prompt text.
    """
    template = _env.get_template("interpretation_synthesis.j2")
    return cast(str, template.render(**context))
