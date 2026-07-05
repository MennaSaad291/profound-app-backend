import os, json, re, time, uuid, asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from fastapi import HTTPException

# ── OpenAI client (lazy) ─────────────────────────────────────────────────────
_client: OpenAI | None = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        key = os.getenv("OPENAI_API_KEY", "")
        if not key:
            raise HTTPException(status_code=500,
                detail="OPENAI_API_KEY not set.")
        _client = OpenAI(api_key=key)
    return _client

GPT_MODEL = "gpt-4o"
GPT_MINI  = "gpt-4o-mini"

MAX_SLIDES   = 60
MIN_SLIDES   = 3
BATCH_SIZE   = 8     # slides per GPT call — stays well within 16k token limit
RETRY_DELAYS = [3, 8, 15]

_version_store: dict[str, list] = {}

NO_IMAGE_TITLES = {
    "learning objectives", "objectives", "prerequisites",
    "summary", "key takeaways", "takeaways",
    "review questions", "questions", "further reading",
    "references", "agenda", "conclusion", "discussion",
    "quiz", "exercise", "activity",
}


# ── GPT caller ────────────────────────────────────────────────────────────────

def _call_gpt(prompt: str, model: str = GPT_MODEL,
              max_tokens: int = 8000, temperature: float = 0.2) -> str:
    for attempt in range(4):
        try:
            resp = _get_client().chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content":
                     "You are a senior university professor creating professional lecture slides. "
                     "Output ONLY valid JSON matching the schema exactly. No markdown."},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content
        except Exception as e:
            err = str(e)
            if "rate_limit" in err.lower() or "429" in err:
                wait = RETRY_DELAYS[min(attempt, 2)]
                print(f"[GPT] Rate limit — waiting {wait}s")
                time.sleep(wait); continue
            if attempt < 3:
                print(f"[GPT] attempt {attempt+1} failed: {err[:80]}")
                time.sleep(RETRY_DELAYS[min(attempt, 2)]); continue
            raise
    raise RuntimeError("GPT failed after 4 attempts")


# ── JSON utilities ────────────────────────────────────────────────────────────

def _md(text: str) -> str:
    return re.sub(r'\*+', '', str(text)).replace("__", "").strip()

def _should_have_image(title: str) -> bool:
    t = title.lower().strip()
    return not any(kw in t for kw in NO_IMAGE_TITLES)

def _validate_image_prompt(prompt: str, title: str) -> str:
    """Ensure image_prompt is a real DALL-E prompt, not a filename."""
    if not prompt: return ""
    p = prompt.strip()
    bad_exts = ('.png','.jpg','.jpeg','.svg','.webp','.gif','.bmp')
    if any(p.lower().endswith(ext) for ext in bad_exts) or len(p) < 30:
        return (f"A professional educational illustration for a university slide about '{title}'. "
                f"Clear diagram showing the concept, clean white background, textbook style.")
    return p

def _repair_json(raw: str) -> str:
    """Extract complete slide objects from potentially truncated JSON."""
    raw = raw.strip()
    try: json.loads(raw); return raw
    except Exception: pass

    slides_pos = raw.find('"slides"')
    arr_start  = raw.find('[', slides_pos if slides_pos != -1 else 0)
    if arr_start == -1: return raw

    content = raw[arr_start:]
    objects, depth, start = [], 0, None
    for i, ch in enumerate(content):
        if ch == '{':
            if depth == 0: start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    obj = json.loads(content[start:i+1])
                    objects.append(obj)
                except Exception: pass
                start = None

    if objects:
        print(f"[JSON repair] Recovered {len(objects)} slides")
        return json.dumps({"slides": objects})
    return raw


# ── Slide cleaner ─────────────────────────────────────────────────────────────

def _clean_slides(raw_list: list) -> list:
    out = []
    for s in raw_list:
        if not isinstance(s, dict): continue
        rp = s.get("points", [])
        if isinstance(rp, str): rp = [{"headline": rp, "detail": ""}]
        pts = []
        for p in rp:
            if isinstance(p, dict):
                hl  = _md(p.get("headline", p.get("title", ""))).strip()
                det = _md(p.get("detail",   p.get("explanation", ""))).strip()
                if hl: pts.append({"headline": hl, "detail": det})
            elif isinstance(p, str) and p.strip():
                pts.append({"headline": _md(p.strip()), "detail": ""})

        def sv(k, fb=""):
            v = s.get(k) or fb
            sv2 = _md(str(v))
            return "" if sv2.lower() in ("null","none","n/a","") else sv2

        ex = s.get("example","")
        if isinstance(ex, list): ex = " | ".join(str(e) for e in ex)
        ex = _md(str(ex).strip())
        if ex.lower() in ("null","none","n/a",""): ex = ""

        title = sv("title") or "Slide"

        img_q = sv("image_keyword") or sv("image_search_query") or ""
        if not _should_have_image(title): img_q = ""

        fallback = [
            {"headline":"Core Definition",       "detail":f"Precise definition of {title} as used in academic and professional contexts."},
            {"headline":"Key Characteristics",   "detail":f"The main properties and attributes that define {title}."},
            {"headline":"Practical Applications","detail":f"How {title} is applied in real-world engineering and professional settings."},
            {"headline":"Performance Factors",   "detail":"Critical metrics, trade-offs, and efficiency considerations."},
            {"headline":"Industry Standards",    "detail":"Best practices and standards adopted by leading organisations worldwide."},
        ]
        while len(pts) < 5:
            pts.append(fallback[len(pts)])

        out.append({
            "title":               title,
            "points":              pts[:5],
            "example":             ex,
            "practical_example":   sv("practical_example"),
            "industry_example":    sv("industry_example"),
            "analogy":             sv("analogy"),
            "code_example":        sv("code_example"),
            "code_language":       sv("code_language"),
            "diagram":             sv("diagram"),
            "image_keyword":       img_q,
            "image_search_query":  img_q,
            "image_prompt":        _validate_image_prompt(sv("image_prompt"), title),
            "image_suggestion":    sv("image_suggestion"),
            "speaker_notes":       sv("speaker_notes"),
            "professor_text":      sv("professor_text"),
            "quiz_questions":      s.get("quiz_questions") or [],
            "discussion_questions":s.get("discussion_questions") or [],
            "assignments":         s.get("assignments") or [],
            "tips":                s.get("tips") or [],
            "common_mistakes":     s.get("common_mistakes") or [],
        })
    return out


# ── Reference summariser ─────────────────────────────────────────────────────

def _summarise_reference(ref: str, topic: str) -> str:
    """
    Condense an arbitrarily long reference into a compact ~800-char summary
    using gpt-4o-mini (very cheap).  The summary is generated ONCE and reused
    by every batch, so the total token cost is:
        1 mini call  +  N batch calls each carrying ~200 tokens of summary
    instead of the old approach of embedding raw text chunks in every batch.
    """
    # If the reference is already short there is nothing to save — use it as-is.
    if len(ref) <= 900:
        return ref.strip()

    prompt = (
        f'Summarise the following reference material for a university lecture on "{topic}".\n'
        f'Output a single dense paragraph (max 150 words) that captures:\n'
        f'- The main topics, definitions, and key facts\n'
        f'- Any specific terminology, figures, or examples worth preserving\n'
        f'- The overall scope and depth of the material\n\n'
        f'Reference:\n{ref[:12000]}\n\n'   # cap at 12k chars ≈ ~3k tokens input
        f'Summary (plain text, no bullet points, no markdown):'
    )
    try:
        # Use a plain text response (no json_object format needed here)
        resp = _get_client().chat.completions.create(
            model=GPT_MINI,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200,   # ~150 words output
        )
        summary = resp.choices[0].message.content.strip()
        print(f"[Ref] Summarised {len(ref)} chars → {len(summary)} chars")
        return summary
    except Exception as e:
        print(f"[Ref] Summarisation failed ({e}), falling back to first 900 chars")
        return ref[:900].strip()


# ── Slide batch prompt ────────────────────────────────────────────────────────

def _batch_prompt(topic: str, batch_titles: list, covered_titles: list,
                  prof_note: str, ref_summary: str, is_last_batch: bool) -> str:
    covered_block = ""
    if covered_titles:
        covered_block = f"\nAlready covered in previous slides (DO NOT REPEAT): {json.dumps(covered_titles)}\n"

    last_note = ""
    if is_last_batch:
        last_note = f"""
IMPORTANT — this is the LAST batch of the lecture.
The last two slides in this batch MUST be:
  - Second to last: "Summary & Key Takeaways" (synthesise all covered topics)
  - Last: "Review Questions & Further Reading" (with quiz_questions, discussion_questions, assignments)
"""

    slides_to_make = "\n".join(f"  - {t}" for t in batch_titles)

    custom = f"\nProfessor instructions (MANDATORY): {prof_note}\n" if prof_note.strip() else ""
    ref_block = f"\nReference material (base slide content on this):\n{ref_summary}\n" if ref_summary else ""

    return f"""You are creating university lecture slides on "{topic}".
{custom}{ref_block}{covered_block}{last_note}
Generate content for exactly these {len(batch_titles)} slides:
{slides_to_make}

MANDATORY QUALITY STANDARDS for every slide:
1. EXACTLY 5 bullet points
2. headline: 5-10 word specific concept (e.g. "TCP Three-Way Handshake Process")
3. detail: EXACTLY 2 complete sentences, 25-45 words total
4. example: real company/person + specific numbers (e.g. "Google's network handles 8.5B searches daily")
5. practical_example: one hands-on thing a student can try
6. industry_example: how a Fortune 500 company uses this
7. analogy: everyday life comparison
8. speaker_notes: 3-4 rich sentences with analogy and class question
9. image_prompt: descriptive DALL-E generation prompt (NOT a filename — write what to draw)
   - e.g. "A detailed diagram of the OSI model showing 7 layers as colored horizontal bands with protocol labels, clean white background, textbook style"
   - Leave EMPTY for: Summary, Review Questions, Learning Objectives, Prerequisites
10. code_example: real runnable code ONLY for algorithm/implementation slides, else ""
11. diagram: valid Mermaid syntax ONLY for process/flow/architecture slides, else ""
12. NO markdown (**bold**) in any field

For the Review Questions slide ONLY, populate:
- quiz_questions: 5 MCQ objects: {{"question":"...","options":["A)...","B)...","C)...","D)..."],"answer":"A"}}
- discussion_questions: 3 open-ended questions
- assignments: 2 practical task descriptions

Return exactly this JSON (root key = "slides"):
{{"slides":[{{"title":"exact slide title","points":[{{"headline":"phrase","detail":"sentence 1. sentence 2."}}],"example":"...","practical_example":"...","industry_example":"...","analogy":"...","code_example":"","code_language":"","diagram":"","image_keyword":"3-5 words","image_prompt":"DALL-E prompt or empty","speaker_notes":"...","professor_text":"","quiz_questions":[],"discussion_questions":[],"assignments":[],"tips":[],"common_mistakes":[]}}]}}"""


# ── Outline builder ───────────────────────────────────────────────────────────

def _build_outline(topic: str, count: int, prof_note: str) -> list[str]:
    """Ask GPT to plan exactly `count` unique slide titles."""
    custom = f"\nProfessor instructions: {prof_note}\n" if prof_note.strip() else ""

    prompt = f"""Plan a {count}-slide university lecture on "{topic}".{custom}
Rules:
- Every slide covers a UNIQUE, SPECIFIC subtopic — NO repeats
- Slide 1: Title slide ("{topic}")
- Slide 2: Learning Objectives
- Slide 3: Prerequisites & Context
- Slides 4 to {count-2}: Core content (UNIQUE topics: definitions, history, theory, types, mechanisms, algorithms, tools, security, best practices, mistakes, applications, case studies, comparisons, research, ethics, future)
- Slide {count-1}: Summary & Key Takeaways
- Slide {count}: Review Questions & Further Reading

Return ONLY a JSON array of exactly {count} title strings:
["Title 1", "Title 2", ...]"""

    for attempt in range(3):
        try:
            raw    = _call_gpt(prompt, model=GPT_MODEL, max_tokens=count*30+500)
            parsed = json.loads(raw)
            # Handle both array and object with array value
            if isinstance(parsed, list):
                titles = [str(t).strip() for t in parsed if t]
            else:
                titles = next(([str(t).strip() for t in v if t]
                               for v in parsed.values() if isinstance(v, list)), [])
            if len(titles) >= count * 0.8:
                return titles[:count]
        except Exception as e:
            print(f"[Outline] attempt {attempt+1}: {e}")
            if attempt < 2: time.sleep(2)

    # Fallback outline
    core_topics = [
        "Definitions and Terminology", "Historical Background and Evolution",
        "Core Theory and Principles", "Types and Classification",
        "Key Components and Architecture", "How It Works — Mechanisms",
        "Algorithms and Methods", "Mathematical Foundations",
        "Implementation and Tools", "Performance and Optimization",
        "Security Considerations", "Best Practices", "Common Mistakes",
        "Real-World Applications", "Industry Case Studies",
        "Comparison with Alternatives", "Current Research Trends",
        "Ethical Implications", "Future Directions", "Standards and Protocols",
        "Tools and Frameworks", "Testing and Validation",
        "Integration with Other Systems", "Scalability Considerations",
    ]
    titles = [topic]
    titles += ["Learning Objectives", "Prerequisites & Context"]
    for i in range(count - 5):
        t = core_topics[i % len(core_topics)]
        titles.append(f"{t} in {topic}")
    titles += ["Summary & Key Takeaways", "Review Questions & Further Reading"]
    return titles[:count]


# ── Parallel image generation ─────────────────────────────────────────────────

def _generate_all_images_parallel(slides: list) -> dict[str, bytes]:
    """
    Generate ALL slide images in parallel using a thread pool.
    Returns dict: {image_prompt: bytes}
    This is called server-side so all images are ready before the response is sent.
    """
    import requests as _req
    import base64 as _b64

    prompts = {
        s["image_prompt"]: s["title"]
        for s in slides
        if s.get("image_prompt", "").strip()
    }

    if not prompts:
        return {}

    results: dict[str, bytes] = {}

    def _fetch_one(prompt_title_pair):
        prompt, title = prompt_title_pair
        for attempt in range(2):
            try:
                resp = _get_client().images.generate(
                    model="gpt-image-1",
                    prompt=prompt,
                    size="1024x1024",
                    n=1,
                )
                img_data = resp.data[0]
                if hasattr(img_data, "b64_json") and img_data.b64_json:
                    return prompt, _b64.b64decode(img_data.b64_json)
                if hasattr(img_data, "url") and img_data.url:
                    r = _req.get(img_data.url, timeout=15)
                    if r.status_code == 200:
                        return prompt, r.content
            except Exception as e:
                print(f"[IMG] attempt {attempt+1} failed for '{title}': {e}")
                if attempt == 0: time.sleep(2)
        return prompt, None

    # Use thread pool — all images generated concurrently
    max_workers = min(len(prompts), 5)  # max 5 parallel image requests
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, (p, t)): p
                   for p, t in prompts.items()}
        for fut in as_completed(futures):
            try:
                prompt, img_bytes = fut.result()
                if img_bytes:
                    results[prompt] = img_bytes
                    print(f"[IMG] Generated: {prompt[:40]}…")
            except Exception as e:
                print(f"[IMG] Future error: {e}")

    print(f"[IMG] Parallel generation done: {len(results)}/{len(prompts)} succeeded")
    return results


# ── Main generation ───────────────────────────────────────────────────────────

def generate_lecture_json(data) -> dict:
    requested  = max(MIN_SLIDES, min(int(data.pages_count), MAX_SLIDES))
    topic      = data.topic.strip()
    additional = getattr(data, "additional_instructions", "") or ""
    prof_note  = additional.strip()
    ref        = getattr(data, "reference_context", "") or ""
    lecture_id = str(uuid.uuid4())

    print(f"[GPT-4o] Generating {requested} slides on '{topic}'")

    # ── Step 1: Build outline (unique titles for all slides) ──────────────────
    print("[GPT-4o] Building outline…")
    all_titles = _build_outline(topic, requested, prof_note)
    # Ensure exactly `requested` titles
    while len(all_titles) < requested:
        all_titles.append(f"{topic} — Advanced Topic {len(all_titles)+1}")
    all_titles = all_titles[:requested]

    # Enforce: last 2 must be Summary + Review
    all_titles[-2] = "Summary & Key Takeaways"
    all_titles[-1] = "Review Questions & Further Reading"

    print(f"[GPT-4o] Outline: {all_titles}")

    # ── Step 2: Generate content in batches ───────────────────────────────────
    # Split all titles into batches of BATCH_SIZE, ALWAYS keeping last 2 in final batch
    core_titles   = all_titles[:-2]
    tail_titles   = all_titles[-2:]

    batches: list[list[str]] = []
    for i in range(0, len(core_titles), BATCH_SIZE):
        batches.append(core_titles[i:i+BATCH_SIZE])
    # Add tail as its own batch (or merged with last batch if last batch is small)
    if batches and len(batches[-1]) < BATCH_SIZE - 1:
        batches[-1].extend(tail_titles)
    else:
        batches.append(tail_titles)

    all_slides   = []
    covered_list = []

    # Summarise the reference ONCE with gpt-4o-mini, then reuse that compact
    # summary in every batch prompt.  This gives all batches full awareness of
    # the reference content at a fraction of the token cost of injecting raw
    # text into each call.
    ref_summary = _summarise_reference(ref, topic) if ref else ""

    for batch_idx, batch_titles in enumerate(batches):
        is_last = (batch_idx == len(batches) - 1)
        print(f"[GPT-4o] Batch {batch_idx+1}/{len(batches)}: {batch_titles}")

        prompt = _batch_prompt(topic, batch_titles, covered_list,
                               prof_note, ref_summary, is_last_batch=is_last)

        batch_slides = None
        for attempt in range(4):
            try:
                raw = _call_gpt(prompt, model=GPT_MODEL,
                                max_tokens=len(batch_titles)*600+500)
                raw = _repair_json(raw)
                parsed = json.loads(raw)
                raw_slides = parsed.get("slides") or next(
                    (v for v in parsed.values() if isinstance(v, list)), [])
                if not raw_slides:
                    raise ValueError("Empty slides")
                batch_slides = _clean_slides(raw_slides)
                print(f"[GPT-4o] Batch {batch_idx+1} OK: {len(batch_slides)} slides")
                break
            except Exception as e:
                print(f"[GPT-4o] Batch {batch_idx+1} attempt {attempt+1}: {e}")
                if attempt < 3: time.sleep(RETRY_DELAYS[min(attempt, 2)])

        if not batch_slides:
            # Fallback: create basic slides for this batch
            batch_slides = [{
                "title": t, "points": [
                    {"headline": f"{t} — Overview",      "detail": f"Core concept of {t} in the context of {topic}. Essential for understanding the subject."},
                    {"headline": "Key Principles",       "detail": "Fundamental rules and properties that govern this topic."},
                    {"headline": "Practical Application","detail": "How this concept is applied in real-world systems and products."},
                    {"headline": "Industry Relevance",   "detail": "Why this matters in modern technology and engineering."},
                    {"headline": "Common Challenges",    "detail": "Typical difficulties practitioners face and how to overcome them."},
                ],
                "example": f"Leading organisations use {t.lower()} to improve system performance.",
                "practical_example":"","industry_example":"","analogy":"",
                "code_example":"","code_language":"","diagram":"",
                "image_keyword":"","image_prompt":"","image_suggestion":"",
                "speaker_notes":f"Discuss {t}. Ask students for examples.",
                "professor_text":"",
                "quiz_questions":[],"discussion_questions":[],"assignments":[],
                "tips":[],"common_mistakes":[],
            } for t in batch_titles]

        all_slides.extend(batch_slides)
        covered_list.extend([s["title"] for s in batch_slides])

    # ── Step 3: Deduplicate — ensure Summary/Review only once at the end ──────
    seen_titles = set()
    deduped = []
    tail_reserved = []

    for s in all_slides:
        t = s["title"].lower()
        is_tail = any(k in t for k in ("summary", "key takeaway", "review question", "further reading"))
        if is_tail:
            # Only keep LAST occurrence of each tail slide type
            tail_reserved = [x for x in tail_reserved if x["title"].lower() not in t]
            tail_reserved.append(s)
        elif s["title"] not in seen_titles:
            seen_titles.add(s["title"])
            deduped.append(s)

    # Ensure exactly 1 Summary and 1 Review at the very end
    final = deduped
    # Add tail slides (deduplicated)
    tail_by_type = {}
    for s in tail_reserved:
        t = s["title"].lower()
        key = "summary" if "summary" in t or "takeaway" in t else "review"
        tail_by_type[key] = s  # last one wins

    if "summary" in tail_by_type: final.append(tail_by_type["summary"])
    if "review"  in tail_by_type: final.append(tail_by_type["review"])

    # Trim/pad to exact count
    final = final[:requested]
    while len(final) < requested:
        final.insert(-2 if len(final) >= 2 else len(final),
                     {"title": f"{topic} — Part {len(final)}",
                      "points": [
                          {"headline": "Core Concept", "detail": f"Important aspect of {topic}. Essential for complete understanding."},
                          {"headline": "Key Principles", "detail": "Fundamental rules governing this topic."},
                          {"headline": "Applications", "detail": "Real-world use in systems and products."},
                          {"headline": "Best Practices", "detail": "Industry-proven guidelines."},
                          {"headline": "Future Outlook", "detail": "Emerging developments in this area."},
                      ],
                      "example":"","practical_example":"","industry_example":"","analogy":"",
                      "code_example":"","code_language":"","diagram":"",
                      "image_keyword":"","image_prompt":"","image_suggestion":"",
                      "speaker_notes":"","professor_text":"",
                      "quiz_questions":[],"discussion_questions":[],"assignments":[],
                      "tips":[],"common_mistakes":[]})

    save_version(lecture_id, final)
    print(f"[GPT-4o] Complete: {len(final)} slides | id={lecture_id}")

    return {
        "lecture_id": lecture_id,
        "slides":     final,
        "metadata": {
            "topic":      topic,
            "slide_count":len(final),
            "model":      GPT_MODEL,
        },
    }


# ── Chat Edit ─────────────────────────────────────────────────────────────────

_ALL_SLIDES_PHRASES = (
    "all slides", "every slide", "each slide", "entire lecture",
    "whole lecture", "whole deck", "throughout the lecture", "throughout",
)

def _extract_target_indices(instruction: str, total: int, current_index: int | None) -> list[int]:
    """Figure out which slide(s) an instruction is actually scoped to, instead of
    assuming the whole deck. Returns a sorted list of 0-based indices."""
    instr = instruction.lower()

    if any(p in instr for p in _ALL_SLIDES_PHRASES):
        return list(range(total))

    nums: set[int] = set()

    # Ranges: "slides 3-5", "slide 3 to 5"
    for m in re.finditer(r"slides?\s+(\d+)\s*(?:-|to)\s*(\d+)", instr):
        a, b = int(m.group(1)), int(m.group(2))
        nums.update(range(min(a, b), max(a, b) + 1))

    # Strip matched ranges so they aren't re-parsed as loose numbers below
    stripped = re.sub(r"slides?\s+\d+\s*(?:-|to)\s*\d+", " ", instr)

    # Lists / singles: "slide 9", "slides 4 and 6", "slides 3, 5, 7"
    for m in re.finditer(r"slides?\s+((?:\d+\s*(?:,|and|&)?\s*)+)", stripped):
        nums.update(int(n) for n in re.findall(r"\d+", m.group(1)))

    valid = sorted(i - 1 for i in nums if 1 <= i <= total)
    if valid:
        return valid


    if current_index is not None and 0 <= current_index < total:
        return [current_index]

    return list(range(total))


def apply_chat_edit(slides: list, instruction: str, topic: str,
                     current_index: int | None = None) -> dict:
    total   = len(slides)
    targets = _extract_target_indices(instruction, total, current_index)

    payload = [{"index": i + 1, "slide": slides[i]} for i in targets]

    prompt = f"""Edit these specific slides from a university lecture on "{topic}".

Instruction: "{instruction}"

Slides to edit (JSON, 1-based index matches their position in the full deck):
{json.dumps(payload, ensure_ascii=False)}

Apply the instruction ONLY to these slides. Do not invent edits beyond what was asked.
If the instruction asks to split one slide into multiple, return multiple slide
objects for that index, in order.

Each slide needs: title, points(5 objects:headline+detail), example, practical_example,
industry_example, analogy, code_example, code_language, diagram, image_keyword,
image_prompt(DALL-E prompt, NOT filename), speaker_notes, professor_text,
quiz_questions, discussion_questions, assignments, tips, common_mistakes.

Return ONLY: {{"edits":[{{"index":<original 1-based index>,"slides":[<one or more slide objects>]}}]}}"""

    for attempt in range(3):
        try:
            raw    = _call_gpt(prompt, model=GPT_MINI,
                                max_tokens=min(len(targets) * 500 + 1500, 16000))
            raw    = _repair_json(raw)
            parsed = json.loads(raw)
            edits  = parsed.get("edits") or next(
                (v for v in parsed.values() if isinstance(v, list)), [])
            if not edits: raise ValueError("Empty")

            edit_map: dict[int, list] = {}
            for e in edits:
                idx = e.get("index")
                sl  = e.get("slides")
                if isinstance(idx, int) and isinstance(sl, list) and sl:
                    edit_map[idx - 1] = _clean_slides(sl)

            if not edit_map: raise ValueError("No usable edits returned")


            new_slides: list = []
            changed: list[int] = []
            for i, original in enumerate(slides):
                if i in edit_map:
                    start = len(new_slides)
                    new_slides.extend(edit_map[i])
                    changed.extend(range(start, len(new_slides)))
                else:
                    new_slides.append(original)

            label = ", ".join(str(i + 1) for i in targets)
            return {
                "slides": new_slides,
                "changed_indices": changed,
                "message": f"Done. Updated slide(s) {label} ({len(changed)} slide(s) affected).",
            }
        except Exception as e:
            print(f"[ChatEdit] attempt {attempt+1}: {e}")
            if attempt < 2: time.sleep(RETRY_DELAYS[attempt])

    return {"slides":slides,"changed_indices":[],
            "message":"Edit could not be applied. Please try again."}


# ── Version History ───────────────────────────────────────────────────────────

def save_version(lecture_id: str, slides: list) -> int:
    if lecture_id not in _version_store:
        _version_store[lecture_id] = []
    _version_store[lecture_id].append(list(slides))
    return len(_version_store[lecture_id])

def get_versions(lecture_id: str) -> list:
    return [{"version": i+1, "slide_count": len(v)}
            for i, v in enumerate(_version_store.get(lecture_id,[]))]

def restore_version(lecture_id: str, version_number: int) -> list:
    versions = _version_store.get(lecture_id, [])
    idx = version_number - 1
    if idx < 0 or idx >= len(versions):
        raise HTTPException(status_code=404, detail=f"Version {version_number} not found")
    return versions[idx]