"""
Lecture routes — Professional AI Authoring System (GPT-4o + DALL-E 3)
Endpoints:
  POST /api/generate-lecture        — full lecture generation
  POST /api/lecture/chat-edit       — AI chat editing (any instruction)
  GET  /api/lecture/{id}/versions   — list all versions
  POST /api/lecture/restore         — restore a specific version
  POST /api/export-pptx             — export to PowerPoint
  POST /api/export-pdf              — export to PDF
  GET  /api/slide-image             — programmatic SVG diagram
  POST /api/generate-slide-image    — DALL-E 3 image for a slide
"""

import io
import os
import json
import hashlib
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, Response
from services.ai_lecture_generation_service import (
    generate_lecture_json,
    apply_chat_edit,
    save_version,
    get_versions,
    restore_version,
)
from services.pptx_service import create_pptx
from schemas import (
    LectureRequest,
    LectureChatEditRequest,
    LectureVersionRestoreRequest,
)

router = APIRouter(prefix="/api", tags=["Lecture"])

# ── Generate ──────────────────────────────────────────────────────────────────

@router.post("/generate-lecture")
async def generate_lecture(data: LectureRequest):
    return generate_lecture_json(data)


# ── Chat Edit ─────────────────────────────────────────────────────────────────

@router.post("/lecture/chat-edit")
async def chat_edit_lecture(data: LectureChatEditRequest):
    result         = apply_chat_edit(data.slides, data.instruction, data.topic,
                                      current_index=data.current_slide_index)
    updated_slides = result["slides"]
    changed        = result["changed_indices"]
    version_num    = save_version(data.lecture_id, updated_slides)
    return {
        "lecture_id":      data.lecture_id,
        "slides":          updated_slides,
        "changed_indices": changed,
        "version":         version_num,
        "message":         result.get("message", f"Version {version_num} saved."),
    }


# ── Version History ───────────────────────────────────────────────────────────

@router.get("/lecture/{lecture_id}/versions")
async def list_versions(lecture_id: str):
    return {"lecture_id": lecture_id, "versions": get_versions(lecture_id)}


@router.post("/lecture/restore")
async def restore_lecture_version(data: LectureVersionRestoreRequest):
    slides = restore_version(data.lecture_id, data.version_number)
    return {"lecture_id": data.lecture_id, "version_number": data.version_number, "slides": slides}


# ── Export PowerPoint ─────────────────────────────────────────────────────────

@router.post("/export-pptx")
async def export_pptx(data: dict):
    if not data.get("slides"):
        raise HTTPException(status_code=400, detail="No slides provided")
    try:
        return StreamingResponse(
            create_pptx(data),
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": "attachment; filename=lecture.pptx"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Export PDF ────────────────────────────────────────────────────────────────

@router.post("/export-pdf")
async def export_pdf(data: dict):
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
        from reportlab.lib.units import cm
        from reportlab.lib import colors

        slides_data = data.get("slides", [])
        if not slides_data:
            raise HTTPException(status_code=400, detail="No slides provided")

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                                leftMargin=2*cm, rightMargin=2*cm,
                                topMargin=2*cm, bottomMargin=2*cm)
        styles   = getSampleStyleSheet()
        t_style  = ParagraphStyle("T",  parent=styles["Heading1"],
                                  fontSize=18, textColor=colors.HexColor("#4F46E5"), spaceAfter=6)
        pt_style = ParagraphStyle("PT", parent=styles["Normal"], fontSize=11, leading=16)
        d_style  = ParagraphStyle("D",  parent=styles["Normal"], fontSize=9,
                                  textColor=colors.HexColor("#374151"), leading=13, leftIndent=14)
        ex_style = ParagraphStyle("EX", parent=styles["Normal"], fontSize=10,
                                  textColor=colors.HexColor("#065F46"), leading=14,
                                  backColor=colors.HexColor("#ECFDF5"), leftIndent=10)
        n_style  = ParagraphStyle("N",  parent=styles["Normal"], fontSize=8,
                                  textColor=colors.HexColor("#6B7280"), leading=12, leftIndent=8)

        story = []
        for i, slide in enumerate(slides_data):
            if not isinstance(slide, dict): continue
            title   = str(slide.get("title", f"Slide {i+1}")).strip()
            points  = slide.get("points", []) or []
            example = str(slide.get("example", "") or "").strip()
            notes   = str(slide.get("speaker_notes", "") or "").strip()

            story.append(Paragraph(f"{i+1}. {title}", t_style))
            story.append(HRFlowable(width="100%", thickness=1,
                                    color=colors.HexColor("#4F46E5"), spaceAfter=8))

            for pt in points:
                hl  = str(pt.get("headline", "")).strip() if isinstance(pt, dict) else str(pt).strip()
                det = str(pt.get("detail",   "")).strip() if isinstance(pt, dict) else ""
                if hl:
                    story.append(Paragraph(f"● {hl}", pt_style))
                if det:
                    story.append(Paragraph(det, d_style))
                story.append(Spacer(1, 4))

            if example:
                story.append(Spacer(1, 6))
                story.append(Paragraph(f"Example: {example}", ex_style))

            if notes:
                story.append(Spacer(1, 6))
                story.append(Paragraph(f"Notes: {notes}", n_style))

            # Quiz questions
            for q in (slide.get("quiz_questions") or []):
                if isinstance(q, dict):
                    story.append(Paragraph(f"Q: {q.get('question','')}", pt_style))
                    for opt in (q.get("options") or []):
                        story.append(Paragraph(f"   {opt}", d_style))

            story.append(Spacer(1, 24))

        doc.build(story)
        buf.seek(0)
        return StreamingResponse(buf, media_type="application/pdf",
                                 headers={"Content-Disposition": "attachment; filename=lecture.pdf"})
    except ImportError:
        raise HTTPException(status_code=500, detail="Install reportlab to enable PDF export.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── SVG Diagram (programmatic, always works) ──────────────────────────────────

@router.get("/slide-image")
async def get_slide_image(
    q: str    = Query(..., description="Slide title"),
    theme: str = Query("Modern Minimalist"),
    points: str = Query("", description="JSON-encoded points array"),
):
    from services.slide_diagram_service import generate_slide_svg
    pts = []
    if points:
        try: pts = json.loads(points)
        except Exception: pts = []
    try:
        svg = generate_slide_svg(title=q, points=pts, theme=theme)
        return Response(content=svg.encode("utf-8"), media_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=86400"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── DALL-E 3 image generation ─────────────────────────────────────────────────

_dalle_cache: dict[str, bytes] = {}

@router.post("/generate-slide-image")
async def generate_slide_image(data: dict):
    """
    Generate a DALL-E 3 image for a slide using its image_prompt.
    Returns the image as JPEG bytes.
    Cached per prompt hash.
    """
    import requests as _req
    from openai import OpenAI
    from fastapi.concurrency import run_in_threadpool

    prompt = str(data.get("image_prompt") or data.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="image_prompt is required")

    cache_key = hashlib.md5(prompt.encode()).hexdigest()
    if cache_key in _dalle_cache:
        return Response(content=_dalle_cache[cache_key], media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})

    openai_key = os.getenv("OPENAI_API_KEY", "")
    if not openai_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    try:
        client = OpenAI(api_key=openai_key)
        # IMPORTANT: client.images.generate() is a *blocking* synchronous call.
        # Running it directly inside this `async def` route freezes FastAPI's
        # single event loop for the whole call, so "parallel" requests from the
        # frontend actually get processed one-by-one on the server, and later
        # ones blow past the client's 45s timeout. run_in_threadpool offloads
        # the blocking call to a worker thread so multiple images really do
        # generate concurrently.
        resp = await run_in_threadpool(
            client.images.generate,
            model="gpt-image-1",
            prompt=prompt,
            size="1024x1024",
            quality="medium",  # "auto"/unset silently picks "high" ($0.167/img,
                                # ~4x medium's $0.042 and ~15x low's $0.011) for
                                # most prompts — medium is plenty for slide art
                                # and was the main driver of unexpectedly fast
                                # credit burn.
            n=1,
        )
        img_data = resp.data[0]

        # gpt-image-1 returns base64, dall-e-3 returns URL
        if hasattr(img_data, 'b64_json') and img_data.b64_json:
            import base64 as _b64
            img_bytes = _b64.b64decode(img_data.b64_json)
        elif hasattr(img_data, 'url') and img_data.url:
            img_resp = await run_in_threadpool(_req.get, img_data.url, timeout=15)
            if img_resp.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to download image")
            img_bytes = img_resp.content
        else:
            raise ValueError("No image data in response")

        _dalle_cache[cache_key] = img_bytes
        mime = "image/png" if img_bytes[:8] == b'\x89PNG\r\n\x1a\n' else "image/jpeg"
        return Response(content=img_bytes, media_type=mime,
                        headers={"Cache-Control": "public, max-age=86400"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image generation error: {str(e)}")