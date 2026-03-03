import os
import bcrypt
import pandas as pd
import io
import json
import re
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import engine, Base, get_db
from models import UserDB, CourseDB, StudentDB, PublicationDB, ProjectDB, InterestDB
from schemas import (
    UserCreate, UserLogin, UserUpdate, 
    LectureRequest, CourseResponse, 
    PublicationCreate, ProjectCreate, InterestCreate
)

from google import genai
from google.genai import types
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.enum.shapes import MSO_SHAPE

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Profound Academic API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def clean_markdown(text: str) -> str:
    """Removes markdown formatting for clean slide text."""
    return re.sub(r'\*\*(.*?)\*\*', r'\1', str(text)).replace('*', '').strip()


@app.post("/register")
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(UserDB).filter(UserDB.email == user.email.lower()).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    salt = bcrypt.gensalt()
    new_user = UserDB(
        full_name=user.full_name,
        email=user.email.lower(),
        password_hash=bcrypt.hashpw(user.password.encode('utf-8'), salt).decode('utf-8')
    )
    db.add(new_user)
    db.commit()
    return {"message": "Success"}

@app.post("/login")
def login_user(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(UserDB).filter(UserDB.email == user.email.lower()).first()
    if not db_user or not bcrypt.checkpw(user.password.encode('utf-8'), db_user.password_hash.encode('utf-8')):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"user": {"id": db_user.id, "name": db_user.full_name}}

@app.get("/profile/{user_id}")
def get_profile(user_id: int, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    pubs = db.query(PublicationDB).filter(PublicationDB.user_id == user_id).all()
    courses = db.query(CourseDB).filter(CourseDB.user_id == user_id).all()
    projects = db.query(ProjectDB).filter(ProjectDB.user_id == user_id).all()
    interests = db.query(InterestDB).filter(InterestDB.user_id == user_id).all()
    
    return {
        "id": user.id,
        "full_name": user.full_name,
        "bio": user.bio,
        "department": user.department,
        "metrics": {
            "citations": sum(p.citations for p in pubs),
            "students": sum(c.students for c in courses),
            "papers": len(pubs),
            "projects": len(projects)
        },
        "publications": pubs,
        "courses": courses,
        "projects": projects,
        "interests": [i.name for i in interests]
    }


@app.post("/courses-with-students")
async def create_course_with_excel(
    user_id: int = Form(...), 
    code: str = Form(...), 
    name: str = Form(...), 
    semester: str = Form("TBA"), 
    schedule: str = Form("TBA"), 
    room: str = Form("TBA"), 
    file: Optional[UploadFile] = File(None), 
    db: Session = Depends(get_db)
):
    student_count = 0
    df = None
    if file and file.filename:
        df = pd.read_excel(io.BytesIO(await file.read()))
        student_count = len(df)
        
    new_course = CourseDB(
        user_id=user_id, code=code, name=name, 
        semester=semester, students=student_count, 
        status="active", schedule=schedule, room=room
    )
    db.add(new_course)
    db.flush() 
    
    if df is not None:
        for _, row in df.iterrows():
            db.add(StudentDB(
                student_id=str(row['id']), 
                name=row['name'], 
                department=row.get('department', 'N/A'), 
                course_id=new_course.id
            ))
    db.commit()
    return {"message": "Success"}

@app.get("/professors/{user_id}/courses", response_model=List[CourseResponse])
def get_courses(user_id: int, db: Session = Depends(get_db)):
    return db.query(CourseDB).filter(CourseDB.user_id == user_id).all()


CANVAS_SYSTEM_PROMPT = """
Act as the 'Gemini Canvas' Designer. 
For every slide, you MUST define:
1. 'bg_hex': A professional background hex color.
2. 'accent_hex': A matching accent color for bars/titles.
3. 'title_font' & 'body_font': Modern font pairings (e.g., 'Montserrat', 'Inter').
4. 'image_prompt': A high-fidelity studio prompt for Nano Banana 2.
5. 'content': 4-6 deeply detailed academic bullet points.
6. 'speaker_notes': Deep professor-level explanation.
Output strictly valid JSON.
"""

@app.post("/api/generate-lecture")
async def generate_lecture(data: LectureRequest):
    try:
        response = client.models.generate_content(
            model='gemini-3.1-flash',
            contents=f"Topic: {data.topic}. Theme: {data.theme}. Level: {data.course_level}. Slide Count: {data.pages_count}.",
            config=types.GenerateContentConfig(
                system_instruction=CANVAS_SYSTEM_PROMPT,
                response_mime_type="application/json"
            )
        )
        return json.loads(response.text)
    except Exception as e:
        status_code = 429 if "429" in str(e) else 500
        raise HTTPException(status_code=status_code, detail=str(e))

@app.post("/api/export-pptx")
async def export_pptx(data: dict):
    try:
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5) 

        for slide_data in data.get('slides', []):
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            
            bg_hex = slide_data.get("bg_hex", "FFFFFF").lstrip("#")
            accent_hex = slide_data.get("accent_hex", "9333EA").lstrip("#")
            
            slide.background.fill.solid()
            slide.background.fill.fore_color.rgb = RGBColor.from_string(bg_hex)
            
            circle = slide.shapes.add_shape(
                MSO_SHAPE.OVAL, Inches(10), Inches(-1.5), Inches(5), Inches(5)
            )
            circle.fill.solid()
            circle.fill.fore_color.rgb = RGBColor.from_string(accent_hex)
            circle.line.fill.background()

            title_box = slide.shapes.add_textbox(Inches(0.8), Inches(1), Inches(9), Inches(1.5))
            tf = title_box.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = clean_markdown(slide_data.get("title", "Untitled"))
            p.font.size = Pt(44)
            p.font.bold = True
            p.font.name = slide_data.get("title_font", "Montserrat")
            p.font.color.rgb = RGBColor.from_string(accent_hex)

            body_box = slide.shapes.add_textbox(Inches(0.8), Inches(2.5), Inches(8), Inches(4))
            body_tf = body_box.text_frame
            body_tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
            
            for point in slide_data.get("content", []):
                p = body_tf.add_paragraph()
                p.text = f"• {clean_markdown(point)}"
                p.font.size = Pt(22)
                p.font.name = slide_data.get("body_font", "Inter")
                p.space_after = Pt(10)

        stream = io.BytesIO()
        prs.save(stream)
        stream.seek(0)
        return StreamingResponse(
            stream, 
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))