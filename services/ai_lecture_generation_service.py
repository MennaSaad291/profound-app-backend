"""
AI Lecture Generation Service — Fast Outline-first approach
=============================================================
Phase 1 : ONE call generates a complete outline (all unique slide titles/subtopics).
Phase 2 : Content batches run in PARALLEL GROUPS of 3 concurrent calls.
          Each content call only gets its immediate neighbours as context (not the
          entire outline) — this keeps prompts small and avoids TPM limits.

Performance for 60 slides:
  - 1 outline call  (~2 s)
  - 12 batches of 5 slides → 4 parallel groups of 3  (~4 × 8 s = ~32 s)
  - Total: ~35 s end-to-end (vs 90 s+ sequential)

"Content unavailable" slides are eliminated by:
  - Removing the full outline from every content prompt (was ~3 600 tokens for 60 slides)
  - Increasing batch size (5) so fewer calls are needed overall
  - Auto-retry on any failure before giving up
"""
import os, json, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from groq import Groq
from fastapi import HTTPException

client = Groq(api_key=os.getenv("GROQ_API_KEY_LECTURE"))

MAX_SLIDES      = 70
MIN_SLIDES      = 3
BATCH_SIZE      = 5      # slides per content call  — 5 is the sweet-spot
MAX_TOKENS      = 3200   # enough for 5 rich slides without overflow
PARALLEL_GROUPS = 3      # concurrent content calls per wave
INTER_WAVE_GAP  = 3      # seconds between waves of parallel calls
RETRY_DELAYS    = [6, 18] # back-off on 429


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — Outline
# ─────────────────────────────────────────────────────────────────────────────

def _gen_outline(topic: str, total: int, prof_note: str) -> list:
    has_custom = (prof_note and prof_note.strip()
                  and prof_note.strip() != "Produce a thorough, student-friendly academic lecture.")
    note_block = f"Professor instructions: {prof_note}\n" if has_custom else ""

    prompt = f"""Design a {total}-slide university lecture on "{topic}".
{note_block}Every slide must cover a UNIQUE subtopic — NO repetition.
Flow: Title → Objectives → Overview → Core content (many specific sub-topics) → Summary.

Slide 1: Title slide
Slide 2: Learning Objectives
Slide 3: Lecture Overview / Roadmap
Slides 4-{total - 1}: Core content — list {total - 4} completely distinct sub-topics of "{topic}"
Slide {total}: Summary & Key Takeaways

Return ONLY a JSON array of exactly {total} objects:
[{{"slide":1,"title":"string","subtopic":"one sentence — exactly what this slide covers"}}]
No markdown, no explanation, just the JSON array."""

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "Output ONLY a valid JSON array. No markdown."},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.4,
                max_tokens=min(total * 55, 4000),
            )
            raw = _strip_fences(resp.choices[0].message.content.strip())
            idx = raw.find('[')
            if idx == -1:
                raise ValueError("No JSON array found")
            outline = json.loads(_fix_array(raw[idx:]))
            if not isinstance(outline, list) or len(outline) < total * 0.75:
                raise ValueError(f"Short outline: {len(outline)}")
            return outline[:total]
        except Exception as e:
            err = str(e).lower()
            if ("rate" in err or "429" in err) and attempt < 2:
                wait = RETRY_DELAYS[attempt]
                print(f"[Outline] 429 — waiting {wait}s"); time.sleep(wait); continue
            print(f"[Outline] failed attempt {attempt+1}: {e}")

    return _fallback_outline(topic, total)


def _fallback_outline(topic: str, total: int) -> list:
    """Deterministic outline — used only if AI outline fails entirely."""
    sections = [
        "Definitions and Terminology",
        "Historical Background and Context",
        "Core Principles and Theory",
        "Fundamental Mechanisms",
        "Key Components and Architecture",
        "Classification and Taxonomy",
        "Mathematical Foundations",
        "Algorithms and Methods",
        "Data Structures and Representations",
        "Design Patterns and Best Practices",
        "Implementation Techniques",
        "Performance Analysis and Complexity",
        "Common Challenges and Pitfalls",
        "Optimisation Strategies",
        "Security Considerations",
        "Scalability and Reliability",
        "Comparison with Alternative Approaches",
        "Industry Standards and Protocols",
        "Tools and Frameworks",
        "Testing and Validation",
        "Real-World Case Studies",
        "Current Research and Open Problems",
        "Future Directions and Trends",
        "Ethical and Social Implications",
        "Integration with Other Domains",
    ]
    out = [
        {"slide": 1, "title": topic,                  "subtopic": "Title and lecture introduction"},
        {"slide": 2, "title": "Learning Objectives",   "subtopic": "Measurable learning outcomes"},
        {"slide": 3, "title": "Lecture Overview",      "subtopic": "Roadmap of today's topics"},
    ]
    core = total - 4
    for i in range(core):
        sec = sections[i % len(sections)]
        out.append({
            "slide":    len(out) + 1,
            "title":    f"{sec}",
            "subtopic": f"{sec} as applied to {topic}",
        })
    out.append({"slide": total, "title": "Summary & Key Takeaways",
                "subtopic": "Synthesis of all covered concepts"})
    return out[:total]


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — Content (parallel groups)
# ─────────────────────────────────────────────────────────────────────────────

def _content_prompt(batch: list, topic: str, total: int,
                    prof_note: str, depth: str,
                    prev_title: str, next_title: str) -> str:
    """
    Compact prompt. Only sends:
    • The assigned subtopics for this batch
    • One slide of context before and after (anti-repetition)
    NOT the full outline — that was the token hog.
    """
    has_custom = (prof_note and prof_note.strip()
                  and prof_note.strip() != "Produce a thorough, student-friendly academic lecture.")
    note_block = f"Professor instructions: {prof_note}\n" if has_custom else ""

    specs = "\n".join(
        f"Slide {o['slide']}: \"{o['title']}\" — {o['subtopic']}"
        for o in batch
    )
    border = ""
    if prev_title:
        border += f"Previous slide already covered: \"{prev_title}\" — do NOT repeat that content.\n"
    if next_title:
        border += f"Next slide will cover: \"{next_title}\" — do NOT pre-empt that content.\n"

    count = len(batch)
    s, e  = batch[0]['slide'], batch[-1]['slide']

    return f"""Generate slides {s}-{e} of a {total}-slide university lecture on "{topic}".
{note_block}{border}
Assign each slide ONLY its listed subtopic:
{specs}

Depth: {depth}

Return EXACTLY {count} slide objects as JSON:
{{"slides":[{{"title":"exact title above","points":[{{"headline":"5-7 word headline","detail":"2-3 sentences"}}],"example":"one concrete named example or empty string","image_suggestion":"specific diagram/chart description","speaker_notes":"2-3 sentences for the lecturer"}}]}}

Rules: exactly {count} slides, root key "slides", no markdown."""


def _gen_content_batch(batch: list, topic: str, total: int,
                       prof_note: str, depth: str,
                       prev_title: str, next_title: str) -> list:
    count = len(batch)
    prompt = _content_prompt(batch, topic, total, prof_note, depth, prev_title, next_title)

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system",
                     "content": "Output ONLY valid JSON. No markdown. Start with { end with }."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=MAX_TOKENS,
            )
            raw   = _strip_fences(resp.choices[0].message.content.strip())
            match = re.search(r'\{', raw)
            if not match:
                raise ValueError("No JSON object")
            parsed = _parse_safe(raw[match.start():])
            slides = parsed.get("slides") or next(
                (v for v in parsed.values() if isinstance(v, list) and v), [])
            cleaned = _clean(slides)
            # Pin titles to outline values
            for i, sl in enumerate(cleaned):
                if i < count:
                    sl['title'] = batch[i]['title']
            return cleaned

        except Exception as e:
            err = str(e).lower()
            if ("rate" in err or "429" in err) and attempt < 2:
                wait = RETRY_DELAYS[attempt]
                print(f"[Batch {batch[0]['slide']}-{batch[-1]['slide']}] 429 — waiting {wait}s")
                time.sleep(wait); continue
            print(f"[Batch {batch[0]['slide']}-{batch[-1]['slide']}] err attempt {attempt+1}: {e}")

    # Last resort — generate placeholder WITH actual title (never "Content unavailable" as title)
    return [{
        "title":            o['title'],
        "points":           [{"headline": o['subtopic'][:60],
                              "detail":   f"Core content about {o['subtopic']}."}],
        "example":          "",
        "image_suggestion": f"Diagram illustrating {o['title']}",
        "speaker_notes":    f"Explain {o['subtopic']} in detail.",
    } for o in batch]


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _depth_instruction(total: int) -> str:
    if total <= 15:
        return "3 points per slide, each 2-3 sentences"
    elif total <= 35:
        return "3 points per slide, each 2 sentences"
    else:
        return "3 points per slide, each 1-2 sentences; be concise but informative"


def _strip_fences(raw: str) -> str:
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*',     '', raw)
    raw = re.sub(r'\s*```$',     '', raw)
    return raw.strip()


def _fix_array(raw: str) -> str:
    last = raw.rfind(']')
    raw  = raw[:last + 1] if last != -1 else raw
    raw += ']' * max(0, raw.count('[') - raw.count(']'))
    return raw


def _fix_obj(raw: str) -> str:
    last = raw.rfind('}')
    if last == -1: return raw
    raw  = raw[:last + 1]
    raw += ']' * max(0, raw.count('[') - raw.count(']'))
    raw += '}' * max(0, raw.count('{') - raw.count('}'))
    return raw


def _parse_safe(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_fix_obj(text))


def _clean(slides_list: list) -> list:
    out = []
    for s in slides_list:
        if not isinstance(s, dict): continue
        rp = s.get("points", [])
        if isinstance(rp, str): rp = [{"headline": rp, "detail": ""}]
        pts = []
        for p in rp:
            if isinstance(p, dict):
                pts.append({"headline": str(p.get("headline", p.get("title", ""))).strip(),
                            "detail":   str(p.get("detail",   p.get("explanation", ""))).strip()})
            elif isinstance(p, str):
                pts.append({"headline": p.strip(), "detail": ""})
        ex = s.get("example", "")
        if isinstance(ex, list): ex = " ".join(str(e) for e in ex)
        ex = str(ex).strip()
        img = s.get("image_suggestion")
        if img and str(img).lower() in ("null", "none", "n/a", ""): img = None
        out.append({
            "title":            str(s.get("title", "Slide")).strip(),
            "points":           pts,
            "example":          ex,
            "image_suggestion": img,
            "speaker_notes":    str(s.get("speaker_notes", "")).strip(),
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def generate_lecture_json(data) -> dict:
    requested  = max(MIN_SLIDES, min(int(data.pages_count), MAX_SLIDES))
    topic      = data.topic
    additional = getattr(data, "additional_instructions", "") or ""
    prof_note  = additional or "Produce a thorough, student-friendly academic lecture."
    depth      = _depth_instruction(requested)

    # ── Phase 1: Outline ───────────────────────────────────────────────────
    print(f"[Lecture] Phase 1 — outline for {requested} slides on '{topic}'")
    outline = _gen_outline(topic, requested, prof_note)

    while len(outline) < requested:          # pad if outline was short
        n = len(outline) + 1
        outline.append({"slide": n, "title": f"{topic} — Part {n}",
                         "subtopic": f"Additional aspect of {topic}"})

    print(f"[Lecture] Outline done: {len(outline)} slides")

    # ── Phase 2: Content in parallel waves ────────────────────────────────
    batches = [outline[i:i + BATCH_SIZE] for i in range(0, len(outline), BATCH_SIZE)]
    results: dict[int, list] = {}

    # Split batches into groups of PARALLEL_GROUPS; each group runs concurrently
    groups = [batches[i:i + PARALLEL_GROUPS]
              for i in range(0, len(batches), PARALLEL_GROUPS)]

    for g_idx, group in enumerate(groups):
        if g_idx > 0:
            time.sleep(INTER_WAVE_GAP)       # brief pause between waves

        with ThreadPoolExecutor(max_workers=PARALLEL_GROUPS) as pool:
            future_map = {}
            for b_idx_in_group, batch in enumerate(group):
                global_b_idx = g_idx * PARALLEL_GROUPS + b_idx_in_group
                b_start = batch[0]['slide']
                b_end   = batch[-1]['slide']

                # Neighbour titles for anti-repetition context
                prev_title = outline[b_start - 2]['title'] if b_start > 1 else ""
                next_title = outline[b_end]['title']       if b_end < requested else ""

                fut = pool.submit(
                    _gen_content_batch,
                    batch, topic, requested, prof_note, depth,
                    prev_title, next_title
                )
                future_map[fut] = global_b_idx

            for fut in as_completed(future_map):
                b_idx = future_map[fut]
                try:
                    results[b_idx] = fut.result()
                except Exception as e:
                    batch = batches[b_idx]
                    print(f"[Wave {g_idx}] batch {b_idx} unhandled: {e}")
                    results[b_idx] = [{
                        "title":            o['title'],
                        "points":           [{"headline": o['subtopic'][:60],
                                              "detail":   f"Core content about {o['subtopic']}."}],
                        "example":          "",
                        "image_suggestion": f"Diagram illustrating {o['title']}",
                        "speaker_notes":    f"Explain {o['subtopic']}.",
                    } for o in batch]

        print(f"[Lecture] Wave {g_idx + 1}/{len(groups)} done")

    # ── Assemble in order ──────────────────────────────────────────────────
    all_slides = []
    for idx in sorted(results):
        all_slides.extend(results[idx])

    all_slides = all_slides[:requested]
    while len(all_slides) < requested:
        i     = len(all_slides)
        title = outline[i]['title'] if i < len(outline) else f"Slide {i + 1}"
        all_slides.append({
            "title":            title,
            "points":           [{"headline": "Key Concepts",
                                  "detail":   f"Important aspects of {topic}."}],
            "example":          "",
            "image_suggestion": None,
            "speaker_notes":    "",
        })

    if not all_slides:
        raise HTTPException(status_code=500, detail="Generation failed. Please try again.")

    print(f"[Lecture] Complete — {len(all_slides)} slides")
    return {"slides": all_slides}
