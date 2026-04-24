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

    # Outro batch (summary)
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
               topic: str, prof_note: str,
               depth: str) -> list:
    count = end - start + 1

    if role == "intro":
        structure = (
            "Slide 1: Title slide (topic title, brief tagline)\n"
            "Slide 2: Learning Objectives (5-6 measurable outcomes using Bloom's verbs)\n"
            "Slide 3: Lecture Overview / Roadmap (list main sections)"
        )
    elif role == "outro":
        structure = (
            f"Slide {start}: Summary & Key Takeaways — synthesise the most important concepts"
        )
    else:
        structure = (
            f"Slides {start} to {end}: Core academic content on \"{topic}\".\n"
            f"Each slide covers a DIFFERENT concept — no overlap between slides.\n"
            f"This is part of a {total}-slide lecture — maintain logical progression."
        )

    # Build a strong professor-instructions block
    has_custom_instructions = (
        prof_note
        and prof_note.strip()
        and prof_note.strip() != "Produce a thorough, student-friendly academic lecture."
    )
    if has_custom_instructions:
        prof_block = f"""
⚠️  PROFESSOR INSTRUCTIONS — MANDATORY — APPLY IN EVERY SLIDE:
{prof_note}

You MUST follow these instructions literally in the slide content:
- If bilingual output is requested (e.g. Arabic+English), add the translation on every bullet point headline
- If a teaching style is specified (e.g. Socratic, problem-based), apply it throughout
- If specific examples, case studies, or topics are named, include them explicitly
- If formatting or structural preferences are given, honour them
These override any default behaviour.
"""
    else:
        prof_block = f"Instructions: {prof_note}"

    prompt = f"""You are a university professor generating lecture slides {start} to {end} (out of {total} total) on "{topic}".

Depth requirement: {depth}
{prof_block}

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
    "image_suggestion":"Specific visual description for a diagram, chart, or illustration that would enhance this slide (e.g. 'flowchart of TCP three-way handshake', 'bar chart comparing sorting algorithm complexities'). Never null — every slide needs a visual.",
    "speaker_notes":"3-4 sentences: what to emphasize, questions to ask, connections to make."
  }}
]}}

STRICT RULES:
- Return EXACTLY {count} slides, no more, no less
- {depth}
- Root JSON key MUST be "slides"
- No markdown, no code fences, no text before or after the JSON
- Keep each point detail concise to avoid response truncation
- example field must be a plain string
- image_suggestion must always be a specific, descriptive string — never null or empty"""

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
    additional = getattr(data, "additional_instructions", "") or ""
    prof_note = additional or "Produce a thorough, student-friendly academic lecture."
    depth     = _depth_instruction(requested)

    # ── Chunked generation ────────────────────────────────────────
    all_slides = []
    for (start, end, role) in _make_batches(requested):
        batch = _gen_batch(start, end, role, requested, topic, prof_note, depth)
        all_slides.extend(batch)

    # ── Trim or pad to exact requested count ──────────────────────
    all_slides = all_slides[:requested]
    while len(all_slides) < requested:
        all_slides.append({
            "title":            f"Additional Content {len(all_slides) + 1}",
            "points":           [{"headline": "Additional Content", "detail": f"Additional content on {topic}."}],
            "example":          "",
            "image_suggestion": None,
            "speaker_notes":    "",
        })


    if not all_slides:
        raise HTTPException(status_code=500, detail="Generation failed. Please try again.")

    return {"slides": all_slides}
