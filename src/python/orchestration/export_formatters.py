"""Pure format builders for export — JSON, CSV, Markdown.

No I/O, no DuckDB imports.  Each function takes already-deserialized
dicts and returns plain Python data ready for serialization.
"""

from __future__ import annotations

from typing import Any

CSV_COLUMNS = [
    "interpretation_id",
    "interpretation_name",
    "theme_id",
    "theme_name",
    "code_id",
    "code_name",
    "exemplar_id",
    "exemplar_content",
    "tag_path",
]


def _safe_int(v: Any) -> int:
    """Convert *v* to int, stripping any non-digit prefix (e.g. ``\"C16\"`` → ``16``).

    Returns ``0`` if no digits remain after stripping.
    """
    digits = "".join(c for c in str(v) if c.isdigit())
    return int(digits) if digits else 0


def _build_json(
    codes: list[dict],
    themes: list[dict],
    interpretations: list[dict],
) -> dict[str, Any]:
    """Build hierarchical JSON with codes/themes grouped by tag."""
    codes_by_tag: dict[str, list[dict]] = {}
    for c in codes:
        tag = c["tag"] or "_none"
        codes_by_tag.setdefault(tag, []).append(
            {
                "id": c["id"],
                "name": c["name"],
                "definition": c["definition"],
                "tag": c["tag"],
                "exemplar_ids": sorted(
                    str(e) for e in (c.get("data_json", {}).get("exemplar_ids") or [])
                ),
            }
        )

    themes_by_tag: dict[str, list[dict]] = {}
    for t in themes:
        tag = t["tag"] or "_none"
        themes_by_tag.setdefault(tag, []).append(
            {
                "id": t["id"],
                "name": t["name"],
                "narrative": t["definition"],
                "tag": t["tag"],
                "code_ids": sorted(
                    _safe_int(e) for e in (t.get("data_json", {}).get("code_ids") or [])
                ),
            }
        )

    interp_list: list[dict] = []
    for i in interpretations:
        dj = i.get("data_json", {})
        interp_list.append(
            {
                "id": i["id"],
                "name": i["name"],
                "narrative": i["definition"],
                "theme_ids": sorted(_safe_int(e) for e in (dj.get("theme_ids") or [])),
                "tag_spans": sorted(dj.get("tag_spans") or []),
            }
        )

    return {
        "codes_by_tag": dict(sorted(codes_by_tag.items())),
        "themes_by_tag": dict(sorted(themes_by_tag.items())),
        "interpretations": interp_list,
    }


def _build_csv(
    interpretations: list[dict],
    themes: list[dict],
    codes: list[dict],
    exemplar_map: dict[str, str],
) -> list[dict[str, str]]:
    """Flatten interpretation → theme → code → exemplar into rows.

    Each row represents one leaf-level code→exemplar pair with the
    full chain of interpretation and theme ancestry.
    """
    theme_by_id: dict[int, dict] = {t["id"]: t for t in themes}
    code_by_id: dict[int, dict] = {c["id"]: c for c in codes}

    rows: list[dict[str, str]] = []
    for interp in interpretations:
        for tid in interp.get("data_json", {}).get("theme_ids") or []:
            theme = theme_by_id.get(_safe_int(tid))
            if theme is None:
                continue
            for cid in theme.get("data_json", {}).get("code_ids") or []:
                code = code_by_id.get(_safe_int(cid))
                if code is None:
                    continue
                eids = code.get("data_json", {}).get("exemplar_ids") or []
                if not eids:
                    rows.append(
                        _csv_row(
                            interp,
                            theme,
                            code,
                            "",
                            "",
                            _tag_path(interp, theme, code),
                        )
                    )
                for eid in sorted(str(e) for e in eids):
                    rows.append(
                        _csv_row(
                            interp,
                            theme,
                            code,
                            eid,
                            exemplar_map.get(str(eid), ""),
                            _tag_path(interp, theme, code),
                        )
                    )
    return rows


def _csv_row(
    interp: dict,
    theme: dict,
    code: dict,
    eid: str,
    content: str,
    tag_path: str,
) -> dict[str, str]:
    """Build a single CSV row dict."""
    return {
        "interpretation_id": str(interp["id"]),
        "interpretation_name": interp["name"],
        "theme_id": str(theme["id"]),
        "theme_name": theme["name"],
        "code_id": str(code["id"]),
        "code_name": code["name"],
        "exemplar_id": eid,
        "exemplar_content": content,
        "tag_path": tag_path,
    }


def _tag_path(interp: dict, theme: dict, code: dict) -> str:
    """Assemble dot-delimited tag path for a code."""
    parts = [p for p in [interp.get("tag"), theme.get("tag"), code.get("tag")] if p]
    return ".".join(parts) if parts else ""


def _build_markdown(
    interpretations: list[dict],
    themes: list[dict],
    codes: list[dict],
    exemplar_map: dict[str, str],
) -> str:
    """Build a human-readable Markdown report with TOC."""
    theme_by_id: dict[int, dict] = {t["id"]: t for t in themes}
    code_by_id: dict[int, dict] = {c["id"]: c for c in codes}
    lines: list[str] = ["# Interpretations\n"]

    for interp in interpretations:
        anchor = _md_anchor(interp["name"])
        lines.append(f"- [{interp['name']}](#{anchor})")
    lines.append("")

    for interp in interpretations:
        anchor = _md_anchor(interp["name"])
        lines.append(f"## {interp['name']}")
        lines.append("")
        if interp.get("definition"):
            lines.append(interp["definition"])
            lines.append("")

        lines.append("### Themes")
        lines.append("")

        for tid in interp.get("data_json", {}).get("theme_ids") or []:
            theme = theme_by_id.get(_safe_int(tid))
            if theme is None:
                continue
            lines.append(f"#### {theme['name']}")
            lines.append("")
            if theme.get("definition"):
                lines.append(theme["definition"])
                lines.append("")

            for cid in theme.get("data_json", {}).get("code_ids") or []:
                code = code_by_id.get(_safe_int(cid))
                if code is None:
                    continue
                lines.append(f"- **{code['name']}**: {code['definition']}")
                for eid in sorted(
                    str(e)
                    for e in (code.get("data_json", {}).get("exemplar_ids") or [])
                ):
                    content = exemplar_map.get(eid, "")
                    if content:
                        for line in content.split("\n"):
                            lines.append(f"  > {line}")
                        lines.append("")
        lines.append("")

    return "\n".join(lines)


def _md_anchor(name: str) -> str:
    """Convert a heading name to a GitHub-style anchor."""
    return name.lower().replace(" ", "-").replace(".", "")


__all__ = [
    "_build_json",
    "_build_csv",
    "_build_markdown",
]
