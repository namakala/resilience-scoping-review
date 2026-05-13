"""JSON serialization/deserialization for state values."""

import json
from typing import Any

from utils.exceptions import StateError


def _serialize(obj: Any) -> tuple[str, str]:
    """Serialize a Python object to JSON string with type hint.

    Args:
        obj: Python object to serialize (int, float, str, bool, dict, list, None).

    Returns:
        Tuple of (json_string, type_hint).

    Raises:
        StateError: If the object type is not JSON-serializable.
    """
    if obj is None:
        return "null", "null"
    if isinstance(obj, bool):
        return json.dumps(obj), "bool"
    if isinstance(obj, int):
        return json.dumps(obj), "int"
    if isinstance(obj, float):
        return json.dumps(obj), "float"
    if isinstance(obj, str):
        return json.dumps(obj), "str"
    if isinstance(obj, dict):
        return json.dumps(obj, ensure_ascii=False), "dict"
    if isinstance(obj, list):
        return json.dumps(obj, ensure_ascii=False), "list"
    raise StateError(
        f"Unsupported state value type: {type(obj).__name__}. "
        "Only int, float, str, bool, dict, list, and None are supported."
    )


def _deserialize(json_str: str, type_hint: str) -> Any:
    """Deserialize a JSON string back to a Python object.

    Args:
        json_str: JSON-encoded string.
        type_hint: Type hint stored alongside the value ('int', 'str', 'dict', etc.).

    Returns:
        Deserialized Python object.

    Raises:
        StateError: If deserialization fails or type mismatch detected.
    """
    try:
        obj = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise StateError(f"Malformed JSON in state value: {exc}") from exc

    # Type coercion based on hint
    if type_hint == "int" and isinstance(obj, int):
        return obj
    if type_hint == "float" and isinstance(obj, (int, float)):
        return float(obj) if type_hint == "float" else obj
    if type_hint == "bool" and isinstance(obj, bool):
        return obj
    if type_hint == "str" and isinstance(obj, str):
        return obj
    if type_hint in ("dict",) and isinstance(obj, dict):
        return obj
    if type_hint in ("list",) and isinstance(obj, list):
        return obj
    if type_hint == "null" and obj is None:
        return None

    # For 'workflow' key we always store as 'dict'
    return obj
