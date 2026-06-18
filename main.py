import os
import bcrypt
import io
import json
import re
import uuid
import pandas as pd
from typing import List, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session
from pydantic import BaseModel

from fastapi import Form
import os
from fastapi import Form, File, UploadFile, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
import database
from database import engine, Base, get_db
from models import (UserDB, CourseDB, StudentDB, PublicationDB,
                    ProjectDB, InterestDB, ExamDB, QuestionDB, SubmissionDB, PerformanceDB, ErrorAnalysisDB,
                    AssignmentDB, GradeUpdate, FinalizeRequest, LectureSlotDB)
from schemas import (UserCreate, UserLogin, UserUpdate,
                    LectureRequest, CourseResponse, ExamRequest,
                    ExamResponse, Question,AssignmentCreate,CourseCreate,
                    ChangePasswordRequest, VerifyPasswordRequest)
from routes import analysis
from routes import lecture
from routes import courses as courses_router
from groq import Groq
from docx import Document

from fastapi import FastAPI, UploadFile, File
import shutil
from file_utils import extract_text
from datetime import datetime

from services import grading_service
from services.grading_service import perform_nlp_grading


try:
    from services.pptx_service import create_pptx
except ImportError:
    create_pptx = None

# try:
#     from services.ai_lecture_generation_service import generate_lecture_json
# except ImportError:
#     from ai_lecture_generation_service import generate_lecture_json



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

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY_ANALYSIS"))

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
            raw_answer = q.get("correct_answer") or q.get("answer")
            # AI sometimes returns int index (0-3) or letter (A-D) instead of full option text
            if isinstance(raw_answer, int) and q_options and 0 <= raw_answer < len(q_options):
                q_answer = str(q_options[raw_answer])
            elif isinstance(raw_answer, str) and len(raw_answer) == 1 and raw_answer.upper() in "ABCD" and q_options:
                idx = ord(raw_answer.upper()) - ord('A')
                q_answer = str(q_options[idx]) if 0 <= idx < len(q_options) else raw_answer
            else:
                q_answer = str(raw_answer) if raw_answer is not None else ""
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
    doc.add_paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d')}")
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
# @app.post("/api/generate-lecture")
# async def generate_lecture(data: LectureRequest):
#     """
#     Generate lecture slides using the AI service.
#     Always returns {"slides": [...]} with validated structure.
#     """
#     return generate_lecture_json(data)


def _build_pptx_response(data: dict):
    """Create a PPTX streaming response from slide data."""
    if create_pptx is None:
        raise HTTPException(status_code=500, detail="PowerPoint service not available. Install python-pptx.")
    if not data.get("slides"):
        raise HTTPException(status_code=400, detail="No slides provided")
    try:
        file_stream = create_pptx(data)
        return StreamingResponse(
            file_stream,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": "attachment; filename=lecture.pptx"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/export-pptx")
async def export_pptx(data: dict):
    return _build_pptx_response(data)

@app.post("/export-pptx")
async def export_pptx_alias(data: dict):
    return _build_pptx_response(data)

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
@app.post("/upload-performance")
async def upload_performance_sheet(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    try:
        content = await file.read()

        if file.filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))

    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "message": "Invalid or corrupted file. Please upload a valid Excel or CSV file."
            }
        )

    required_columns = ["student_id", "course_id", "grade", "attendance"]

    if not all(col in df.columns for col in required_columns):
        return JSONResponse(
            status_code=400,
            content={
                "message": "Invalid file structure. Please upload a file containing: student_id, course_id, grade, and attendance."
            }
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

    return {
        "message": f"Successfully processed {records_added} records from the sheet"
    }   
# ---upload grade and attendence---
# @app.post("/upload-performance")
# async def upload_performance_sheet(
#     file: UploadFile = File(...),
#     db: Session = Depends(get_db)
# ):
#     content = await file.read()
#     if file.filename.endswith(".csv"):
#         df = pd.read_csv(io.BytesIO(content))
#     else:
#         df = pd.read_excel(io.BytesIO(content))


#     required_columns = ["student_id", "course_id", "grade", "attendance"]

#     if not all(col in df.columns for col in required_columns):
#         return JSONResponse(
#             status_code=400,
#             content={
#                 "message": "Invalid file structure. Please upload a file containing: student_id, course_id, grade, and attendance."
#             }
#         )

#     records_added = 0
#     for _, row in df.iterrows():
#         current_student_id = str(row["student_id"])
#         current_course_id = int(row["course_id"])

#         student = db.query(StudentDB).filter(
#             StudentDB.student_id == current_student_id,
#             StudentDB.course_id == current_course_id
#         ).first()

#         if student:
#             new_perf = PerformanceDB(
#                 student_id=student.id,
#                 course_id=current_course_id, 
#                 grade=float(row["grade"]),
#                 attendance=float(row["attendance"])
#             )
#             db.add(new_perf)
#             records_added += 1

#     db.commit()
#     return {"message": f"Successfully processed {records_added} records from the sheet"}    

app.include_router(analysis.router)
app.include_router(lecture.router)
app.include_router(courses_router.router)


#submission------------
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


from fastapi.middleware.cors import CORSMiddleware

# 1. ADD THIS to allow Flutter to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. UPDATE THIS to show the last submission first
@app.get("/submissions")
async def get_submissions(assignment_id: int, db: Session = Depends(get_db)):
    return db.query(SubmissionDB).filter(
        SubmissionDB.assignment_id == assignment_id
    ).order_by(SubmissionDB.id.desc()).all()
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



# Ensure the upload directory exists
UPLOAD_DIR = "uploads/assignments"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# --- Assignment Management ---

@app.post("/assignments")
async def create_assignment(
    assignment_name: str = Form(...),
    course_id: int = Form(...),
    assignment_question: Optional[str] = Form(None),
    assignment_file: Optional[UploadFile] = File(None),
    is_model_answer: bool = Form(...),
    model_answer: Optional[str] = Form(None),
    rubric: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    file_local_path = None

    if assignment_file:
        try:
            # Use a safe filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = f"{course_id}_{timestamp}_{assignment_file.filename}".replace(" ", "_")
            file_local_path = os.path.join(UPLOAD_DIR, safe_name)

            with open(file_local_path, "wb") as buffer:
                shutil.copyfileobj(assignment_file.file, buffer)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"File save error: {str(e)}")

    course = db.query(CourseDB).filter(CourseDB.id == course_id).first()
    if not course:
        raise HTTPException(status_code=400, detail="Course not found")

    new_assignment = AssignmentDB(
        assignment_name=assignment_name,
        course_id=course_id,
        assignment_question=assignment_question,
        assignment_file_path=file_local_path,
        model_answer=model_answer,
        rubric=rubric,
        is_model_answer=is_model_answer
    )

    db.add(new_assignment)
    db.commit()
    db.refresh(new_assignment)
    return {"message": "Success", "id": new_assignment.id}

@app.get("/assignments-with-submissions/{course_id}")
async def get_nested_assignments(course_id: int, db: Session = Depends(get_db)):
    assignments = db.query(AssignmentDB).filter(AssignmentDB.course_id == course_id).all()
    result = []
    for assign in assignments:
        subs = db.query(SubmissionDB).filter(SubmissionDB.assignment_id == assign.id).all()
        result.append({
            "id": assign.id,
            "assignment_name": assign.assignment_name,
            "model_answer": assign.model_answer,
            "rubric": assign.rubric,
            "is_model_answer": assign.is_model_answer,
            "submissions": [
                {
                    "id": s.id,
                    "student_name": s.student_name,
                    "status": s.status,
                    # ai_grade: original AI score, never overwritten
                    "ai_grade": s.ai_grade,
                    # manual_grade: professor's override — null means no override yet
                    "manual_grade": s.manual_grade,
                    # final_grade: what to display — professor's value if set, else AI
                    "final_grade": s.manual_grade if s.manual_grade is not None else s.ai_grade,
                    "grade_report": s.grade_report,
                } for s in subs
            ]
        })
    return result



@app.post("/grade-submission/{assignment_id}")
async def grade_student(
    assignment_id: int,
    file: UploadFile = File(...),
    # Fix 1: accept feedback_tone from the Flutter client.
    # Falls back to "formal" if the client does not send it.
    feedback_tone: Optional[str] = Form("formal"),
    db: Session = Depends(get_db)
):
    assign = db.query(AssignmentDB).filter(AssignmentDB.id == assignment_id).first()

    if not assign:
        raise HTTPException(status_code=404, detail="Assignment not found")

    # Validate tone value — only allow the three supported options
    valid_tones = {"formal", "encouraging", "strict"}
    if feedback_tone not in valid_tones:
        feedback_tone = "formal"

    # ------------------------
    # Save + extract student file
    # ------------------------
    content = await file.read()

    ext = file.filename.lower().split(".")[-1]
    temp_path = f"temp_{uuid.uuid4()}.{ext}"

    with open(temp_path, "wb") as f:
        f.write(content)

    student_text = ""

    # ✅ DOCX handling
    if ext == "docx":
        from docx import Document
        doc = Document(temp_path)
        student_text = "\n".join([p.text for p in doc.paragraphs])

    # ✅ PDF handling
    elif ext == "pdf":
        student_text = extract_text(temp_path)

    else:
        os.remove(temp_path)
        raise HTTPException(status_code=400, detail="Only PDF or DOCX files are allowed")

    os.remove(temp_path)

    # ------------------------
    # DEBUG INPUTS
    # ------------------------
    print("\n========== DEBUG START ==========")
    print("Student Answer:\n", student_text[:500])
    print("Feedback Tone:", feedback_tone)
    print("Assignment Question:\n", assign.assignment_question)
    print("Model Answer:\n", assign.model_answer if assign.is_model_answer else "None")
    print("Rubric:\n", assign.rubric if not assign.is_model_answer else "None")

    # ------------------------
    # BUILD REFERENCE BASED ON MODE
    # ------------------------
    if assign.is_model_answer:
        mode = "MODEL"
        reference = f"""
### MODE: MODEL_ANSWER
QUESTION:
{assign.assignment_question}

IDEAL ANSWER:
{assign.model_answer}
"""
    else:
        mode = "RUBRIC"
        reference = f"""
### MODE: RUBRIC
QUESTION:
{assign.assignment_question}

RUBRIC:
{assign.rubric}
"""

    print("MODE:", mode)
    print("FINAL REFERENCE SENT TO AI:\n", reference)

    # ------------------------
    # CALL AI  (Fix 1: pass the professor's chosen tone)
    # ------------------------
    ai_report = perform_nlp_grading(
        student_text=student_text,
        mode=mode,
        reference=reference,
        feedback_tone=feedback_tone,
    )

    print("AI RESPONSE:\n", ai_report)
    print("=========== DEBUG END ===========\n")

    # ------------------------
    # SAVE SUBMISSION
    # ------------------------
    new_sub = SubmissionDB(
        assignment_id=assignment_id,
        student_name=file.filename.split('.')[0],
        status="ready",
        ai_grade=ai_report.get('score_out_of_100', 0),
        grade_report=ai_report,
        essay_content=student_text,
    )

    db.add(new_sub)
    db.flush()   # get new_sub.id before the error-analysis insert below

    # ─────────────────────────────────────────────────────────────────
    # Fix 3: Populate ErrorAnalysisDB from the AI error_categories.
    #
    # The AI returns a dict like:
    #   {
    #     "conceptual":   "Student misunderstood X ...",
    #     "structural":   null,
    #     "language":     "Several run-on sentences ...",
    #     "completeness": null
    #   }
    #
    # We write one ErrorAnalysisDB row per non-null category so that
    # the analytics dashboard can query real error trends over time.
    # ─────────────────────────────────────────────────────────────────
    error_categories: dict = ai_report.get("error_categories", {}) or {}

    # Map AI category keys → human-readable category labels
    category_label_map = {
        "conceptual":   "Conceptual",
        "structural":   "Structural",
        "language":     "Language",
        "completeness": "Completeness",
    }

    # Try to resolve the student DB record for the FK.
    # The submission filename is used as student_name; if a matching
    # StudentDB row exists we link it, otherwise we skip the FK.
    student_name = file.filename.split('.')[0]
    student_record = (
        db.query(StudentDB)
        .filter(StudentDB.name == student_name,
                StudentDB.course_id == assign.course_id)
        .first()
    )

    for category_key, description in error_categories.items():
        # Skip null / empty entries — no error in that category
        if not description or str(description).strip().lower() in ("null", "none", ""):
            continue

        label = category_label_map.get(category_key, category_key.capitalize())

        error_row = ErrorAnalysisDB(
            student_id=student_record.id if student_record else None,
            course_id=assign.course_id,
            assignment_name=assign.assignment_name,
            error_category=label,
            # Store the AI's descriptive text as the specific error type
            error_type=str(description)[:500],   # cap at 500 chars
        )
        db.add(error_row)

    db.commit()

    return {
        "status": "success",
        "grade": ai_report.get("score_out_of_100", 0),
        "mode": mode,
        "feedback_tone": feedback_tone,
        "report": ai_report,
    }


@app.put("/update-submission-grade/{submission_id}")
async def update_grade(submission_id: int, data: dict, db: Session = Depends(get_db)):
    """
    Called when the professor finalises a grade in the review dialog.
    Writes the professor's value to manual_grade only — ai_grade is
    never touched so the original AI score is always preserved.
    """
    submission = db.query(SubmissionDB).filter(SubmissionDB.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    submission.manual_grade = int(data['final_grade'])
    submission.status = "graded"
    db.commit()
    return {"message": "Success"}

# /courses POST is handled by routes/courses.py router



# In main.py
from services.grading_service import perform_nlp_grading

@app.post("/analyze-general-submission")
async def analyze_general(data: dict):
    student_text = data.get("student_text")
    mode = data.get("mode")  # "MODEL" or "RUBRIC"
    reference = data.get("reference_content")
    feedback_tone = data.get("feedback_tone", "formal")  # optional

    if not all([student_text, mode, reference]):
        raise HTTPException(status_code=400, detail="Missing required fields")

    try:
        report = perform_nlp_grading(
            student_text=student_text,
            mode=mode,
            reference=reference,
            feedback_tone=feedback_tone
        )
        return report
    except Exception as e:
        print(f"AI Service Error: {e}")
        raise HTTPException(status_code=500, detail="AI grading failed")


# Add this to your main.py if it's not already there
@app.post("/extract-text")
async def api_extract_text(file: UploadFile = File(...)):
    # Create a temporary path to save the uploaded file
    temp_path = f"temp_{file.filename}"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # Use your existing utility to get the text
        text = extract_text(temp_path)
        return {"extracted_text": text}
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_path):
            os.remove(temp_path)