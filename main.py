import os
import bcrypt
import io
import json
import re
import uuid
import datetime
from typing import List, Optional
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import engine, Base, get_db
from models import (UserDB, CourseDB, StudentDB, PublicationDB,
                    ProjectDB, InterestDB, ExamDB, QuestionDB, SubmissionDB)
from schemas import (UserCreate, UserLogin, UserUpdate,
                    LectureRequest, CourseResponse, ExamRequest,
                    ExamResponse, Question,
                    ChangePasswordRequest, VerifyPasswordRequest)

from groq import Groq
from docx import Document

from fastapi import FastAPI, UploadFile, File
import shutil
from grading import grade_text
from plagiarism import plagiarism_score
from file_utils import extract_text
from datetime import datetime

try:
    from services.pptx_service import create_pptx
except ImportError:
    create_pptx = None

load_dotenv()
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Profound Academic API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def clean_markdown(text: str) -> str:
    text_str = str(text)
    return re.sub(r'\*\*(.*?)\*\*', r'\1', text_str).replace('*', '').strip()

#submission------------

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)



@app.post("/grade")
async def grade_files(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db)
):

    results = []

    for file in files:

        file_path = f"{UPLOAD_DIR}/{file.filename}"

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        text = extract_text(file_path)

        ai_grade = grade_text(text)
        plagiarism = plagiarism_score(text)

        new_submission = SubmissionDB(
            student_name=file.filename,
            submission_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
            status="ready",
            ai_grade=ai_grade,
            plagiarism_score=plagiarism,
            essay_content=text
        )

        db.add(new_submission)
        db.commit()
        db.refresh(new_submission)

        results.append({
            "file": file.filename,
            "grade": ai_grade,
            "plagiarism": plagiarism
        })

    return {
        "status": "success",
        "results": results
    }

@app.get("/submissions")
def get_submissions(db: Session = Depends(get_db)):
    submissions = db.query(SubmissionDB).all()

    return [
        {
            "id": s.id,
            "student_name": s.student_name,
            "submission_time": s.submission_time,
            "status": s.status,
            "ai_grade": s.ai_grade,
            "plagiarism_score": s.plagiarism_score
        }
        for s in submissions
    ]


from pydantic import BaseModel


class GradeUpdate(BaseModel):
    ai_grade: int
    status: str

@app.put("/api/submissions/{submission_id}")
def update_submission_grade(submission_id: int, data: GradeUpdate, db: Session = Depends(get_db)):
    submission = db.query(SubmissionDB).filter(SubmissionDB.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    submission.ai_grade = data.ai_grade
    submission.status = data.status
    db.commit()
    return {"message": "Grade updated successfully"}
# --- Auth & Profile ---
@app.post("/register")
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(UserDB).filter(UserDB.email == user.email.lower()).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    salt = bcrypt.gensalt()
    new_user = UserDB(
        full_name=user.full_name, email=user.email.lower(),
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
    return {
        "id": user.id, "full_name": user.full_name, "email": user.email,
        "bio": user.bio, "department": user.department,
        "metrics": {
            "citations": sum(p.citations for p in pubs),
            "students": sum(c.students for c in courses),
            "papers": len(pubs), "projects": len(projects)
        },
        "publications": pubs, "courses": courses, "projects": projects
    }

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

@app.post("/verify-password")
def verify_password(data: VerifyPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.id == data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not bcrypt.checkpw(data.password.encode('utf-8'), user.password_hash.encode('utf-8')):
        raise HTTPException(status_code=401, detail="Incorrect password")
    return {"message": "Password verified"}

@app.post("/change-password")
def change_password(data: ChangePasswordRequest, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.id == data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not bcrypt.checkpw(data.current_password.encode('utf-8'), user.password_hash.encode('utf-8')):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if data.current_password == data.new_password:
        raise HTTPException(status_code=400, detail="New password must be different from current password")
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    salt = bcrypt.gensalt()
    user.password_hash = bcrypt.hashpw(data.new_password.encode('utf-8'), salt).decode('utf-8')
    db.commit()
    return {"message": "Password updated successfully"}

# --- Exam Generation ---
@app.post("/exams/generate", response_model=ExamResponse)
async def generate_exam(request: ExamRequest, db: Session = Depends(get_db)):
    prompt = f"""
    Act as a University Professor. Generate EXACTLY {request.number_of_questions} {request.question_type} questions for: {request.topic}.
    Bloom's Taxonomy: {request.blooms_level}. Difficulty: {request.difficulty}.

    CRITICAL RULES:
    - You MUST generate EXACTLY {request.number_of_questions} questions. Not more, not less.
    - Do NOT generate {request.number_of_questions + 1} questions. Stop at exactly {request.number_of_questions}.
    - question_type for every question MUST be "{request.question_type}"
    - If MCQ: options must be a list of exactly 4 strings
    - If Essay: options must be null

    Output strictly JSON with key "questions" containing EXACTLY {request.number_of_questions} objects with:
    "question_text", "question_type", "options", "correct_answer", "explanation", "difficulty"
    """
    try:
        print(f"Requesting EXACTLY {request.number_of_questions} {request.question_type} | {request.difficulty}")
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a JSON-only academic exam generator. Follow instructions exactly."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        raw = completion.choices[0].message.content
        ai_data = json.loads(raw)
        all_questions = ai_data.get("questions", [])
        all_questions = all_questions[:request.number_of_questions]

        exam_id = str(uuid.uuid4())[:8]
        new_exam = ExamDB(id=exam_id, course_id=request.course_id, title=f"Assessment: {request.topic}")
        db.add(new_exam)

        generated_questions = []
        for q in all_questions:
            q_text = q.get("question_text") or q.get("question")
            q_options = q.get("options")
            q_answer = q.get("correct_answer") or q.get("answer")
            q_type = q.get("question_type") or request.question_type
            q_difficulty = q.get("difficulty") or request.difficulty
            new_q = QuestionDB(
                id=str(uuid.uuid4())[:8], exam_id=exam_id, question_text=q_text,
                question_type=q_type, options=q_options, blooms_level=request.blooms_level,
                difficulty=q_difficulty, correct_answer=q_answer, explanation=q.get("explanation", "")
            )
            db.add(new_q)
            generated_questions.append(Question(
                question_text=q_text, options=q_options, correct_answer=q_answer,
                explanation=q.get("explanation", ""), difficulty=q_difficulty, question_type=q_type
            ))

        db.commit()
        print(f"Saved exactly {len(generated_questions)} questions, exam_id: {exam_id}")
        return {"exam_id": exam_id, "questions": generated_questions}

    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# --- Export Word ---
@app.get("/exams/export-word/{exam_id}")
async def export_exam_word(exam_id: str, db: Session = Depends(get_db)):
    exam = db.query(ExamDB).filter(ExamDB.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    questions = db.query(QuestionDB).filter(QuestionDB.exam_id == exam_id).all()

    doc = Document()
    doc.add_heading(exam.title, 0)
    doc.add_paragraph(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d')}")
    doc.add_paragraph(f"Total Questions: {len(questions)}")
    doc.add_paragraph("")

    for i, q in enumerate(questions, 1):
        p = doc.add_paragraph()
        p.add_run(f"Q{i} [{q.question_type} | {q.difficulty}]: {q.question_text}").bold = True
        if q.question_type == "MCQ" and q.options:
            for opt in q.options:
                doc.add_paragraph(f"   [ ] {opt}")
        doc.add_paragraph("_" * 50)

    stream = io.BytesIO()
    doc.save(stream)
    stream.seek(0)
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=Exam_{exam_id}.docx"}
    )

# --- Lecture Generation ---
@app.post("/api/generate-lecture")
async def generate_lecture(data: LectureRequest):
    prompt = f"Act as a University Professor. Topic: {data.topic}. Output strictly JSON slides."
    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Professional JSON lecture generator."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/professors/{user_id}/courses", response_model=List[CourseResponse])
def get_courses(user_id: int, db: Session = Depends(get_db)):
    return db.query(CourseDB).filter(CourseDB.user_id == user_id).all()


@app.post("/api/grade-essay/{submission_id}")
async def grade_essay(submission_id: int, db: Session = Depends(get_db)):
    submission = db.query(SubmissionDB).filter(SubmissionDB.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    prompt = f"""
    Act as a professor. Grade this essay on a scale of 0-100. 
    Return ONLY a JSON object with keys "score" (int) and "feedback" (string).
    Essay: {submission.essay_content}
    """

    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        ai_result = json.loads(completion.choices[0].message.content)

        submission.ai_grade = ai_result.get("score")
        submission.status = "ready"
        db.commit()

        return {"status": "success", "grade": submission.ai_grade}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))