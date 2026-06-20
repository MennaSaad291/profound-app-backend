"""
AI Lecture Generation Service
- Exact slide count via sequential chunked generation
- Sequential calls with retry+backoff to avoid Groq rate limits
- Content depth scales with slide count
- Max 70 slides enforced
- JSON repair for truncated responses
"""
import os
import json
import re
import time
from groq import Groq
from fastapi import HTTPException

client = Groq(api_key=os.getenv("GROQ_API_KEY_LECTURE"))

MAX_SLIDES = 70
MIN_SLIDES = 3
BATCH_SIZE = 3          # slides per API call — small = fewer tokens per call
MAX_TOKENS = 2500       # tight ceiling — enough for 3 rich slides, avoids waste
RETRY_DELAYS = [5, 15]  # seconds to wait on rate-limit before retrying (2 attempts)


def _depth_instruction(total: int) -> str:
    if total <= 10:
        return "2-3 points per slide, each 1-2 sentences"
    elif total <= 25:
        return "3 points per slide, each 2 sentences"
    else:
        return "3 points per slide, each 2 sentences, include key mechanisms"


def _make_batches(total: int) -> list:
    """Split slides into sequential batches of BATCH_SIZE. Returns list of (start, end, role)."""
    batches = []
    i = 1
    while i <= total:
        end = min(i + BATCH_SIZE - 1, total)
        # Assign role based on position
        if i == 1:
            role = "intro"
        elif end == total:
            role = "outro"
        else:
            role = "core"
        batches.append((i, end, role))
        i = end + 1
    return batches


def _repair_json(raw: str) -> str:
    last_close = raw.rfind("}")
    if last_close == -1:
        return raw
    raw = raw[:last_close + 1]
    raw += "]" * max(0, raw.count("[") - raw.count("]"))
    raw += "}" * max(0, raw.count("{") - raw.count("}"))
    return raw


def _parse_json_safe(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_repair_json(text))


def _build_prompt(start: int, end: int, role: str, total: int,
                  topic: str, prof_note: str, depth: str) -> str:
    count = end - start + 1

    if role == "intro":
        structure = (
            "Slide 1: Title slide (topic title + tagline)\n"
            "Slide 2: Learning Objectives (4-5 outcomes)\n"
            "Slide 3: Lecture Overview (list main sections)"
        ) if total >= 3 else f"Slides 1-{count}: Introduction to {topic}"
    elif role == "outro":
        structure = f"Slide {start}: Summary & Key Takeaways — synthesise the most important concepts"
    else:
        structure = (
            f"Slides {start}-{end}: Core content on \"{topic}\". "
            f"Each slide covers a DIFFERENT concept. Part of a {total}-slide lecture."
        )

    has_custom = prof_note and prof_note.strip() and \
                 prof_note.strip() != "Produce a thorough, student-friendly academic lecture."
    if has_custom:
        note_block = f"PROFESSOR INSTRUCTIONS (apply to every slide):\n{prof_note}\n"
    else:
        note_block = ""

    # Compact prompt — every line that can be removed is removed
    return f"""Generate slides {start}-{end} of {total} for a university lecture on "{topic}".
{note_block}Depth: {depth}
Structure: {structure}

Return EXACTLY {count} slide objects as JSON:
{{"slides":[{{"title":"string","points":[{{"headline":"5-7 word headline","detail":"2 sentence explanation"}}],"example":"one concrete example or empty string","image_suggestion":"specific diagram or chart description","speaker_notes":"2-3 sentences"}}]}}

Rules: exactly {count} slides, root key "slides", no markdown, no extra text."""


def _gen_batch_with_retry(start: int, end: int, role: str, total: int,
                          topic: str, prof_note: str, depth: str) -> list:
    """Call the Groq API for one batch, retrying on rate-limit errors."""
    prompt = _build_prompt(start, end, role, total, topic, prof_note, depth)
    count  = end - start + 1
    last_err = None

    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": "Output ONLY valid JSON. No markdown. Start with { end with }."
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=MAX_TOKENS,
            )
            raw = resp.choices[0].message.content.strip()

            # Strip markdown fences
            raw = re.sub(r'^```json\s*', '', raw)
            raw = re.sub(r'^```\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            raw = raw.strip()

            # Extract JSON object
            match = re.search(r'\{', raw)
            if not match:
                raise ValueError("No JSON object found")
            parsed = _parse_json_safe(raw[match.start():])

            slides_list = parsed.get("slides")
            if not slides_list:
                for v in parsed.values():
                    if isinstance(v, list) and v:
                        slides_list = v
                        break

            return _clean_slides(slides_list or [])

        except Exception as e:
            last_err = e
            err_str  = str(e).lower()
            is_rate_limit = "rate" in err_str or "429" in err_str or \
                            "tokens per minute" in err_str or "per minute" in err_str

            if is_rate_limit and attempt < len(RETRY_DELAYS):
                wait = RETRY_DELAYS[attempt]
                print(f"[Batch {start}-{end}] Rate limit hit — waiting {wait}s (attempt {attempt+1})")
                time.sleep(wait)
                continue
            else:
                print(f"[Batch {start}-{end}] Failed after {attempt+1} attempt(s): {e}")
                break

    # Return placeholder slides so generation continues
    return [
        {
            "title":            f"Slide {start + i}: {topic}",
            "points":           [{"headline": "Content unavailable",
                                  "detail": "Please regenerate this slide using the refresh button."}],
            "example":          "",
            "image_suggestion": None,
            "speaker_notes":    "",
        }
        for i in range(count)
    ]


def _clean_slides(slides_list: list) -> list:
    out = []
    for s in slides_list:
        if not isinstance(s, dict):
            continue
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

        ex = s.get("example", "")
        if isinstance(ex, list):
            ex = " ".join(str(e) for e in ex)
        ex = str(ex).strip()

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
    requested = max(MIN_SLIDES, min(int(data.pages_count), MAX_SLIDES))
    topic     = data.topic
    additional = getattr(data, "additional_instructions", "") or ""
    prof_note  = additional or "Produce a thorough, student-friendly academic lecture."
    depth      = _depth_instruction(requested)

    batches    = _make_batches(requested)
    all_slides = []

    # ── Sequential generation with inter-batch pause ──────────────────────────
    for idx, (start, end, role) in enumerate(batches):
        # Small pause between calls to stay within tokens-per-minute limit.
        # Skip pause before first batch.
        if idx > 0:
            time.sleep(2)

        slides = _gen_batch_with_retry(start, end, role, requested,
                                       topic, prof_note, depth)
        all_slides.extend(slides)

    # ── Trim / pad to exact count ─────────────────────────────────────────────
    all_slides = all_slides[:requested]
    while len(all_slides) < requested:
        all_slides.append({
            "title":            f"Additional Content {len(all_slides) + 1}",
            "points":           [{"headline": "Additional Content",
                                  "detail":   f"Additional content on {topic}."}],
            "example":          "",
            "image_suggestion": None,
            "speaker_notes":    "",
        })

    if not all_slides:
        raise HTTPException(status_code=500, detail="Generation failed. Please try again.")

    return {"slides": all_slides}
