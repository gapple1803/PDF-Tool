"""Table detection and plain-text page assembly.

Tables are found from ruling lines (pdfplumber's "lines" strategy) and drawn as
text grids. The rest of the page text is taken from outside the table boxes and
merged back in top-to-bottom order, so each table appears where it sits on the page.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass

MAX_COL_WIDTH = 40


@dataclass
class FoundTable:
    bbox: tuple[float, float, float, float]  # x0, top, x1, bottom
    rows: list[list[str]]


def _clean_cell(cell: str | None) -> str:
    if not cell:
        return ""
    lines = (" ".join(line.split()) for line in cell.splitlines())
    return "\n".join(line for line in lines if line)


def detect_tables(page) -> list[FoundTable]:
    """Ruled tables on the page with at least 2 rows and 2 non-empty columns."""
    try:
        candidates = page.find_tables()
    except Exception:  # odd geometry should never break text extraction
        return []
    tables: list[FoundTable] = []
    for table in candidates:
        rows = [[_clean_cell(c) for c in row] for row in table.extract()]
        rows = [row for row in rows if any(row)]
        if not rows:
            continue
        ncols = max(len(r) for r in rows)
        rows = [r + [""] * (ncols - len(r)) for r in rows]
        keep = [c for c in range(ncols) if any(r[c] for r in rows)]
        rows = [[r[c] for c in keep] for r in rows]
        if len(rows) >= 2 and len(keep) >= 2:
            tables.append(FoundTable(tuple(table.bbox), rows))
    return tables


def render_grid(rows: list[list[str]], max_width: int = MAX_COL_WIDTH) -> str:
    """Draw rows as an ASCII grid; long cells wrap inside their column."""
    ncols = max((len(r) for r in rows), default=0)
    if not ncols:
        return ""
    rows = [[c or "" for c in r] + [""] * (ncols - len(r)) for r in rows]
    widths = []
    for c in range(ncols):
        longest = max(len(line) for r in rows for line in r[c].split("\n"))
        widths.append(max(1, min(longest, max_width)))

    wrapped: list[list[list[str]]] = []
    for row in rows:
        cells = []
        for c, text in enumerate(row):
            lines: list[str] = []
            for para in text.split("\n"):
                lines.extend(
                    textwrap.wrap(para, widths[c], break_long_words=True, break_on_hyphens=False) or [""]
                )
            cells.append(lines)
        wrapped.append(cells)

    multiline = any(len(cell) > 1 for row in wrapped for cell in row)
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [sep]
    for i, row in enumerate(wrapped):
        for k in range(max(len(cell) for cell in row)):
            out.append(
                "| "
                + " | ".join((cell[k] if k < len(cell) else "").ljust(widths[j]) for j, cell in enumerate(row))
                + " |"
            )
        if i == 0 or multiline or i == len(wrapped) - 1:
            out.append(sep)
    return "\n".join(out)


def tidy(text: str | None, layout: bool = False) -> str:
    """Strip trailing spaces, collapse runs of blank lines, trim the ends."""
    if not text:
        return ""
    lines = [line.rstrip() for line in text.splitlines()]
    out: list[str] = []
    for line in lines:
        if not line and (not out or not out[-1]):
            continue
        out.append(line)
    while out and not out[-1]:
        out.pop()
    result = "\n".join(out)
    return textwrap.dedent(result) if layout else result


def _extract(page, layout: bool) -> str:
    return tidy(page.extract_text(layout=True) if layout else page.extract_text(), layout)


def _center(obj) -> tuple[float, float]:
    return (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2


def _in_any(obj, boxes) -> bool:
    cx, cy = _center(obj)
    return any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in boxes)


def _band(page, y0: float, y1: float, layout: bool) -> str:
    """Text whose characters are vertically centred in [y0, y1)."""
    sub = page.filter(lambda o: o.get("object_type") != "char" or y0 <= _center(o)[1] < y1)
    return _extract(sub, layout)


def page_text(page, layout: bool = False, find_tables: bool = True) -> tuple[str, int]:
    """Plain text for one page with tables drawn as grids. Returns (text, table_count)."""
    tables = detect_tables(page) if find_tables else []
    if not tables:
        return _extract(page, layout), 0

    boxes = [t.bbox for t in tables]
    body = page.filter(lambda o: o.get("object_type") != "char" or not _in_any(o, boxes))

    # Group tables whose vertical ranges overlap (e.g. two tables side by side).
    clusters: list[list] = []  # [top, bottom, [tables]]
    for t in sorted(tables, key=lambda t: (t.bbox[1], t.bbox[0])):
        if clusters and t.bbox[1] < clusters[-1][1]:
            clusters[-1][1] = max(clusters[-1][1], t.bbox[3])
            clusters[-1][2].append(t)
        else:
            clusters.append([t.bbox[1], t.bbox[3], [t]])

    parts: list[str] = []
    y = float("-inf")
    for top, bottom, group in clusters:
        parts.append(_band(body, y, top, layout))
        parts.extend(render_grid(t.rows) for t in sorted(group, key=lambda t: t.bbox[0]))
        parts.append(_band(body, top, bottom, layout))  # text beside the table(s)
        y = bottom
    parts.append(_band(body, y, float("inf"), layout))
    return "\n\n".join(p for p in parts if p), len(tables)


_CID = re.compile(r"\(cid:\d+\)")


def real_char_count(text: str) -> int:
    """Non-whitespace characters, ignoring (cid:NN) placeholders and replacement chars."""
    cleaned = _CID.sub("", text).replace("�", "")
    return sum(1 for ch in cleaned if not ch.isspace() and ch not in "+-|")


def is_garbage(text: str) -> bool:
    """True when most of the text is unmapped glyphs from a broken font encoding."""
    compact = "".join(text.split())
    if not compact:
        return False
    junk = sum(len(m) for m in _CID.findall(compact)) + compact.count("�")
    return junk / len(compact) > 0.3
