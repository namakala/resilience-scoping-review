"""Load few-shot examples from static curated JSON files.

Usage:
    from inference.fewshot_loader import load_fewshot

    examples = load_fewshot("code_inference", count=2)
    bundle = render_code_prompt(fewshot=examples, ...)
"""

import json
import os
import random

_FEWSHOT_DIR = os.path.join(os.path.dirname(__file__), "fewshot")


def load_fewshot(
    prompt_type: str,
    count: int = 2,
    shuffle: bool = False,
) -> list[dict]:
    """Load up to *count* few-shot demonstrations for a prompt type.

    Each element in the returned list is a dict with ``"user"`` and
    ``"assistant"`` keys suitable for ``PromptBundle.fewshot``.

    Parameters
    ----------
    prompt_type :
        One of ``"code_inference"``, ``"theme_inference"``,
        ``"interpretation_synthesis"``.
    count :
        Maximum number of examples to return.
    shuffle :
        If True, randomize selection order; otherwise first N.

    Returns
    -------
    list[dict]
        Alternating ``{"user": ..., "assistant": ...}`` pairs.
        Empty list if the JSON file does not exist.
    """
    path = os.path.join(_FEWSHOT_DIR, f"{prompt_type}.json")
    if not os.path.isfile(path):
        return []
    with open(path) as f:
        examples: list[dict] = json.load(f)
    if shuffle:
        random.shuffle(examples)
    return examples[:count]
