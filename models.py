import datetime
from pydantic import BaseModel
from sqlalchemy import Column, String, Integer, Text, ForeignKey, Boolean, DateTime, TIMESTAMP, JSON, Float, func
from database import Base


class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    bio = Column(Text, default="Professor of Computer Science specialized in AI.")
    department = Column(String, default="Information Systems Dept.")


class CourseDB(Base):
    __tablename__ = "courses"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    code = Column(String)
    name = Column(String)
    semester = Column(String)
    students = Column(Integer, default=0)
    status = Column(String, default="active")
    schedule = Column(String, default="TBA")
    room = Column(String, default="TBA")
    progress = Column(Integer, default=0)
    department = Column(String(100), nullable=True)


class StudentDB(Base):
    __tablename__ = "students"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(String)
    name = Column(String)
    department = Column(String)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"))


class PublicationDB(Base):
    __tablename__ = "publications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String)
    journal = Column(String)
    year = Column(Integer)
    citations = Column(Integer, default=0)


class ProjectDB(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String)
    team = Column(String)
    year = Column(String)
    status = Column(String)
    deadline = Column(String, nullable=True)   # e.g. "2026-06-30"
    progress = Column(Integer, default=0)      # 0–100


class LiteraturePaperDB(Base):
    __tablename__ = "literature_papers"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String)
    read_status = Column(String, default="to-read")  # to-read | reading | read
    citation_format = Column(String, default="APA")  # APA | IEEE | MLA


class GraduationProjectDB(Base):
    __tablename__ = "graduation_projects"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String)
    team = Column(String)
    academic_year = Column(String)
    department = Column(String)
    document_path = Column(String, nullable=True)


class InterestDB(Base):
    __tablename__ = "interests"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String)


class ExamDB(Base):
    __tablename__ = "exams"
    id = Column(String(50), primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255))
    created_at = Column(TIMESTAMP, default=datetime.datetime.utcnow)
    is_variation = Column(Boolean, default=False)


class QuestionDB(Base):
    __tablename__ = "questions"
    id = Column(String(50), primary_key=True)
    exam_id = Column(String(50), ForeignKey("exams.id", ondelete="CASCADE"))
    question_text = Column(Text)
    question_type = Column(String(50))
    options = Column(JSON, nullable=True)
    blooms_level = Column(String(50))
    difficulty = Column(String(20))
    correct_answer = Column(Text)
    explanation = Column(Text)


class SubmissionDB(Base):
    __tablename__ = "submissions"
    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"))
    student_name = Column(String)
    submission_time = Column(DateTime, default=datetime.datetime.utcnow)
    question_type = Column(String, default="Essay")
    status = Column(String, default="pending")
    ai_grade = Column(Integer, nullable=True)
    manual_grade = Column(Integer, nullable=True)
    plagiarism_score = Column(Integer, nullable=True)
    essay_content = Column(Text, nullable=True)
    grade_report = Column(JSON, nullable=True)


class PerformanceDB(Base):
    __tablename__ = "performance"
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"))
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"))
    grade = Column(Float)
    attendance = Column(Integer)
    created_at = Column(DateTime, default=func.now())


class ErrorAnalysisDB(Base):
    __tablename__ = "error_analysis"
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=True)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"))
    assignment_name = Column(String)
    error_category = Column(String)
    error_type = Column(String)
    created_at = Column(DateTime, default=func.now())


class AssignmentDB(Base):
    __tablename__ = "assignments"
    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"))
    assignment_name = Column(String(100))
    assignment_question = Column(Text, nullable=True)
    assignment_file_path = Column(Text, nullable=True)
    model_answer = Column(Text, nullable=True)
    rubric = Column(Text, nullable=True)
    is_model_answer = Column(Boolean, default=False)


class LectureSlotDB(Base):
    __tablename__ = "lecture_slots"
    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"))
    day = Column(String(20))
    start_time = Column(String(10))
    end_time = Column(String(10))
    room = Column(String(100))


# Pydantic request bodies used directly in main.py
class GradeUpdate(BaseModel):
    ai_grade: int
    status: str


class FinalizeRequest(BaseModel):
    manual_grade: int
