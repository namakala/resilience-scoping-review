"""Tokenizer pipeline configuration and construction.

Initializes the global TOKENIZER used throughout the BM25 index.
"""

import string
from typing import Callable, List

from utils.logging import get_logger

logger = get_logger(__name__)

# Predefined stopword list

_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "shall",
    "should",
    "can",
    "could",
    "may",
    "might",
    "must",
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
    "this",
    "that",
    "these",
    "those",
    "my",
    "your",
    "his",
    "her",
    "its",
    "our",
    "their",
    "me",
    "him",
    "her",
    "us",
    "them",
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "where",
    "when",
    "why",
    "how",
    "not",
    "no",
    "yes",
    "so",
    "if",
    "then",
    "there",
    "here",
    "all",
    "some",
    "any",
    "each",
    "every",
    "both",
    "few",
    "many",
    "much",
    "more",
    "most",
    "other",
    "such",
    "only",
    "own",
    "same",
    "than",
    "too",
    "very",
    "just",
    "now",
    "then",
    "well",
    "also",
    "back",
    "up",
    "down",
    "out",
    "off",
    "over",
    "under",
    "again",
    "ever",
    "never",
    "always",
    "often",
    "sometimes",
    "enough",
    "even",
    "quite",
    "rather",
    "like",
    "as",
    "because",
    "since",
    "although",
    "though",
    "while",
    "unless",
    "until",
    "before",
    "after",
    "during",
    "about",
    "above",
    "below",
    "between",
    "among",
    "through",
    "throughout",
    "toward",
    "towards",
    "from",
    "into",
    "onto",
    "upon",
    "across",
    "along",
    "around",
    "round",
    "past",
    "via",
    "without",
    "within",
    "beyond",
    "beside",
    "besides",
    "concerning",
    "considering",
    "despite",
    "including",
    "regarding",
    "versus",
}

# Valid toggles

_VALID_TOGGLES = {
    "lowercase",
    "strip_punctuation",
    "split_by_space",
    "remove_stopword",
}

# Config parsing


def _parse_tokenizer_config(config_str: str | None = None) -> List[str]:
    """Parse comma-separated tokenizer config to ordered list of valid toggles.

    Args:
        config_str: e.g., "lowercase,split_by_space,remove_stopword".
            If None, reads BM25_TOKENIZER_CONFIG from env
            (default: "lowercase,split_by_space").

    Returns:
        List of toggle names in order of application.

    Raises:
        ValueError: if any toggle is not in _VALID_TOGGLES.
    """
    import os

    if config_str is None:
        config_str = os.getenv("BM25_TOKENIZER_CONFIG", "lowercase,split_by_space")
    toggles = [t.strip() for t in config_str.split(",") if t.strip()]
    for t in toggles:
        if t not in _VALID_TOGGLES:
            raise ValueError(
                f"Invalid tokenizer toggle '{t}'. "
                f"Valid toggles: {sorted(_VALID_TOGGLES)}"
            )
    return toggles


# Tokenizer factory


def _build_tokenizer(toggles: List[str]) -> Callable[[str], List[str]]:
    """Construct a tokenizer function from a pipeline of toggles.

    Order matters: toggles are applied sequentially. 'split_by_space' must
    appear exactly once and is the tokenization step
    (produces list of strings).

    Args:
        toggles: Ordered list of toggle names.

    Returns:
        Callable that takes raw keyword string and returns List[str] tokens.
    """
    if "split_by_space" not in toggles:
        raise ValueError("Tokenizer config must include 'split_by_space'")

    def tokenize(text: str) -> List[str]:
        # Apply toggles in order; text type changes during pipeline
        for toggle in toggles:
            if toggle == "lowercase":
                text = text.lower()  # type: ignore[assignment]
            elif toggle == "strip_punctuation":
                text = text.translate(  # type: ignore[assignment]
                    str.maketrans("", "", string.punctuation)
                )
            elif toggle == "split_by_space":
                text = text.split()  # type: ignore[assignment]
            elif toggle == "remove_stopword":
                # text is now a list if split_by_space already applied
                if isinstance(text, list):
                    text = [t for t in text if t not in _STOPWORDS]
                else:
                    # split_by_space not yet applied: split then filter
                    text = [
                        t for t in text.split() if t not in _STOPWORDS
                    ]  # type: ignore[assignment]
        return text if isinstance(text, list) else [text]

    return tokenize


# ── Module-level tokenizer ────────────────────────────────────────────────────

_TOKENIZER_TOGGLES = _parse_tokenizer_config()
_TOKENIZER = _build_tokenizer(_TOKENIZER_TOGGLES)

logger.info(
    "BM25 tokenizer initialized",
    extra={"toggles": _TOKENIZER_TOGGLES},
)
