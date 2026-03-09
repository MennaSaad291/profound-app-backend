import os
import bcrypt
import pandas as pd
import io
import json
import re
from typing import List, Optional
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

# Database Imports
from database import engine, Base, get_db
from models import UserDB, CourseDB, StudentDB, PublicationDB, ProjectDB, InterestDB
from schemas import (
    UserCreate, UserLogin, UserUpdate, 
    LectureRequest, CourseResponse, 
    PublicationCreate, ProjectCreate, InterestCreate
)

# AI & Presentation Libraries
from groq import Groq
from services.pptx_service import create_pptx

load_dotenv()
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Profound Academic API")

# --- 1. Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 2. Free High-Speed AI Engine ---
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# --- 3. Professional Theme System ---
THEMES = {
    "Modern Minimalist": {"bg": "FFFFFF", "text": "1A1A1A", "accent": "4F46E5", "accent2": "F3F4F6"},
    "Dark Mode Tech": {"bg": "0F172A", "text": "F8FAFC", "accent": "38BDF8", "accent2": "1E293B"},
    "Classic Academic": {"bg": "FDFBF7", "text": "1E1E1E", "accent": "800000", "accent2": "E5E7EB"},
    "Vibrant Creative": {"bg": "FFF7ED", "text": "431407", "accent": "F97316", "accent2": "FFEDD5"}
}

def clean_markdown(text: str) -> str:
    """Removes markdown and cleans strings for PPTX safety."""
    text_str = str(text)
    # Remove markdown bolding and stars
    text_str = re.sub(r'\*\*(.*?)\*\*', r'\1', text_str).replace('*', '')
    return text_str.strip()

# --- 4. User Authentication & Profile ---
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
    if not user: raise HTTPException(status_code=404, detail="User not found")
    pubs = db.query(PublicationDB).filter(PublicationDB.user_id == user_id).all()
    courses = db.query(CourseDB).filter(CourseDB.user_id == user_id).all()
    projects = db.query(ProjectDB).filter(ProjectDB.user_id == user_id).all()
    return {
        "id": user.id, "full_name": user.full_name, "bio": user.bio, "department": user.department,
        "metrics": {
            "citations": sum(p.citations for p in pubs),
            "students": sum(c.students for c in courses),
            "papers": len(pubs), "projects": len(projects)
        },
        "publications": pubs, "courses": courses, "projects": projects
    }

# --- 5. Excel Student Upload Logic ---
@app.post("/courses-with-students")
async def create_course_with_excel(
    user_id: int = Form(...), code: str = Form(...), name: str = Form(...), 
    semester: str = Form("TBA"), schedule: str = Form("TBA"), room: str = Form("TBA"), 
    file: Optional[UploadFile] = File(None), db: Session = Depends(get_db)
):
    student_count = 0
    df = None
    if file and file.filename:
        df = pd.read_excel(io.BytesIO(await file.read()))
        student_count = len(df)
    new_course = CourseDB(
        user_id=user_id, code=code, name=name, semester=semester, 
        students=student_count, status="active", schedule=schedule, room=room
    )
    db.add(new_course)
    db.flush() 
    if df is not None:
        for _, row in df.iterrows():
            db.add(StudentDB(
                student_id=str(row['id']), name=row['name'], 
                department=row.get('department', 'N/A'), course_id=new_course.id
            ))
    db.commit()
    return {"message": "Success"}

@app.get("/professors/{user_id}/courses", response_model=List[CourseResponse])
def get_courses(user_id: int, db: Session = Depends(get_db)):
    return db.query(CourseDB).filter(CourseDB.user_id == user_id).all()

# --- 6. AI Lecture Generation (Updated for Structured Bullets) ---
@app.post("/api/generate-lecture")
async def generate_lecture(data: LectureRequest):
    prompt = f"""
    Act as a University Professor. Topic: {data.topic}. Level: {data.course_level}. 
    Slides: {data.pages_count}. Theme: {data.theme}. 
    Instructions: {data.additional_instructions}.
    
    CRITICAL STRUCTURE RULES:
    1. Output strictly valid JSON.
    2. "content" MUST be a LIST of strings (bullet points).
    3. Each bullet point should be concise (max 20 words).
    4. Provide 4 to 6 bullet points per slide.
    5. NO long paragraphs inside the content list.
    
    Format: 
    {{ 
      "slides": [ 
        {{ 
          "title": "Title of Slide", 
          "content": ["Point 1", "Point 2", "Point 3", "Point 4"], 
          "speaker_notes": "Deep technical explanation for the professor." 
        }} 
      ] 
    }}
    """
    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": "You are a professional JSON lecture generator. You always return content as a list of bullet points."}, 
                      {"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        # Parse and return
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- 7. Professional PPTX Designer Engine ---
@app.post("/api/export-pptx")
async def export_pptx(data: dict):
    try:
        # data should already contain the list of slides with "content" as a list
        return StreamingResponse(create_pptx(data), media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))