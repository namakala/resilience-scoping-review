"""Pure format builders for export — JSON, CSV, Markdown.

No I/O, no DuckDB imports.  Each function takes already-deserialized
dicts and returns plain Python data ready for serialization.
"""

from __future__ import annotations

from typing import Any

CSV_COLUMNS = [
    "id",
    "document",
    "tag",
    "content",
    "keywords",
    "code",
    "theme",
    "interpretation",
]


# ── Helpers ──────────────────────────────────────────────────────────────


def _safe_int(v: Any) -> int:
    """Convert *v* to int, stripping any non-digit prefix (e.g. ``"C16"`` → ``16``).

    Returns ``0`` if no digits remain after stripping.
    """
    digits = "".join(c for c in str(v) if c.isdigit())
    return int(digits) if digits else 0


def _build_lookups(
    themes: list[dict],
    codes: list[dict],
    exemplars: dict[str, dict],
) -> tuple[dict[int, dict], dict[int, dict]]:
    """Build theme-by-id and code-by-id lookup dicts."""
    theme_by_id: dict[int, dict] = {t["id"]: t for t in themes}
    code_by_id: dict[int, dict] = {c["id"]: c for c in codes}
    return theme_by_id, code_by_id


def _exemplar_keywords(exemplar: dict) -> list[str]:
    """Extract keyword list from an exemplar dict."""
    raw = exemplar.get("keywords") or []
    return list(raw)


# ── JSON builder ─────────────────────────────────────────────────────────


def _build_json(
    codes: list[dict],
    themes: list[dict],
    interpretations: list[dict],
    exemplars: dict[str, dict],
) -> list[dict[str, Any]]:
    """Build hierarchical JSON as an array of interpretations.

    Each interpretation nests its themes, codes, and exemplars in a
    tree structure matching the user specification.
    """
    theme_by_id, code_by_id = _build_lookups(themes, codes, exemplars)
    result: list[dict[str, Any]] = []

    for interp in interpretations:
        interp_dj = interp.get("data_json") or {}
        theme_list: list[dict[str, Any]] = []

        for tid in interp_dj.get("theme_ids") or []:
            theme = theme_by_id.get(_safe_int(tid))
            if theme is None:
                continue

            theme_dj = theme.get("data_json") or {}
            code_list: list[dict[str, Any]] = []

            for cid in theme_dj.get("code_ids") or []:
                code = code_by_id.get(_safe_int(cid))
                if code is None:
                    continue

                code_dj = code.get("data_json") or {}
                ex_list: list[dict[str, Any]] = []

                for eid in code_dj.get("exemplar_ids") or []:
                    ex = exemplars.get(str(eid))
                    if ex is None:
                        continue
                    ex_list.append(
                        {
                            "id": int(ex["id"]),
                            "content": str(ex.get("content", "")),
                            "keywords": _exemplar_keywords(ex),
                        }
                    )

                code_list.append(
                    {
                        "id": code["id"],
                        "tag": code.get("tag") or "",
                        "name": code["name"],
                        "description": code.get("definition", ""),
                        "exemplars": ex_list,
                    }
                )

            theme_list.append(
                {
                    "id": theme["id"],
                    "name": theme["name"],
                    "description": theme.get("definition", ""),
                    "codes": code_list,
                }
            )

        result.append(
            {
                "id": interp["id"],
                "interpretation": interp["name"],
                "narrative": interp.get("definition", ""),
                "themes": theme_list,
            }
        )

    return result


# ── CSV builder ──────────────────────────────────────────────────────────


def _build_csv(
    interpretations: list[dict],
    themes: list[dict],
    codes: list[dict],
    exemplars: dict[str, dict],
) -> list[dict[str, str]]:
    """Flatten interpretation → theme → code → exemplar into per-exemplar rows.

    Each row represents one exemplar with its full analysis chain.
    """
    theme_by_id, code_by_id = _build_lookups(themes, codes, exemplars)
    rows: list[dict[str, str]] = []

    for interp in interpretations:
        interp_dj = interp.get("data_json") or {}
        for tid in interp_dj.get("theme_ids") or []:
            theme = theme_by_id.get(_safe_int(tid))
            if theme is None:
                continue

            theme_dj = theme.get("data_json") or {}
            for cid in theme_dj.get("code_ids") or []:
                code = code_by_id.get(_safe_int(cid))
                if code is None:
                    continue

                code_dj = code.get("data_json") or {}
                eids = code_dj.get("exemplar_ids") or []
                if not eids:
                    rows.append(_csv_row(interp, theme, code, "", "", "", "", ""))
                for eid in sorted(str(e) for e in eids):
                    ex = exemplars.get(str(eid), {})
                    rows.append(
                        _csv_row(
                            interp,
                            theme,
                            code,
                            str(ex.get("id", eid)),
                            str(ex.get("document", "")),
                            str(ex.get("tag", "")),
                            str(ex.get("content", "")),
                            ", ".join(_exemplar_keywords(ex)),
                        )
                    )

    return rows


def _csv_row(
    interp: dict,
    theme: dict,
    code: dict,
    exemplar_id: str,
    document: str,
    tag: str,
    content: str,
    keywords: str,
) -> dict[str, str]:
    """Build a single CSV row dict."""
    return {
        "id": exemplar_id,
        "document": document,
        "tag": tag,
        "content": content,
        "keywords": keywords,
        "code": code["name"],
        "theme": theme["name"],
        "interpretation": interp["name"],
    }


# ── Markdown builder ─────────────────────────────────────────────────────


def _build_markdown(
    interpretations: list[dict],
    themes: list[dict],
    codes: list[dict],
    exemplars: dict[str, dict],
) -> str:
    """Build a human-readable Markdown report.

    Uses ``#`` for interpretation, ``##`` for theme, ``###`` for code,
    ``-`` for exemplar entries, each with explicit label lines.
    """
    theme_by_id, code_by_id = _build_lookups(themes, codes, exemplars)
    lines: list[str] = []

    for interp in interpretations:
        lines.append(f"# {interp['name']}")
        lines.append("")
        lines.append(f"Narrative: {interp.get('definition', '')}")
        lines.append("")

        interp_dj = interp.get("data_json") or {}
        for tid in interp_dj.get("theme_ids") or []:
            theme = theme_by_id.get(_safe_int(tid))
            if theme is None:
                continue

            lines.append(f"## {theme['name']}")
            lines.append("")
            lines.append(f"Description: {theme.get('definition', '')}")
            lines.append("")

            theme_dj = theme.get("data_json") or {}
            for cid in theme_dj.get("code_ids") or []:
                code = code_by_id.get(_safe_int(cid))
                if code is None:
                    continue

                lines.append(f"### {code['name']}")
                lines.append("")
                lines.append(f"Description: {code.get('definition', '')}")
                lines.append("")

                code_dj = code.get("data_json") or {}
                for eid in sorted(str(e) for e in (code_dj.get("exemplar_ids") or [])):
                    ex = exemplars.get(str(eid))
                    if ex is None:
                        continue
                    content = str(ex.get("content", ""))
                    # Collapse multi-line content to single line for list items
                    oneline = content.replace("\n", " ").replace("\r", " ").strip()
                    lines.append(f"- {ex.get('id', eid)}: {oneline}")

        lines.append("")

    return "\n".join(lines)


__all__ = [
    "_build_json",
    "_build_csv",
    "_build_markdown",
    "CSV_COLUMNS",
]
