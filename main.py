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

from database import engine, Base, get_db
from models import UserDB, CourseDB, StudentDB, PublicationDB, ProjectDB, InterestDB
from schemas import (
    UserCreate, UserLogin, UserUpdate, 
    LectureRequest, CourseResponse, 
    PublicationCreate, ProjectCreate, InterestCreate,
    ChangePasswordRequest, VerifyPasswordRequest
)

# AI & Presentation Libraries
from groq import Groq
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_AUTO_SIZE, PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

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

# --- 2. Free High-Speed AI Engine (Unlimited Access) ---
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# --- 3. Professional Theme System ---
THEMES = {
    "Modern Minimalist": {"bg": "FFFFFF", "text": "1A1A1A", "accent": "4F46E5", "accent2": "F3F4F6"},
    "Dark Mode Tech": {"bg": "0F172A", "text": "F8FAFC", "accent": "38BDF8", "accent2": "1E293B"},
    "Classic Academic": {"bg": "FDFBF7", "text": "1E1E1E", "accent": "800000", "accent2": "E5E7EB"},
    "Vibrant Creative": {"bg": "FFF7ED", "text": "431407", "accent": "F97316", "accent2": "FFEDD5"}
}

def clean_markdown(text: str) -> str:
    """Removes markdown formatting for clean slide text."""
    return re.sub(r'\*\*(.*?)\*\*', r'\1', str(text)).replace('*', '').strip()

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
        "id": user.id, "full_name": user.full_name, "email": user.email, "bio": user.bio, "department": user.department,
        "metrics": {
            "citations": sum(p.citations for p in pubs),
            "students": sum(c.students for c in courses),
            "papers": len(pubs), "projects": len(projects)
        },
        "publications": pubs, "courses": courses, "projects": projects
    }

@app.post("/verify-password")
def verify_password(data: VerifyPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.id == data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not bcrypt.checkpw(data.password.encode('utf-8'), user.password_hash.encode('utf-8')):
        raise HTTPException(status_code=401, detail="Incorrect password")
    return {"message": "Password verified"}


@app.put("/profile/{user_id}")
def update_profile(user_id: int, data: UserUpdate, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.full_name = data.full_name
    user.bio = data.bio
    user.department = data.department
    db.commit()
    return {"message": "Profile updated successfully"}


@app.post("/change-password")
def change_password(data: ChangePasswordRequest, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.id == data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Verify current password
    if not bcrypt.checkpw(data.current_password.encode('utf-8'), user.password_hash.encode('utf-8')):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    
    # Check new password is different from current
    if data.current_password == data.new_password:
        raise HTTPException(status_code=400, detail="New password must be different from current password")

    # Validate new password length
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    
    # Hash and save new password
    salt = bcrypt.gensalt()
    user.password_hash = bcrypt.hashpw(data.new_password.encode('utf-8'), salt).decode('utf-8')
    db.commit()
    
    return {"message": "Password updated successfully"}

# --- 6. Course & Student Excel Uploads ---
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

# --- 7. AI Lecture Generation ---
@app.post("/api/generate-lecture")
async def generate_lecture(data: LectureRequest):
    prompt = f"""
    Act as a University Professor. Topic: {data.topic}. Level: {data.course_level}. 
    Slides: {data.pages_count}. Theme: {data.theme}. Instructions: {data.additional_instructions}.
    Output strictly valid JSON with keys: "slides" [title, content[], speaker_notes].
    """
    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": "JSON-only academic generator."}, 
                      {"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- 8. Professional PPTX Designer Engine ---
@app.post("/api/export-pptx")
async def export_pptx(data: dict):
    try:
        theme = THEMES.get(data.get('theme'), THEMES['Modern Minimalist'])
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5) 

        for i, slide_data in enumerate(data.get('slides', [])):
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            
            slide.background.fill.solid()
            slide.background.fill.fore_color.rgb = RGBColor.from_string(theme["bg"])
            
            bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(0.12), Inches(7.5))
            bar.fill.solid()
            bar.fill.fore_color.rgb = RGBColor.from_string(theme["accent"])
            bar.line.fill.background()

            is_title = (i == 0)
            
            top = Inches(2.5) if is_title else Inches(0.5)
            title_box = slide.shapes.add_textbox(Inches(0.8), top, Inches(11.5), Inches(1.5))
            tf = title_box.text_frame
            p = tf.paragraphs[0]
            p.text = clean_markdown(slide_data.get("title", "Untitled")).upper() if is_title else clean_markdown(slide_data.get("title", "Untitled"))
            p.font.size = Pt(54) if is_title else Pt(40)
            p.font.bold = True
            p.font.color.rgb = RGBColor.from_string(theme["accent"])
            if is_title: p.alignment = PP_ALIGN.CENTER

            if not is_title:
                body_box = slide.shapes.add_textbox(Inches(0.8), Inches(1.8), Inches(11.5), Inches(4.8))
                body_tf = body_box.text_frame
                body_tf.word_wrap = True
                for point in slide_data.get("content", []):
                    p = body_tf.add_paragraph()
                    p.text = f"• {clean_markdown(point)}"
                    p.font.size = Pt(22)
                    p.font.color.rgb = RGBColor.from_string(theme["text"])
                    p.space_after = Pt(12)

        stream = io.BytesIO()
        prs.save(stream)
        stream.seek(0)
        return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))