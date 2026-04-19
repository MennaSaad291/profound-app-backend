"""
AI Lecture Generation Service
- Exact slide count via chunked generation (max 5 slides per AI call)
- Content depth scales automatically with slide count
- Max 70 slides enforced
- JSON repair for truncated responses
- Professor manual text and image injections applied per slide
"""
import os
import json
import re
from groq import Groq
from fastapi import HTTPException

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

MAX_SLIDES = 70
MIN_SLIDES = 3

DOMAIN_SOURCES = {
    "computer":        ["Cormen et al. – Introduction to Algorithms (MIT Press)", "Tanenbaum – Modern Operating Systems", "IEEE Xplore", "ACM Digital Library"],
    "database":        ["Ramakrishnan & Gehrke – Database Management Systems", "Silberschatz – Database System Concepts (7th ed.)", "ACM SIGMOD"],
    "machine learning":["Bishop – Pattern Recognition and ML (Springer)", "Goodfellow – Deep Learning (MIT Press)", "ArXiv.org", "NeurIPS Proceedings"],
    "deep learning":   ["Goodfellow – Deep Learning (MIT Press)", "LeCun et al. – Nature 2015", "fast.ai Notes"],
    "ai":              ["Russell & Norvig – AI: A Modern Approach (4th ed.)", "Stanford CS221 Notes", "DeepMind Research Blog"],
    "software":        ["Pressman – Software Engineering (8th ed.)", "Clean Code – Robert C. Martin", "IEEE Software Journal"],
    "network":         ["Kurose & Ross – Computer Networking (8th ed.)", "Tanenbaum – Computer Networks (5th ed.)", "RFC Archive at IETF"],
    "security":        ["Stallings – Cryptography and Network Security", "Anderson – Security Engineering (3rd ed.)", "OWASP Foundation"],
    "data structure":  ["Cormen – Introduction to Algorithms", "Sedgewick – Algorithms (4th ed.)", "Weiss – Data Structures and Algorithm Analysis"],
    "operating":       ["Tanenbaum – Modern Operating Systems (4th ed.)", "Silberschatz – Operating System Concepts", "Linux Kernel Docs"],
    "math":            ["Stewart – Calculus (8th ed.)", "Strang – Linear Algebra (MIT OCW)", "Wolfram MathWorld"],
    "physics":         ["Halliday, Resnick & Krane – Physics (5th ed.)", "The Feynman Lectures on Physics", "Physical Review Letters"],
    "default":         ["MIT OpenCourseWare", "Springer Academic", "Elsevier ScienceDirect", "Oxford Academic", "Cambridge University Press"],
}

MEDIA_LINKS = {
    "computer":        [{"title": "CS50 – Harvard Intro to CS", "url": "https://cs50.harvard.edu/x"}, {"title": "MIT OCW – Computer Science", "url": "https://ocw.mit.edu/search/?d=Electrical+Engineering+and+Computer+Science"}],
    "database":        [{"title": "CMU Database Group Lectures", "url": "https://www.youtube.com/@CMUDatabaseGroup"}, {"title": "Stanford DB – edX", "url": "https://www.edx.org/learn/databases"}],
    "machine learning":[{"title": "Andrew Ng – ML Specialization", "url": "https://www.coursera.org/specializations/machine-learning-introduction"}, {"title": "fast.ai", "url": "https://www.fast.ai"}, {"title": "Google ML Crash Course", "url": "https://developers.google.com/machine-learning/crash-course"}],
    "deep learning":   [{"title": "fast.ai Practical Deep Learning", "url": "https://www.fast.ai"}, {"title": "MIT 6.S191", "url": "http://introtodeeplearning.com"}],
    "ai":              [{"title": "Stanford CS221", "url": "https://stanford-cs221.github.io/autumn2024/"}, {"title": "MIT 6.034", "url": "https://ocw.mit.edu/courses/6-034-artificial-intelligence-fall-2010/"}],
    "data structure":  [{"title": "Visualgo – Algorithm Visualizations", "url": "https://visualgo.net"}, {"title": "Princeton Algorithms (Coursera)", "url": "https://www.coursera.org/learn/algorithms-part1"}],
    "math":            [{"title": "3Blue1Brown – Visual Math", "url": "https://www.3blue1brown.com"}, {"title": "MIT OCW Mathematics", "url": "https://ocw.mit.edu/search/?d=Mathematics"}],
    "physics":         [{"title": "The Feynman Lectures Online", "url": "https://www.feynmanlectures.caltech.edu"}, {"title": "MIT OCW – Physics", "url": "https://ocw.mit.edu/search/?d=Physics"}],
    "default":         [{"title": "MIT OpenCourseWare", "url": "https://ocw.mit.edu"}, {"title": "Coursera", "url": "https://www.coursera.org"}, {"title": "edX", "url": "https://www.edx.org"}],
}


def _pick(topic: str, lookup: dict) -> list:
    t = topic.lower()
    for key in lookup:
        if key in t:
            return lookup[key]
    return lookup["default"]


def _depth_instruction(total: int) -> str:
    """Depth scales with slide count — more slides = more granular content per slide."""
    if total <= 10:
        return "3 points per slide, each detail 2 sentences"
    elif total <= 20:
        return "3-4 points per slide, each detail 2-3 sentences"
    elif total <= 35:
        return "4 points per slide, each detail 2-3 sentences, include sub-concepts"
    else:
        return "4 points per slide, each detail 3 sentences minimum, deep mechanisms and nuances"


def _make_batches(total: int) -> list:
    """
    Split slides into batches of max 5 (smaller = less truncation risk).
    Returns list of (start, end, role) tuples — 1-indexed.
    """
    batches       = []
    intro_end     = min(3, total)
    summary_start = max(total - 1, intro_end + 1)

    # Intro batch (slides 1-3)
    batches.append((1, intro_end, "intro"))

    # Core batches — max 5 per batch to stay well within token limits
    core_s = intro_end + 1
    core_e = summary_start - 1
    i = core_s
    while i <= core_e:
        end = min(i + 4, core_e)   # 5 slides per batch
        batches.append((i, end, "core"))
        i = end + 1

    # Outro batch (summary + references)
    if summary_start <= total:
        batches.append((summary_start, total, "outro"))

    return batches


def _repair_json(raw: str) -> str:
    """
    Attempt to salvage truncated JSON by:
    1. Truncating after the last complete JSON object
    2. Closing any unclosed arrays/objects
    """
    # Find last complete object — ends with }
    last_close = raw.rfind("}")
    if last_close == -1:
        return raw
    raw = raw[:last_close + 1]

    # Balance brackets
    opens_sq  = raw.count("[") - raw.count("]")
    opens_cur = raw.count("{") - raw.count("}")
    raw += "]" * max(0, opens_sq)
    raw += "}" * max(0, opens_cur)
    return raw


def _parse_json_safe(text: str) -> dict:
    """
    Try to parse JSON. If it fails (truncated), attempt repair then retry.
    Raises ValueError if both attempts fail.
    """
    # First attempt — clean parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Second attempt — repair then parse
    repaired = _repair_json(text)
    return json.loads(repaired)   # raises if still broken


def _gen_batch(start: int, end: int, role: str, total: int,
               topic: str, level: str, prof_note: str,
               sources: list, depth: str) -> list:
    count = end - start + 1

    if role == "intro":
        structure = (
            "Slide 1: Title slide (topic title, academic level, brief tagline)\n"
            "Slide 2: Learning Objectives (5-6 measurable outcomes using Bloom's verbs)\n"
            "Slide 3: Lecture Overview / Roadmap (list main sections)"
        )
    elif role == "outro":
        structure = (
            f"Slide {start}: Summary & Key Takeaways — synthesise the most important concepts\n"
            f"Slide {end}: References & Further Reading — list trusted academic sources"
        )
    else:
        structure = (
            f"Slides {start} to {end}: Core academic content on \"{topic}\".\n"
            f"Each slide covers a DIFFERENT concept — no overlap between slides.\n"
            f"This is part of a {total}-slide lecture — maintain logical progression."
        )

    prompt = f"""You are a university professor generating lecture slides {start} to {end} (out of {total} total) on "{topic}".

Level: {level}
Depth requirement: {depth}
Instructions: {prof_note}
Sources: {", ".join(sources[:3])}

Slide structure for this batch:
{structure}

Return EXACTLY {count} slide objects in this JSON structure:
{{"slides":[
  {{
    "title":"Slide Title Here",
    "points":[
      {{"headline":"Bold headline in 5-7 words","detail":"2-3 sentences explaining this in depth with mechanism and significance."}}
    ],
    "example":"Concrete real-world example using specific named systems or algorithms. Empty string if not applicable.",
    "image_suggestion":"Short description of a helpful diagram, or null",
    "speaker_notes":"3-4 sentences: what to emphasize, questions to ask, connections to make."
  }}
]}}

STRICT RULES:
- Return EXACTLY {count} slides, no more, no less
- {depth}
- Root JSON key MUST be "slides"
- No markdown, no code fences, no text before or after the JSON
- Keep each point detail concise to avoid response truncation
- example field must be a plain string"""

    try:
        c = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Output ONLY valid JSON. No markdown fences. "
                        "Start your response with { and end with }. "
                        "Keep responses concise to avoid truncation."
                    )
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=6000,   # Increased from 4000
        )

        raw = c.choices[0].message.content.strip()

        # Strip markdown fences if model adds them
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*',     '', raw)
        raw = re.sub(r'\s*```$',     '', raw)
        raw = raw.strip()

        # Extract the JSON object
        match = re.search(r'\{', raw)
        if not match:
            raise ValueError("No JSON object found in response")
        json_str = raw[match.start():]

        # Parse with repair fallback
        parsed = _parse_json_safe(json_str)

        # Normalize root key
        slides_list = parsed.get("slides")
        if not slides_list:
            for v in parsed.values():
                if isinstance(v, list) and len(v) > 0:
                    slides_list = v
                    break

        return _clean_slides(slides_list or [])

    except Exception as e:
        # Return placeholder slides — generation continues for other batches
        print(f"[Batch {start}-{end}] failed: {e}")
        return [
            {
                "title":            f"Slide {start + i}: {topic}",
                "points":           [{"headline": "Content unavailable", "detail": "Please regenerate this slide using the refresh button."}],
                "example":          "",
                "image_suggestion": None,
                "speaker_notes":    "",
            }
            for i in range(count)
        ]


def _clean_slides(slides_list: list) -> list:
    """Normalize and validate each slide object."""
    out = []
    for s in slides_list:
        if not isinstance(s, dict):
            continue

        # Normalize points array
        rp = s.get("points", [])
        if isinstance(rp, str):
            rp = [{"headline": rp, "detail": ""}]
        pts = []
        for p in rp:
            if isinstance(p, dict):
                pts.append({
                    "headline": str(p.get("headline", p.get("title", ""))).strip(),
                    "detail":   str(p.get("detail",   p.get("explanation", ""))).strip(),
                })
            elif isinstance(p, str):
                pts.append({"headline": p.strip(), "detail": ""})

        # Normalize example
        ex = s.get("example", "")
        if isinstance(ex, list): ex = " ".join(str(e) for e in ex)
        ex = str(ex).strip()

        # Normalize image suggestion
        img = s.get("image_suggestion")
        if img and str(img).lower() in ("null", "none", "n/a", ""):
            img = None

        out.append({
            "title":            str(s.get("title", "Slide")).strip(),
            "points":           pts,
            "example":          ex,
            "image_suggestion": img,
            "speaker_notes":    str(s.get("speaker_notes", "")).strip(),
        })
    return out


def generate_lecture_json(data) -> dict:
    # ── Enforce slide count limits ────────────────────────────────
    requested = max(MIN_SLIDES, min(int(data.pages_count), MAX_SLIDES))

    topic      = data.topic
    level      = data.course_level
    additional = getattr(data, "additional_instructions", "") or ""
    inc_media  = getattr(data, "include_media", False)
    custom_src = getattr(data, "custom_sources", "") or ""

    trusted = _pick(topic, DOMAIN_SOURCES)
    if custom_src:
        src = [s.strip() for s in custom_src.split(",") if s.strip()] + trusted
    else:
        src = trusted

    prof_note = additional or "Produce a thorough, student-friendly academic lecture."
    depth     = _depth_instruction(requested)

    # ── Chunked generation ────────────────────────────────────────
    all_slides = []
    for (start, end, role) in _make_batches(requested):
        batch = _gen_batch(start, end, role, requested, topic, level, prof_note, src, depth)
        all_slides.extend(batch)

    # ── Trim or pad to exact requested count ──────────────────────
    all_slides = all_slides[:requested]
    while len(all_slides) < requested:
        all_slides.append({
            "title":            f"Additional Content {len(all_slides) + 1}",
            "points":           [{"headline": "Further Discussion", "detail": f"Additional content on {topic}."}],
            "example":          "",
            "image_suggestion": None,
            "speaker_notes":    "",
        })

    # ── Inject professor manual text additions ────────────────────
    for item in (getattr(data, "manual_texts", []) or []):
        try:
            idx  = int(getattr(item, "slide", 1)) - 1
            text = str(getattr(item, "text", "")).strip()
            if 0 <= idx < len(all_slides) and text:
                all_slides[idx]["professor_text"] = text
        except Exception:
            pass

    # ── Inject professor manual image additions ───────────────────
    for item in (getattr(data, "manual_images", []) or []):
        try:
            idx   = int(getattr(item, "slide",    1)) - 1
            fname = str(getattr(item, "filename", ""))
            b64   = str(getattr(item, "data",     ""))
            if 0 <= idx < len(all_slides) and b64:
                all_slides[idx]["professor_image"] = {"filename": fname, "data": b64}
        except Exception:
            pass

    # ── Append media resources slide if requested ─────────────────
    if inc_media:
        ml = _pick(topic, MEDIA_LINKS)
        all_slides.append({
            "title":         "Further Learning & Academic Resources",
            "points":        [{"headline": l["title"], "detail": l["url"]} for l in ml[:5]],
            "example":       f"Visit MIT OpenCourseWare (ocw.mit.edu) for free university-level materials on {topic}.",
            "image_suggestion": None,
            "speaker_notes": f"Direct students to these verified resources for self-study on {topic}.",
        })

    if not all_slides:
        raise HTTPException(status_code=500, detail="Generation failed. Please try again.")

    return {"slides": all_slides}
