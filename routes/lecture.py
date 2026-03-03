from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.services.ai_service import generate_lecture_json
from app.services.pptx_service import create_pptx
from app.schemas import LectureRequest 

router = APIRouter(prefix="/api", tags=["Lecture"])

@app.post("/generate-lecture")
async def generate_lecture(data: LectureRequest):
    return generate_lecture_json(data)

@app.post("/export-pptx")
async def export_pptx(data: dict):
    file_stream = create_pptx(data)
    return StreamingResponse(
        file_stream, 
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )