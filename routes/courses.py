import io
import asyncio
import pandas as pd
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import (
    CourseDB, StudentDB, PerformanceDB, ErrorAnalysisDB,
    LectureSlotDB, PublicationDB, ProjectDB, InterestDB, UserDB
)
from schemas import PublicationCreate, ProjectCreate, InterestCreate, UserUpdate

router = APIRouter(tags=["courses"])


# ── Local schemas ─────────────────────────────────────────────────────────────

class CourseCreate(BaseModel):
    user_id: int
    code: str
    name: str
    semester: str
    status: str = "active"
    schedule: str = "TBA"
    room: str = "TBA"
    department: Optional[str] = None


class CourseUpdate(BaseModel):
    code: str
    name: str
    semester: str
    status: str = "active"
    schedule: str = "TBA"
    room: str = "TBA"
    department: Optional[str] = None


class StudentCreate(BaseModel):
    student_id: str
    name: str
    department: Optional[str] = ""
    course_id: int


class LectureSlotCreate(BaseModel):
    day: str
    start_time: str
    end_time: str
    room: str


# ── Course CRUD ───────────────────────────────────────────────────────────────

@router.post("/courses")
def create_course(data: CourseCreate, db: Session = Depends(get_db)):
    course = CourseDB(**data.dict())
    db.add(course)
    db.commit()
    db.refresh(course)
    return {"message": "Course created", "id": course.id}


@router.put("/courses/{course_id}")
def update_course(course_id: int, data: CourseUpdate, db: Session = Depends(get_db)):
    course = db.query(CourseDB).filter(CourseDB.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    for field, value in data.dict().items():
        setattr(course, field, value)
    db.commit()
    return {"message": "Course updated"}


@router.delete("/courses/{course_id}")
def delete_course(course_id: int, db: Session = Depends(get_db)):
    course = db.query(CourseDB).filter(CourseDB.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    db.query(PerformanceDB).filter(PerformanceDB.course_id == course_id).delete(synchronize_session=False)
    db.query(ErrorAnalysisDB).filter(ErrorAnalysisDB.course_id == course_id).delete(synchronize_session=False)
    db.query(StudentDB).filter(StudentDB.course_id == course_id).delete(synchronize_session=False)
    db.query(LectureSlotDB).filter(LectureSlotDB.course_id == course_id).delete(synchronize_session=False)
    db.delete(course)
    db.commit()
    return {"message": "Course deleted"}


# ── Students ──────────────────────────────────────────────────────────────────

@router.get("/courses/{course_id}/students")
def get_students(course_id: int, db: Session = Depends(get_db)):
    students = db.query(StudentDB).filter(StudentDB.course_id == course_id).all()
    return [{"id": s.id, "student_id": s.student_id, "name": s.name, "department": s.department}
            for s in students]


@router.post("/courses/{course_id}/students")
def add_student(course_id: int, data: StudentCreate, db: Session = Depends(get_db)):
    course = db.query(CourseDB).filter(CourseDB.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if db.query(StudentDB).filter(StudentDB.student_id == data.student_id, StudentDB.course_id == course_id).first():
        raise HTTPException(status_code=400, detail="Student already enrolled in this course")
    student = StudentDB(student_id=data.student_id, name=data.name,
                        department=data.department or "", course_id=course_id)
    db.add(student)
    db.flush()  # make new row visible to COUNT
    course.students = db.query(func.count(StudentDB.id)).filter(StudentDB.course_id == course_id).scalar()
    db.commit()
    db.refresh(student)
    return {"message": "Student added", "id": student.id}


@router.delete("/courses/{course_id}/students/{student_id}")
def delete_student(course_id: int, student_id: int, db: Session = Depends(get_db)):
    student = db.query(StudentDB).filter(StudentDB.id == student_id, StudentDB.course_id == course_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    db.delete(student)
    db.flush()  # ensure delete is visible to COUNT
    course = db.query(CourseDB).filter(CourseDB.id == course_id).first()
    if course:
        course.students = db.query(func.count(StudentDB.id)).filter(StudentDB.course_id == course_id).scalar()
    db.commit()
    return {"message": "Student removed"}


def _parse_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    """Parse CSV or Excel bytes into a DataFrame (runs in a thread executor).

    Handles messy Excel files where:
    - The header row is not on the first row (blank/title rows above it)
    - The data columns start at a non-zero column offset
    - There are multiple sheets (picks the first one with student_id/name columns)
    """
    if filename.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(content))
        return _normalise_df(df)

    # Try every sheet, return the first one that contains the required columns
    xl = pd.ExcelFile(io.BytesIO(content), engine='openpyxl')
    for sheet in xl.sheet_names:
        raw = xl.parse(sheet, header=None)
        df = _find_header_and_trim(raw)
        if df is not None:
            return df

    # Fallback: return the first sheet as-is so the caller can report the error
    return xl.parse(xl.sheet_names[0])


def _find_header_and_trim(raw: "pd.DataFrame") -> "pd.DataFrame | None":
    """Scan rows and columns of a header-less DataFrame to find the real header row.

    Returns a properly-headed DataFrame, or None if no matching row is found.
    """
    required = {"student_id", "name"}
    for row_idx in range(min(20, len(raw))):          # scan first 20 rows
        for col_offset in range(min(5, raw.shape[1])): # scan first 5 columns
            row_vals = raw.iloc[row_idx, col_offset:].astype(str).str.strip().str.lower()
            if required.issubset(set(row_vals)):
                # Found the header row — rebuild DataFrame from here
                df = raw.iloc[row_idx + 1:, col_offset:].copy()
                df.columns = row_vals.values
                df = df.reset_index(drop=True)
                return _normalise_df(df)
    return None


def _normalise_df(df: "pd.DataFrame") -> "pd.DataFrame":
    """Strip whitespace from column names and drop fully-empty rows."""
    df.columns = [str(c).strip().lower() for c in df.columns]
    df = df.dropna(how='all')
    return df


@router.post("/courses/{course_id}/upload-students")
async def upload_students_excel(course_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    course = db.query(CourseDB).filter(CourseDB.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return await _do_upload_students(course, file, db)


@router.post("/courses/by-code/{course_code}/upload-students")
async def upload_students_by_code(course_code: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Same as upload-students but identified by course code (e.g. CS402) instead of numeric id."""
    course = db.query(CourseDB).filter(
        func.upper(CourseDB.code) == course_code.strip().upper()
    ).first()
    if not course:
        raise HTTPException(status_code=404, detail=f"Course with code '{course_code}' not found")
    return await _do_upload_students(course, file, db)


async def _do_upload_students(course: CourseDB, file: UploadFile, db: Session):
    """Shared logic for both upload-students endpoints."""

    content = await file.read()

    # Offload the blocking pandas parse to a thread so the event loop stays free
    loop = asyncio.get_event_loop()
    try:
        df = await loop.run_in_executor(None, _parse_dataframe, content, file.filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")

    df.columns = list(df.columns)  # already normalised by _parse_dataframe
    missing = {"student_id", "name"} - set(df.columns)
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing columns: {missing}")

    existing_ids = {r[0] for r in db.query(StudentDB.student_id).filter(StudentDB.course_id == course.id).all()}
    to_add, skipped = [], 0
    has_dept = "department" in df.columns

    for _, row in df.iterrows():
        # student_id may be read as a float (e.g. 20210001.0) — normalise to str
        raw_sid = row["student_id"]
        sid = str(int(float(raw_sid))).strip() if str(raw_sid).replace('.', '', 1).isdigit() else str(raw_sid).strip()
        if not sid or sid.lower() in ('nan', ''):
            continue
        if sid in existing_ids:
            skipped += 1
            continue
        dept = str(row.get("department", "")).strip() if has_dept else ""
        to_add.append(StudentDB(student_id=sid, name=str(row["name"]).strip(),
                                department=dept, course_id=course.id))
        existing_ids.add(sid)

    if to_add:
        db.bulk_save_objects(to_add)
        db.flush()  # ensure new rows are visible to the COUNT query below
    course.students = db.query(func.count(StudentDB.id)).filter(StudentDB.course_id == course.id).scalar()
    db.commit()
    return {"message": f"Added {len(to_add)} student(s). Skipped {skipped} duplicate(s)."}


# ── Analytics ─────────────────────────────────────────────────────────────────

@router.get("/course-analytics/{course_id}")
def get_course_analytics(course_id: int, db: Session = Depends(get_db)):
    performances = db.query(PerformanceDB).filter(PerformanceDB.course_id == course_id).all()
    if not performances:
        return {"average": "N/A", "at_risk": 0, "trend": [0, 0, 0, 0, 0],
                "distribution": {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}}

    grades = [p.grade for p in performances]
    avg = round(sum(grades) / len(grades), 1)
    dist = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    for g in grades:
        if g >= 90: dist["A"] += 1
        elif g >= 80: dist["B"] += 1
        elif g >= 70: dist["C"] += 1
        elif g >= 60: dist["D"] += 1
        else: dist["F"] += 1

    chunk = max(1, len(grades) // 5)
    trend = [round(sum(grades[i*chunk:(i+1)*chunk]) / len(grades[i*chunk:(i+1)*chunk]), 1)
             if grades[i*chunk:(i+1)*chunk] else avg for i in range(5)]

    return {"average": f"{avg}%", "at_risk": sum(1 for g in grades if g < 60),
            "trend": trend, "distribution": dist}


# ── Profile helpers ───────────────────────────────────────────────────────────

@router.post("/courses-with-students")
async def create_course_with_students(
    user_id: int = Form(...), code: str = Form(...), name: str = Form(...),
    semester: str = Form(...), schedule: str = Form("TBA"), room: str = Form("TBA"),
    department: Optional[str] = Form(None), status: str = Form("active"),
    file: UploadFile = File(...), db: Session = Depends(get_db),
):
    course = CourseDB(user_id=user_id, code=code, name=name, semester=semester,
                      schedule=schedule, room=room, department=department, status=status)
    db.add(course)
    db.flush()

    content = await file.read()

    # Offload the blocking pandas parse to a thread so the event loop stays free
    loop = asyncio.get_event_loop()
    try:
        df = await loop.run_in_executor(None, _parse_dataframe, content, file.filename)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")

    df.columns = list(df.columns)  # already normalised by _parse_dataframe
    if not {"student_id", "name"}.issubset(df.columns):
        db.rollback()
        raise HTTPException(status_code=400, detail="File must contain 'student_id' and 'name' columns.")

    has_dept_cws = "department" in df.columns
    to_add_cws = []
    for _, row in df.iterrows():
        raw_sid = row["student_id"]
        sid = str(int(float(raw_sid))).strip() if str(raw_sid).replace('.', '', 1).isdigit() else str(raw_sid).strip()
        if not sid or sid.lower() in ('nan', ''):
            continue
        dept = str(row.get("department", "")).strip() if has_dept_cws else ""
        to_add_cws.append(StudentDB(student_id=sid, name=str(row["name"]).strip(),
                                department=dept, course_id=course.id))

    if to_add_cws:
        db.bulk_save_objects(to_add_cws)
    course.students = len(to_add_cws)
    db.commit()
    return {"message": f"Course created with {len(to_add_cws)} students.", "course_id": course.id}


@router.post("/publications")
def add_publication(data: PublicationCreate, db: Session = Depends(get_db)):
    db.add(PublicationDB(**data.dict()))
    db.commit()
    return {"message": "Publication added"}


@router.post("/projects")
def add_project(data: ProjectCreate, db: Session = Depends(get_db)):
    db.add(ProjectDB(**data.dict()))
    db.commit()
    return {"message": "Project added"}


@router.post("/interests")
def add_interest(data: InterestCreate, db: Session = Depends(get_db)):
    db.add(InterestDB(**data.dict()))
    db.commit()
    return {"message": "Interest added"}


@router.delete("/interests/{user_id}/{name}")
def delete_interest(user_id: int, name: str, db: Session = Depends(get_db)):
    interest = db.query(InterestDB).filter(
        InterestDB.user_id == user_id, InterestDB.name == name
    ).first()
    if not interest:
        raise HTTPException(status_code=404, detail="Interest not found")
    db.delete(interest)
    db.commit()
    return {"message": "Interest deleted"}


@router.put("/profile/update/{user_id}")
def update_profile_alias(user_id: int, data: UserUpdate, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.full_name = data.full_name
    user.bio = data.bio
    user.department = data.department
    db.commit()
    return {"message": "Profile updated successfully"}


# ── Lecture Schedule ──────────────────────────────────────────────────────────

@router.get("/courses/{course_id}/schedule")
def get_schedule(course_id: int, db: Session = Depends(get_db)):
    slots = db.query(LectureSlotDB).filter(LectureSlotDB.course_id == course_id).all()
    return [{"id": s.id, "day": s.day, "start_time": s.start_time, "end_time": s.end_time, "room": s.room}
            for s in slots]


@router.post("/courses/{course_id}/schedule")
def add_slot(course_id: int, data: LectureSlotCreate, db: Session = Depends(get_db)):
    if not db.query(CourseDB).filter(CourseDB.id == course_id).first():
        raise HTTPException(status_code=404, detail="Course not found")
    slot = LectureSlotDB(course_id=course_id, **data.dict())
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return {"message": "Slot added", "id": slot.id}


@router.put("/courses/{course_id}/schedule/{slot_id}")
def update_slot(course_id: int, slot_id: int, data: LectureSlotCreate, db: Session = Depends(get_db)):
    slot = db.query(LectureSlotDB).filter(LectureSlotDB.id == slot_id, LectureSlotDB.course_id == course_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    for field, value in data.dict().items():
        setattr(slot, field, value)
    db.commit()
    return {"message": "Slot updated"}


@router.delete("/courses/{course_id}/schedule/{slot_id}")
def delete_slot(course_id: int, slot_id: int, db: Session = Depends(get_db)):
    slot = db.query(LectureSlotDB).filter(LectureSlotDB.id == slot_id, LectureSlotDB.course_id == course_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    db.delete(slot)
    db.commit()
    return {"message": "Slot deleted"}
