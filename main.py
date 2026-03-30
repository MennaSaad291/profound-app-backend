import os
import bcrypt
import io
import json
import re
import uuid
import datetime
import pandas as pd
from typing import List, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import engine, Base, get_db
from models import (UserDB, CourseDB, StudentDB, PublicationDB,
                    ProjectDB, InterestDB, ExamDB, QuestionDB, SubmissionDB, PerformanceDB, ErrorAnalysisDB,
                    AssignmentDB, GradeUpdate, FinalizeRequest)
from schemas import (UserCreate, UserLogin, UserUpdate,
                    LectureRequest, CourseResponse, ExamRequest,
                    ExamResponse, Question,
                    ChangePasswordRequest, VerifyPasswordRequest)
from routes import analysis
from groq import Groq
from docx import Document

from fastapi import FastAPI, UploadFile, File
import shutil
from file_utils import extract_text
from datetime import datetime
from services.grading_service import perform_nlp_grading


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
    
# ---upload grade and attendence---
@app.post("/upload-performance")
async def upload_performance_sheet(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    content = await file.read()
    if file.filename.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(content))
    else:
        df = pd.read_excel(io.BytesIO(content))

    required_columns = ["student_id", "course_id", "grade", "attendance"]
    if not all(col in df.columns for col in required_columns):
        raise HTTPException(
            status_code=400, 
            detail="Sheet must have: student_id, course_id, grade, and attendance"
        )

    records_added = 0
    for _, row in df.iterrows():
        current_student_id = str(row["student_id"])
        current_course_id = int(row["course_id"])

        student = db.query(StudentDB).filter(
            StudentDB.student_id == current_student_id,
            StudentDB.course_id == current_course_id
        ).first()

        if student:
            new_perf = PerformanceDB(
                student_id=student.id,
                course_id=current_course_id, 
                grade=float(row["grade"]),
                attendance=float(row["attendance"])
            )
            db.add(new_perf)
            records_added += 1

    db.commit()
    return {"message": f"Successfully processed {records_added} records from the sheet"}    


@app.get("/analysis/common-errors")
def common_error_analysis(
    course_id: int,
    db: Session = Depends(get_db)
):

    total_errors = db.query(func.count(ErrorAnalysisDB.id)).filter(
        ErrorAnalysisDB.course_id == course_id
    ).scalar()

    categories = db.query(
        ErrorAnalysisDB.error_category,
        func.count(ErrorAnalysisDB.id).label("count")
    ).filter(
        ErrorAnalysisDB.course_id == course_id
    ).group_by(
        ErrorAnalysisDB.error_category
    ).all()

    result = []

    for cat in categories:

        percentage = (cat.count / total_errors) * 100

        error_types = db.query(
            ErrorAnalysisDB.error_type,
            func.count(ErrorAnalysisDB.id).label("count"),
            func.count(func.distinct(ErrorAnalysisDB.student_id)).label("students")
        ).filter(
            ErrorAnalysisDB.course_id == course_id,
            ErrorAnalysisDB.error_category == cat.error_category
        ).group_by(
            ErrorAnalysisDB.error_type
        ).all()

        patterns = []

        for e in error_types:

            patterns.append({
                "error_type": e.error_type,
                "occurrences": e.count,
                "affected_students": e.students
            })

        result.append({
            "category": cat.error_category,
            "total_errors": cat.count,
            "percentage": round(percentage,2),
            "patterns": patterns
        })

    return result

@app.get("/analysis/department-benchmarks")
def department_benchmarks(course_id: int, db: Session = Depends(get_db)):

    course = db.query(CourseDB).filter(CourseDB.id == course_id).first()

    department = course.department

    your_avg_grade = db.query(func.avg(PerformanceDB.grade)).filter(
        PerformanceDB.course_id == course_id
    ).scalar()

    dept_avg_grade = db.query(func.avg(PerformanceDB.grade)).join(
        CourseDB, PerformanceDB.course_id == CourseDB.id
    ).filter(
        CourseDB.department == department
    ).scalar()

    your_attendance = db.query(func.avg(PerformanceDB.attendance)).filter(
        PerformanceDB.course_id == course_id
    ).scalar()

    dept_attendance = db.query(func.avg(PerformanceDB.attendance)).join(
        CourseDB, PerformanceDB.course_id == CourseDB.id
    ).filter(
        CourseDB.department == department
    ).scalar()

    your_pass_rate = db.query(
        func.count().filter(PerformanceDB.grade >= 50) * 100.0 / func.count()
    ).filter(
        PerformanceDB.course_id == course_id
    ).scalar()

    dept_pass_rate = db.query(
        func.count().filter(PerformanceDB.grade >= 50) * 100.0 / func.count()
    ).join(
        CourseDB, PerformanceDB.course_id == CourseDB.id
    ).filter(
        CourseDB.department == department
    ).scalar()
    your_assignment_completion = db.query(
        func.count().filter(AssignmentDB.is_submitted == True) * 100.0 / func.count()
    ).filter(
        AssignmentDB.course_id == course_id
    ).scalar() or 0.0

    dept_assignment_completion = db.query(
        func.count().filter(AssignmentDB.is_submitted == True) * 100.0 / func.count()
    ).join(
        CourseDB, AssignmentDB.course_id == CourseDB.id
    ).filter(
        CourseDB.department == department
    ).scalar() or 0.0
    return {
        "average_grade": {
            "course": round(your_avg_grade,1),
            "department": round(dept_avg_grade,1),
            "difference": round(dept_avg_grade - your_avg_grade,1)
        },
        "pass_rate": {
            "course": round(your_pass_rate,1),
            "department": round(dept_pass_rate,1),
            "difference": round(dept_pass_rate - your_pass_rate,1)
        },
        "attendance_rate": {
            "course": round(your_attendance,1),
            "department": round(dept_attendance,1),
            "difference": round(dept_attendance - your_attendance,1)
        },
        "assignment_completion": {
            "course": round(your_assignment_completion, 1),
            "department": round(dept_assignment_completion, 1),
            "difference": round(dept_assignment_completion - your_assignment_completion, 1)
        }
    }
app.include_router(analysis.router)


#submission------------
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.get("/submissions")
async def get_all_submissions(db: Session = Depends(get_db)):
    submissions = db.query(SubmissionDB).order_by(SubmissionDB.id.desc()).all()
    return submissions


@app.put("/api/submissions/{submission_id}")
def update_submission_grade(submission_id: int, data: GradeUpdate, db: Session = Depends(get_db)):
    submission = db.query(SubmissionDB).filter(SubmissionDB.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    submission.ai_grade = data.ai_grade
    submission.status = data.status
    db.commit()
    return {"message": "Grade updated successfully"}

# --------grading----------
@app.post("/grade-submission/{assignment_id}")
async def grade_submission(assignment_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename_only = os.path.splitext(file.filename)[0]
    temp_path = f"temp_{file.filename}"

    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        text_content = extract_text(temp_path)
        assignment = db.query(AssignmentDB).filter(AssignmentDB.id == assignment_id).first()
        rubric = assignment.assignment_name if assignment else "General Academic Rubric"

        nlp_results = perform_nlp_grading(text_content, rubric)

        new_submission = SubmissionDB(
            student_name=filename_only,
            submission_time=datetime.now().strftime("%Y-%m-%d %I:%M %p"),
            status="ready",
            ai_grade=nlp_results.get("score_out_of_100"),
            plagiarism_score=15,
            essay_content=text_content,
            grade_report=nlp_results
        )

        db.add(new_submission)
        db.commit()
        db.refresh(new_submission)
        return {"status": "success", "id": new_submission.id}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)



@app.post("/assignments/{assignment_id}/run-grading")
async def run_grading(assignment_id: int, db: Session = Depends(get_db)):
    submissions = db.query(SubmissionDB).filter(
        SubmissionDB.status == "pending"
    ).all()

    for sub in submissions:
        report = perform_nlp_grading(sub.essay_content, "Standard Essay Rubric")
        sub.ai_grade = report.get("score_out_of_100")
        sub.grade_report = report
        sub.status = "ready"

    db.commit()
    return {"message": f"Processed {len(submissions)} submissions"}


@app.post("/submissions/{submission_id}/finalize")
async def finalize_submission(
        submission_id: int,
        data: FinalizeRequest,
        db: Session = Depends(get_db)
):
    submission = db.query(SubmissionDB).filter(SubmissionDB.id == submission_id).first()

    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    submission.ai_grade = data.manual_grade
    submission.status = "graded"

    db.commit()
    db.refresh(submission)

    return {
        "status": "success",
        "message": "Grade finalized",
        "final_grade": submission.ai_grade
    }

