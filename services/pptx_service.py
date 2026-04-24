"""
pptx_service.py
Professional university lecture PowerPoint export.

Fixes:
- 'str' object has no attribute 'get' — defensive handling for string and dict points
- Pure solid colour themes — no external image files required
- Professor images embedded from base64
- Professor manual text shown as highlighted note box
"""
import io
import json
import base64
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

THEMES = {
    "Modern Minimalist": {
        "bg":        (0xFF, 0xFF, 0xFF),
        "accent":    (0x4F, 0x46, 0xE5),
        "accent2":   (0x7C, 0x3A, 0xED),
        "title_txt": (0x1E, 0x1B, 0x4B),
        "headline":  (0x1E, 0x1B, 0x4B),
        "detail":    (0x37, 0x41, 0x51),
        "ex_bg":     (0xEC, 0xFD, 0xF5),
        "ex_label":  (0x06, 0x5F, 0x46),
        "ex_txt":    (0x06, 0x5F, 0x46),
        "note_bg":   (0xFF, 0xF7, 0xED),
        "note_txt":  (0x92, 0x40, 0x0E),
        "dot":       (0x4F, 0x46, 0xE5),
        "bar":       (0x4F, 0x46, 0xE5),
        "divider":   (0xC7, 0xD2, 0xFE),
        "badge_bg":  (0x4F, 0x46, 0xE5),
        "badge_txt": (0xFF, 0xFF, 0xFF),
    },
    "Dark Mode Tech": {
        "bg":        (0x0F, 0x17, 0x2A),
        "accent":    (0x38, 0xBD, 0xF8),
        "accent2":   (0x06, 0xB6, 0xD4),
        "title_txt": (0xF8, 0xFA, 0xFC),
        "headline":  (0xE2, 0xE8, 0xF0),
        "detail":    (0x94, 0xA3, 0xB8),
        "ex_bg":     (0x0C, 0x2A, 0x2A),
        "ex_label":  (0x34, 0xD3, 0x99),
        "ex_txt":    (0x34, 0xD3, 0x99),
        "note_bg":   (0x1E, 0x1B, 0x0A),
        "note_txt":  (0xFB, 0xD3, 0x4D),
        "dot":       (0x38, 0xBD, 0xF8),
        "bar":       (0x38, 0xBD, 0xF8),
        "divider":   (0x1E, 0x40, 0x4F),
        "badge_bg":  (0x38, 0xBD, 0xF8),
        "badge_txt": (0x0F, 0x17, 0x2A),
    },
    "Classic Academic": {
        "bg":        (0xFD, 0xFB, 0xF7),
        "accent":    (0x80, 0x00, 0x00),
        "accent2":   (0xB8, 0x5C, 0x38),
        "title_txt": (0x3B, 0x0A, 0x0A),
        "headline":  (0x3B, 0x0A, 0x0A),
        "detail":    (0x1E, 0x1E, 0x1E),
        "ex_bg":     (0xF0, 0xF7, 0xEE),
        "ex_label":  (0x1A, 0x47, 0x2A),
        "ex_txt":    (0x1A, 0x47, 0x2A),
        "note_bg":   (0xFD, 0xF5, 0xDD),
        "note_txt":  (0x70, 0x3A, 0x00),
        "dot":       (0x80, 0x00, 0x00),
        "bar":       (0x80, 0x00, 0x00),
        "divider":   (0xD9, 0xC5, 0xB2),
        "badge_bg":  (0x80, 0x00, 0x00),
        "badge_txt": (0xFF, 0xFF, 0xFF),
    },
    "Vibrant Creative": {
        "bg":        (0xFF, 0xFF, 0xFF),
        "accent":    (0xF9, 0x73, 0x16),
        "accent2":   (0xEC, 0x48, 0x99),
        "title_txt": (0x43, 0x14, 0x07),
        "headline":  (0x43, 0x14, 0x07),
        "detail":    (0x1C, 0x1C, 0x1E),
        "ex_bg":     (0xFD, 0xF2, 0xF8),
        "ex_label":  (0x70, 0x1A, 0x75),
        "ex_txt":    (0x70, 0x1A, 0x75),
        "note_bg":   (0xFE, 0xF2, 0xC7),
        "note_txt":  (0x92, 0x40, 0x0E),
        "dot":       (0xF9, 0x73, 0x16),
        "bar":       (0xF9, 0x73, 0x16),
        "divider":   (0xFE, 0xD7, 0xAA),
        "badge_bg":  (0xF9, 0x73, 0x16),
        "badge_txt": (0xFF, 0xFF, 0xFF),
    },
}

_W = Inches(13.333)
_H = Inches(7.5)


def _rgb(t: tuple) -> RGBColor:
    return RGBColor(t[0], t[1], t[2])


def _rect(slide, left, top, width, height, color: tuple):
    s = slide.shapes.add_shape(1, left, top, width, height)
    s.fill.solid()
    s.fill.fore_color.rgb = _rgb(color)
    s.line.fill.background()
    return s


def _oval(slide, left, top, width, height, color: tuple):
    s = slide.shapes.add_shape(9, left, top, width, height)
    s.fill.solid()
    s.fill.fore_color.rgb = _rgb(color)
    s.line.fill.background()
    return s


def _tb(slide, left, top, width, height):
    box = slide.shapes.add_textbox(left, top, width, height)
    box.text_frame.word_wrap = True
    return box.text_frame


def _para(tf, text: str, size: float, bold: bool, color: tuple,
          align=PP_ALIGN.LEFT, space_before: float = 0, italic: bool = False):
    if tf.paragraphs and tf.paragraphs[0].text == "":
        p = tf.paragraphs[0]
    else:
        p = tf.add_paragraph()
    run = p.add_run()
    run.text           = str(text)
    run.font.size      = Pt(size)
    run.font.bold      = bold
    run.font.italic    = italic
    run.font.color.rgb = _rgb(color)
    p.alignment        = align
    if space_before:
        p.space_before = Pt(space_before)
    return p


def _extract_point(pt) -> tuple[str, str]:
    """
    Safely extract (headline, detail) from a point that may be
    a dict OR a plain string — fixes 'str' has no attribute 'get'.
    """
    if isinstance(pt, str):
        return pt.strip(), ""
    if isinstance(pt, dict):
        hl  = str(pt.get("headline", pt.get("title",       ""))).strip()
        det = str(pt.get("detail",   pt.get("explanation", ""))).strip()
        return hl, det
    return str(pt).strip(), ""


def _fetch_image(query: str) -> bytes | None:
    """
    Fetch a relevant image for a slide.
    Strategy:
      1. Try Wikimedia Commons API (topic-relevant diagrams/photos, CC licensed)
      2. Fall back to Lorem Picsum (abstract placeholder, always works)
    Returns bytes or None on failure.
    """
    if not query:
        return None

    # ── 1. Wikimedia Commons search ───────────────────────────────
    try:
        clean = query.strip()
        # Search Commons for the query
        search_url = (
            "https://en.wikipedia.org/w/api.php"
            f"?action=query&list=search&srsearch={urllib.request.quote(clean)}"
            "&srnamespace=6&srlimit=1&format=json"
        )
        req = urllib.request.Request(search_url, headers={"User-Agent": "LectureGen/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            results = data.get("query", {}).get("search", [])
            if results:
                title = results[0]["title"]  # e.g. "File:TCP_handshake.svg"
                # Get image URL from Commons
                img_url = (
                    "https://en.wikipedia.org/w/api.php"
                    f"?action=query&titles={urllib.request.quote(title)}"
                    "&prop=imageinfo&iiprop=url&format=json"
                )
                req2 = urllib.request.Request(img_url, headers={"User-Agent": "LectureGen/1.0"})
                with urllib.request.urlopen(req2, timeout=3) as resp2:
                    idata = json.loads(resp2.read().decode())
                    pages = idata.get("query", {}).get("pages", {})
                    for page in pages.values():
                        img_info = page.get("imageinfo", [])
                        if img_info:
                            direct_url = img_info[0]["url"]
                            req3 = urllib.request.Request(direct_url, headers={"User-Agent": "LectureGen/1.0"})
                            with urllib.request.urlopen(req3, timeout=4) as resp3:
                                if resp3.status == 200:
                                    img_bytes = resp3.read()
                                    # Only accept raster images (not SVG — pptx-python can't render SVG)
                                    if img_bytes[:4] in (b'\x89PNG', b'\xff\xd8\xff', b'GIF8') or img_bytes[:2] == b'BM':
                                        return img_bytes
    except Exception:
        pass

    # ── 2. Picsum fallback (abstract photo, always works) ─────────
    try:
        # Use query hash for consistent image per topic
        seed = abs(hash(query)) % 1000
        url  = f"https://picsum.photos/seed/{seed}/800/450"
        req  = urllib.request.Request(url, headers={"User-Agent": "LectureGen/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            if resp.status == 200:
                return resp.read()
    except Exception:
        pass

    return None


def create_pptx(data: dict) -> io.BytesIO:
    theme_name  = data.get("theme", "Modern Minimalist")
    c           = THEMES.get(theme_name, THEMES["Modern Minimalist"])
    slides_data = data.get("slides", [])

    if not slides_data:
        raise ValueError("No slides data provided")

    prs = Presentation()
    prs.slide_width  = _W
    prs.slide_height = _H

    # ── Pre-fetch all images in parallel (max 20s total) ────────
    _img_cache: dict[str, bytes | None] = {}
    _queries = list({
        str(sd.get("image_query", sd.get("image_suggestion", "")) or "").strip()
        for sd in slides_data
        if isinstance(sd, dict)
    } - {"", "null", "none"})

    if _queries:
        with ThreadPoolExecutor(max_workers=8) as pool:
            future_map = {pool.submit(_fetch_image, q): q for q in _queries}
            for future in as_completed(future_map, timeout=20):
                q = future_map[future]
                try:
                    _img_cache[q] = future.result(timeout=1)
                except Exception:
                    _img_cache[q] = None

    for idx, sd in enumerate(slides_data):
        # ── Defensive: sd must be a dict ─────────────────────────
        if not isinstance(sd, dict):
            continue

        slide    = prs.slides.add_slide(prs.slide_layouts[6])
        title    = str(sd.get("title", "Slide")).strip()
        is_title = (idx == 0)

        # ── Safely get all fields ─────────────────────────────────
        raw_points  = sd.get("points", [])
        if not isinstance(raw_points, list):
            raw_points = []

        example     = str(sd.get("example",       "") or "").strip()
        notes       = str(sd.get("speaker_notes", "") or "").strip()
        prof_text   = str(sd.get("professor_text","") or "").strip()
        prof_img_d  = sd.get("professor_image")
        if not isinstance(prof_img_d, dict):
            prof_img_d = None

        img_query = str(sd.get("image_query", sd.get("image_suggestion", "") or "") or "").strip()
        if img_query.lower() in ("null", "none", ""):
            img_query = ""

        # ── Slide background ──────────────────────────────────────
        _rect(slide, 0, 0, _W, _H, c["bg"])
        _rect(slide, 0, 0, Inches(0.08), _H, c["bar"])

        # ══════════════════════════════════════════════════════════
        # TITLE SLIDE
        # ══════════════════════════════════════════════════════════
        if is_title:
            _oval(slide, Inches(8.8),  Inches(-1.8), Inches(5.5), Inches(5.5), c["accent"])
            _oval(slide, Inches(10.0), Inches(4.2),  Inches(4.0), Inches(4.0), c["accent2"])
            tf = _tb(slide, Inches(1.1), Inches(1.8), Inches(9.0), Inches(2.8))
            _para(tf, title, 46, True, c["title_txt"], PP_ALIGN.LEFT)
            _rect(slide, Inches(1.1), Inches(4.75), Inches(3.0), Inches(0.07), c["accent"])
            if notes:
                slide.notes_slide.notes_text_frame.text = notes
            continue

        # ── Slide number badge ────────────────────────────────────
        bw, bh = Inches(0.55), Inches(0.30)
        _rect(slide, _W - bw - Inches(0.12), _H - bh - Inches(0.10), bw, bh, c["badge_bg"])
        btf = _tb(slide, _W - bw - Inches(0.10), _H - bh - Inches(0.08), bw, bh)
        _para(btf, str(idx + 1), 10, True, c["badge_txt"], PP_ALIGN.CENTER)

        # ── Title ─────────────────────────────────────────────────
        ttf = _tb(slide, Inches(0.22), Inches(0.10), Inches(12.8), Inches(0.80))
        _para(ttf, title, 26, True, c["title_txt"])
        _rect(slide, Inches(0.22), Inches(0.93), Inches(12.8), Inches(0.035), c["accent"])


        # ══════════════════════════════════════════════════════════
        # CONTENT SLIDE
        # ══════════════════════════════════════════════════════════

        # Decide whether to embed an image
        has_img   = False
        img_bytes: bytes | None = None

        # AI-suggested image via Wikimedia / Picsum
        if img_query:
            if img_query not in _img_cache:
                _img_cache[img_query] = _fetch_image(img_query)
            img_bytes = _img_cache[img_query]
            has_img   = img_bytes is not None

        # Professor-uploaded image (base64) — overrides AI image
        if prof_img_d and prof_img_d.get("data"):
            try:
                img_bytes = base64.b64decode(str(prof_img_d["data"]))
                has_img   = True
            except Exception:
                has_img = False

        # Space allocation
        has_example  = bool(example)
        has_proftext = bool(prof_text)
        bottom_h     = Inches(0.12)
        if has_example:   bottom_h += Inches(1.10)
        if has_proftext:  bottom_h += Inches(0.90)

        ex_top      = _H - bottom_h
        content_top = Inches(1.05)
        content_h   = ex_top - content_top - Inches(0.10)

        txt_w = Inches(7.8) if has_img else Inches(12.8)

        # Embed image
        if has_img and img_bytes:
            try:
                slide.shapes.add_picture(
                    io.BytesIO(img_bytes),
                    Inches(8.1), Inches(1.05), Inches(4.9), Inches(4.80)
                )
            except Exception:
                has_img = False
                txt_w   = Inches(12.8)

        # ── Points ────────────────────────────────────────────────
        ptf = _tb(slide, Inches(0.22), content_top, txt_w, content_h)

        for i, pt in enumerate(raw_points):
            hl, det = _extract_point(pt)   # ← safe for str or dict
            if not hl:
                continue

            space_top = 10 if i == 0 else 16

            if ptf.paragraphs and ptf.paragraphs[0].text == "":
                hp = ptf.paragraphs[0]
            else:
                hp = ptf.add_paragraph()
            hp.space_before = Pt(space_top)
            hp.space_after  = Pt(2)

            dot_r = hp.add_run()
            dot_r.text = "●  "
            dot_r.font.size  = Pt(12)
            dot_r.font.bold  = True
            dot_r.font.color.rgb = _rgb(c["dot"])

            hl_r = hp.add_run()
            hl_r.text = hl
            hl_r.font.size  = Pt(17)
            hl_r.font.bold  = True
            hl_r.font.color.rgb = _rgb(c["headline"])

            if det:
                dp = ptf.add_paragraph()
                dp.space_before = Pt(2)
                dp.space_after  = Pt(2)
                dr = dp.add_run()
                dr.text = "     " + det
                dr.font.size  = Pt(12)
                dr.font.bold  = False
                dr.font.color.rgb = _rgb(c["detail"])

        # ── Example box ───────────────────────────────────────────
        cur_y = ex_top
        if has_example:
            _rect(slide, Inches(0.22), cur_y - Inches(0.07),
                  Inches(12.8), Inches(0.025), c["divider"])
            ex_h = Inches(1.05)
            _rect(slide, Inches(0.22), cur_y, Inches(12.8), ex_h, c["ex_bg"])

            etf = _tb(slide, Inches(0.40), cur_y + Inches(0.07),
                      Inches(12.4), ex_h - Inches(0.10))
            if etf.paragraphs and etf.paragraphs[0].text == "":
                ep = etf.paragraphs[0]
            else:
                ep = etf.add_paragraph()

            lb = ep.add_run(); lb.text = "EXAMPLE   "
            lb.font.size = Pt(10); lb.font.bold = True
            lb.font.color.rgb = _rgb(c["ex_label"])

            tx = ep.add_run(); tx.text = example
            tx.font.size = Pt(12); tx.font.bold = False
            tx.font.color.rgb = _rgb(c["ex_txt"])

            cur_y += ex_h

        # ── Professor note box ────────────────────────────────────
        if has_proftext:
            note_h = Inches(0.85)
            _rect(slide, Inches(0.22), cur_y + Inches(0.04),
                  Inches(12.8), note_h, c["note_bg"])

            ntf = _tb(slide, Inches(0.40), cur_y + Inches(0.10),
                      Inches(12.4), note_h - Inches(0.10))
            if ntf.paragraphs and ntf.paragraphs[0].text == "":
                np_ = ntf.paragraphs[0]
            else:
                np_ = ntf.add_paragraph()

            lb2 = np_.add_run(); lb2.text = "PROFESSOR NOTE   "
            lb2.font.size = Pt(9); lb2.font.bold = True
            lb2.font.color.rgb = _rgb(c["note_txt"])

            tx2 = np_.add_run(); tx2.text = prof_text
            tx2.font.size = Pt(11); tx2.font.bold = False
            tx2.font.color.rgb = _rgb(c["note_txt"])

        # ── Speaker notes ─────────────────────────────────────────
        if notes:
            slide.notes_slide.notes_text_frame.text = notes

    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf