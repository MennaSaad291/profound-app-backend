"""
slide_diagram_service.py
========================
Generates professional, topic-relevant educational SVG diagrams for lecture slides.
Uses slide content (title + bullet points) to determine the best diagram type.
No external APIs, no network calls — works 100% reliably offline.

Diagram types:
  - TABLE    : for database/data structure topics → draws a styled table
  - FLOW     : for process/algorithm topics → draws a flowchart
  - COMPARE  : for comparison/vs topics → draws two-column comparison
  - CONCEPT  : for definition/theory topics → draws a concept card with numbered points
  - HIERARCHY: for classification/types topics → draws a tree hierarchy
"""

from __future__ import annotations
import re
import hashlib


# ── Theme colours ─────────────────────────────────────────────────────────────
_THEMES: dict[str, dict] = {
    "Modern Minimalist": {"accent": "#4F46E5", "accent2": "#7C3AED", "light": "#EEF2FF", "text": "#1E1B4B", "sub": "#374151"},
    "Dark Mode Tech":    {"accent": "#38BDF8", "accent2": "#06B6D4", "light": "#0C2A3A", "text": "#E2E8F0", "sub": "#94A3B8"},
    "Classic Academic":  {"accent": "#800000", "accent2": "#B85C38", "light": "#FDF5DD", "text": "#3B0A0A", "sub": "#1E1E1E"},
    "Vibrant Creative":  {"accent": "#F97316", "accent2": "#EC4899", "light": "#FDF2F8", "text": "#431407", "sub": "#1C1C1E"},
}
_DEFAULT_THEME = "Modern Minimalist"


def _c(theme: str, key: str) -> str:
    return _THEMES.get(theme, _THEMES[_DEFAULT_THEME]).get(key, "#4F46E5")


# ── Diagram type classifier ────────────────────────────────────────────────────

_TABLE_KEYWORDS = {
    "table", "relation", "schema", "tuple", "attribute", "row", "column",
    "record", "field", "database", "sql", "query", "join", "key", "index",
    "normalization", "entity", "data model", "spreadsheet", "matrix",
}
_FLOW_KEYWORDS = {
    "algorithm", "process", "pipeline", "workflow", "steps", "procedure",
    "implementation", "mechanism", "how it works", "execution", "lifecycle",
    "transaction", "protocol", "compiler", "sorting", "searching", "method",
}
_COMPARE_KEYWORDS = {
    "comparison", "vs", "versus", "difference", "contrast", "types",
    "alternatives", "advantages", "disadvantages", "pros", "cons",
    "classification", "categories", "variants", "approaches",
}
_HIERARCHY_KEYWORDS = {
    "hierarchy", "tree", "classification", "taxonomy", "inheritance",
    "structure", "architecture", "layer", "level", "tier", "model",
    "components", "framework", "organization", "b-tree", "heap",
}


def _classify(title: str, points: list) -> str:
    t = title.lower()

    # ── Slides that should NEVER have a diagram ────────────────────────────
    _no_diagram = {
        "learning objectives", "objectives", "prerequisites", "pre-requisites",
        "summary", "key takeaways", "takeaways", "review questions", "questions",
        "further reading", "references", "best practices", "common mistakes",
        "agenda", "overview", "roadmap", "introduction", "conclusion",
        "discussion", "quiz", "exercise", "activity", "case study",
        "real-world applications", "applications and case",
    }
    if any(k in t for k in _no_diagram):
        return "CONCEPT"  # CONCEPT = no diagram shown

    # ── Title-only classification first (most accurate) ────────────────────
    if any(k in t for k in _TABLE_KEYWORDS):     return "TABLE"
    if any(k in t for k in _FLOW_KEYWORDS):      return "FLOW"
    if any(k in t for k in _HIERARCHY_KEYWORDS): return "HIERARCHY"
    if any(k in t for k in _COMPARE_KEYWORDS):   return "COMPARE"

    # ── Fall back to point headlines ────────────────────────────────────────
    pts_text = " ".join(
        str(p.get("headline", "") if isinstance(p, dict) else p).lower()
        for p in points
    )
    if any(k in pts_text for k in _FLOW_KEYWORDS):      return "FLOW"
    if any(k in pts_text for k in _HIERARCHY_KEYWORDS): return "HIERARCHY"
    if any(k in pts_text for k in _TABLE_KEYWORDS):     return "TABLE"
    if any(k in pts_text for k in _COMPARE_KEYWORDS):   return "COMPARE"

    # ── Default: no diagram ─────────────────────────────────────────────────
    return "CONCEPT"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    """Escape XML special chars."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _wrap(text: str, max_chars: int = 30) -> list[str]:
    """Wrap text to lines of max_chars."""
    words = text.split()
    lines, line = [], ""
    for w in words:
        if len(line) + len(w) + 1 <= max_chars:
            line = (line + " " + w).strip()
        else:
            if line: lines.append(line)
            line = w
    if line: lines.append(line)
    return lines or [""]


# ── TABLE diagram ─────────────────────────────────────────────────────────────

def _draw_table(title: str, points: list, theme: str) -> str:
    ac   = _c(theme, "accent")
    lt   = _c(theme, "light")
    txt  = _c(theme, "text")
    sub  = _c(theme, "sub")
    W, H = 560, 380

    # Extract column names and rows from points
    cols = []
    rows = []
    for p in points[:5]:
        hl  = str(p.get("headline","") if isinstance(p,dict) else p).strip()
        det = str(p.get("detail","")   if isinstance(p,dict) else "").strip()
        cols.append(hl[:20])
        # Generate 2 sample rows from the detail
        det_words = det.split()[:8]
        rows.append((" ".join(det_words[:4]), " ".join(det_words[4:])))

    n_cols = min(len(cols), 4)
    n_rows = min(len(rows), 4)
    col_w  = (W - 80) // max(n_cols, 1)
    row_h  = 36
    header_h = 42
    tbl_top  = 90
    tbl_left = 40

    svg = [f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">']
    svg.append(f'<rect width="{W}" height="{H}" fill="white" rx="12"/>')
    svg.append(f'<rect width="{W}" height="7" fill="{ac}" rx="0"/>')

    # Title
    svg.append(f'<rect x="0" y="0" width="{W}" height="52" fill="{ac}"/>')
    svg.append(f'<text x="{W//2}" y="33" text-anchor="middle" font-family="Arial,sans-serif" font-size="16" font-weight="bold" fill="white">{_esc(title[:50])}</text>')

    # Table header row
    svg.append(f'<rect x="{tbl_left}" y="{tbl_top}" width="{col_w * n_cols}" height="{header_h}" fill="{ac}"/>')
    for ci in range(n_cols):
        svg.append(f'<text x="{tbl_left + ci*col_w + col_w//2}" y="{tbl_top + header_h//2 + 6}" text-anchor="middle" font-family="Arial,sans-serif" font-size="12" font-weight="bold" fill="white">{_esc(cols[ci][:18])}</text>')

    # Data rows
    for ri in range(n_rows):
        row_fill = lt if ri % 2 == 0 else "white"
        y = tbl_top + header_h + ri * row_h
        svg.append(f'<rect x="{tbl_left}" y="{y}" width="{col_w * n_cols}" height="{row_h}" fill="{row_fill}"/>')
        for ci in range(n_cols):
            cell_txt = f"Value {ri+1}-{ci+1}"
            svg.append(f'<text x="{tbl_left + ci*col_w + col_w//2}" y="{y + row_h//2 + 5}" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" fill="{sub}">{cell_txt}</text>')

    # Table border
    total_h = header_h + n_rows * row_h
    svg.append(f'<rect x="{tbl_left}" y="{tbl_top}" width="{col_w*n_cols}" height="{total_h}" fill="none" stroke="{ac}" stroke-width="2" rx="2"/>')
    for ci in range(1, n_cols):
        x = tbl_left + ci * col_w
        svg.append(f'<line x1="{x}" y1="{tbl_top}" x2="{x}" y2="{tbl_top+total_h}" stroke="{ac}" stroke-width="1" opacity="0.5"/>')

    # Labels
    label_y = tbl_top + header_h + total_h // 2
    svg.append(f'<text x="20" y="{label_y}" text-anchor="end" font-family="Arial,sans-serif" font-size="11" fill="{ac}" font-style="italic">← Tuple</text>')
    svg.append(f'<text x="{tbl_left}" y="{tbl_top - 8}" text-anchor="start" font-family="Arial,sans-serif" font-size="11" fill="{ac}" font-style="italic">Attribute ↓</text>')

    svg.append('</svg>')
    return "\n".join(svg)


# ── FLOW diagram ──────────────────────────────────────────────────────────────

def _draw_flow(title: str, points: list, theme: str) -> str:
    ac  = _c(theme, "accent")
    ac2 = _c(theme, "accent2")
    lt  = _c(theme, "light")
    txt = _c(theme, "text")
    W, H = 560, 400

    steps = []
    for p in points[:5]:
        hl = str(p.get("headline","") if isinstance(p,dict) else p).strip()
        steps.append(hl[:35])

    n     = len(steps)
    box_w = 200
    box_h = 44
    gap_y = 30
    start_y = 90
    cx    = W // 2

    svg = [f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">']
    svg.append(f'<rect width="{W}" height="{H}" fill="white" rx="12"/>')
    svg.append(f'<rect x="0" y="0" width="{W}" height="52" fill="{ac}"/>')
    svg.append(f'<text x="{cx}" y="33" text-anchor="middle" font-family="Arial,sans-serif" font-size="16" font-weight="bold" fill="white">{_esc(title[:48])}</text>')

    for i, step in enumerate(steps):
        y   = start_y + i * (box_h + gap_y)
        bx  = cx - box_w // 2
        # Alternate colours
        fill = ac if i == 0 else (ac2 if i == len(steps)-1 else lt)
        tc   = "white" if fill in (ac, ac2) else txt
        svg.append(f'<rect x="{bx}" y="{y}" width="{box_w}" height="{box_h}" fill="{fill}" rx="8" stroke="{ac}" stroke-width="1.5"/>')
        # Step number circle
        svg.append(f'<circle cx="{bx+22}" cy="{y+box_h//2}" r="14" fill="{ac if fill==lt else "rgba(255,255,255,0.3)"}"/>')
        svg.append(f'<text x="{bx+22}" y="{y+box_h//2+5}" text-anchor="middle" font-family="Arial,sans-serif" font-size="12" font-weight="bold" fill="{"white" if fill==lt else fill}">{i+1}</text>')
        svg.append(f'<text x="{bx+45}" y="{y+box_h//2+5}" font-family="Arial,sans-serif" font-size="12" font-weight="bold" fill="{tc}">{_esc(step)}</text>')
        # Arrow to next
        if i < len(steps) - 1:
            ay = y + box_h
            svg.append(f'<line x1="{cx}" y1="{ay}" x2="{cx}" y2="{ay+gap_y-4}" stroke="{ac}" stroke-width="2" marker-end="url(#arrow)"/>')

    # Arrow marker
    svg.append('<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto">')
    svg.append(f'<path d="M0,0 L8,4 L0,8 Z" fill="{ac}"/></marker></defs>')
    svg.append('</svg>')
    return "\n".join(svg)


# ── CONCEPT card diagram ──────────────────────────────────────────────────────

def _draw_concept(title: str, points: list, theme: str) -> str:
    ac  = _c(theme, "accent")
    ac2 = _c(theme, "accent2")
    lt  = _c(theme, "light")
    txt = _c(theme, "text")
    sub = _c(theme, "sub")
    W, H = 560, 400

    svg = [f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">']
    svg.append(f'<rect width="{W}" height="{H}" fill="white" rx="12"/>')
    svg.append(f'<rect x="0" y="0" width="{W}" height="52" fill="{ac}"/>')
    svg.append(f'<text x="{W//2}" y="33" text-anchor="middle" font-family="Arial,sans-serif" font-size="16" font-weight="bold" fill="white">{_esc(title[:48])}</text>')
    svg.append(f'<rect x="0" y="52" width="{W}" height="4" fill="{ac2}"/>')

    row_h = (H - 78) // max(len(points[:5]), 1)
    for i, p in enumerate(points[:5]):
        hl  = str(p.get("headline","") if isinstance(p,dict) else p).strip()[:50]
        det = str(p.get("detail","")   if isinstance(p,dict) else "").strip()[:80]
        y   = 62 + i * row_h
        fill = lt if i % 2 == 0 else "white"
        svg.append(f'<rect x="8" y="{y+3}" width="{W-16}" height="{row_h-6}" fill="{fill}" rx="6"/>')
        # Number badge
        svg.append(f'<circle cx="34" cy="{y+row_h//2}" r="16" fill="{ac}"/>')
        svg.append(f'<text x="34" y="{y+row_h//2+5}" text-anchor="middle" font-family="Arial,sans-serif" font-size="13" font-weight="bold" fill="white">{i+1}</text>')
        # Headline
        svg.append(f'<text x="60" y="{y+row_h//2-6}" font-family="Arial,sans-serif" font-size="13" font-weight="bold" fill="{txt}">{_esc(hl)}</text>')
        if det:
            lines = _wrap(det, 55)
            svg.append(f'<text x="60" y="{y+row_h//2+10}" font-family="Arial,sans-serif" font-size="10" fill="{sub}">{_esc(lines[0])}</text>')

    svg.append(f'<rect x="8" y="{H-12}" width="{W-16}" height="5" fill="{ac}" rx="2"/>')
    svg.append('</svg>')
    return "\n".join(svg)


# ── HIERARCHY tree diagram ────────────────────────────────────────────────────

def _draw_hierarchy(title: str, points: list, theme: str) -> str:
    ac  = _c(theme, "accent")
    ac2 = _c(theme, "accent2")
    lt  = _c(theme, "light")
    txt = _c(theme, "text")
    W, H = 560, 400

    svg = [f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">']
    svg.append(f'<rect width="{W}" height="{H}" fill="white" rx="12"/>')
    svg.append(f'<rect x="0" y="0" width="{W}" height="52" fill="{ac}"/>')
    svg.append(f'<text x="{W//2}" y="33" text-anchor="middle" font-family="Arial,sans-serif" font-size="16" font-weight="bold" fill="white">{_esc(title[:48])}</text>')

    # Root node
    root_x, root_y, root_w, root_h = W//2, 75, 200, 36
    svg.append(f'<rect x="{root_x-root_w//2}" y="{root_y}" width="{root_w}" height="{root_h}" fill="{ac}" rx="8"/>')
    svg.append(f'<text x="{root_x}" y="{root_y+root_h//2+5}" text-anchor="middle" font-family="Arial,sans-serif" font-size="13" font-weight="bold" fill="white">{_esc(title[:30])}</text>')

    # Child nodes
    pts   = points[:4]
    n     = len(pts)
    node_w, node_h = 110, 34
    spacing = (W - 60) // max(n, 1)
    child_y = 165

    for i, p in enumerate(pts):
        hl = str(p.get("headline","") if isinstance(p,dict) else p).strip()[:22]
        cx = 30 + spacing // 2 + i * spacing
        # Connector line
        svg.append(f'<line x1="{root_x}" y1="{root_y+root_h}" x2="{cx}" y2="{child_y}" stroke="{ac}" stroke-width="1.5" opacity="0.6"/>')
        # Node box
        svg.append(f'<rect x="{cx-node_w//2}" y="{child_y}" width="{node_w}" height="{node_h}" fill="{ac2 if i%2==0 else ac}" rx="6"/>')
        svg.append(f'<text x="{cx}" y="{child_y+node_h//2+5}" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" font-weight="bold" fill="white">{_esc(hl)}</text>')

        # Sub-children
        if i < len(points):
            det = str(points[i].get("detail","") if isinstance(points[i],dict) else "").strip()
            det_words = det.split()[:3]
            if det_words:
                sub_y = child_y + node_h + 20
                sub_x = cx
                svg.append(f'<line x1="{cx}" y1="{child_y+node_h}" x2="{sub_x}" y2="{sub_y}" stroke="{ac}" stroke-width="1" opacity="0.4" stroke-dasharray="4,3"/>')
                svg.append(f'<rect x="{sub_x-55}" y="{sub_y}" width="110" height="28" fill="{lt}" rx="4" stroke="{ac}" stroke-width="1" opacity="0.6"/>')
                svg.append(f'<text x="{sub_x}" y="{sub_y+17}" text-anchor="middle" font-family="Arial,sans-serif" font-size="10" fill="{txt}" opacity="0.8">{_esc(" ".join(det_words))}</text>')

    svg.append(f'<rect x="8" y="{H-12}" width="{W-16}" height="5" fill="{ac}" rx="2"/>')
    svg.append('</svg>')
    return "\n".join(svg)


# ── COMPARE diagram ───────────────────────────────────────────────────────────

def _draw_compare(title: str, points: list, theme: str) -> str:
    ac  = _c(theme, "accent")
    ac2 = _c(theme, "accent2")
    lt  = _c(theme, "light")
    txt = _c(theme, "text")
    sub = _c(theme, "sub")
    W, H = 560, 400

    svg = [f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">']
    svg.append(f'<rect width="{W}" height="{H}" fill="white" rx="12"/>')
    svg.append(f'<rect x="0" y="0" width="{W}" height="52" fill="{ac}"/>')
    svg.append(f'<text x="{W//2}" y="33" text-anchor="middle" font-family="Arial,sans-serif" font-size="16" font-weight="bold" fill="white">{_esc(title[:48])}</text>')

    col_w = (W - 40) // 2
    # Column headers
    svg.append(f'<rect x="10" y="62" width="{col_w}" height="36" fill="{ac}" rx="6"/>')
    svg.append(f'<rect x="{20+col_w}" y="62" width="{col_w}" height="36" fill="{ac2}" rx="6"/>')
    svg.append(f'<text x="{10+col_w//2}" y="85" text-anchor="middle" font-family="Arial,sans-serif" font-size="13" font-weight="bold" fill="white">Approach A</text>')
    svg.append(f'<text x="{20+col_w+col_w//2}" y="85" text-anchor="middle" font-family="Arial,sans-serif" font-size="13" font-weight="bold" fill="white">Approach B</text>')

    row_h = (H - 118) // max(min(len(points), 5), 1)
    for i, p in enumerate(points[:5]):
        hl  = str(p.get("headline","") if isinstance(p,dict) else p).strip()
        det = str(p.get("detail","")   if isinstance(p,dict) else "").strip()
        y   = 102 + i * row_h
        fill = lt if i % 2 == 0 else "white"
        svg.append(f'<rect x="10" y="{y}" width="{col_w}" height="{row_h-4}" fill="{fill}" rx="4" stroke="{ac}" stroke-width="0.5"/>')
        svg.append(f'<rect x="{20+col_w}" y="{y}" width="{col_w}" height="{row_h-4}" fill="{fill}" rx="4" stroke="{ac2}" stroke-width="0.5"/>')
        words = hl.split()
        mid   = len(words) // 2
        left  = " ".join(words[:mid]) or hl
        right = " ".join(words[mid:]) or hl
        svg.append(f'<text x="{10+col_w//2}" y="{y+row_h//2+5}" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" fill="{txt}">{_esc(left[:28])}</text>')
        svg.append(f'<text x="{20+col_w+col_w//2}" y="{y+row_h//2+5}" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" fill="{txt}">{_esc(right[:28])}</text>')

    svg.append(f'<rect x="8" y="{H-12}" width="{W-16}" height="5" fill="{ac}" rx="2"/>')
    svg.append('</svg>')
    return "\n".join(svg)


# ── Public API ────────────────────────────────────────────────────────────────

_CACHE: dict[str, str] = {}


def generate_slide_svg(title: str, points: list,
                        theme: str = "Modern Minimalist") -> str:
    """
    Generate a topic-relevant educational SVG diagram for a slide.
    Returns SVG string (or empty string if no diagram is applicable).
    Cached by title+theme.
    """
    cache_key = hashlib.md5(f"{title}{theme}".encode()).hexdigest()
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    diagram_type = _classify(title, points)

    # Don't show a diagram for CONCEPT type — it just mirrors the slide content
    if diagram_type == "CONCEPT":
        return ""  # empty string = no diagram shown

    try:
        if diagram_type == "TABLE":
            svg = _draw_table(title, points, theme)
        elif diagram_type == "FLOW":
            svg = _draw_flow(title, points, theme)
        elif diagram_type == "HIERARCHY":
            svg = _draw_hierarchy(title, points, theme)
        elif diagram_type == "COMPARE":
            svg = _draw_compare(title, points, theme)
        else:
            return ""
    except Exception as e:
        print(f"[Diagram] {diagram_type} failed for '{title}': {e}")
        return ""

    _CACHE[cache_key] = svg
    return svg
