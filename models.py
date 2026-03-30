from database import Base
from sqlalchemy import Column, String, Integer, Text, ForeignKey, Boolean, DateTime, TIMESTAMP, JSON ,Float ,func
import datetime
from pydantic import BaseModel

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
    title = Column(String); journal = Column(String); year = Column(Integer); citations = Column(Integer, default=0)

class ProjectDB(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String); team = Column(String); year = Column(String); status = Column(String)

class InterestDB(Base):
    __tablename__ = "interests"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String)
    
class ExamDB(Base):
    __tablename__ = "exams"
    id = Column(String(50), primary_key=True)
    # nullable=True allows exams to be generated without being linked to a specific course
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255))
    created_at = Column(TIMESTAMP, default=datetime.datetime.utcnow)
    is_variation = Column(Boolean, default=False)

class QuestionDB(Base):
    __tablename__ = "questions"
    id = Column(String(50), primary_key=True)
    exam_id = Column(String(50), ForeignKey("exams.id", ondelete="CASCADE"))
    question_text = Column(Text)
    question_type = Column(String(50)) # e.g., 'MCQ' or 'Essay'
    options = Column(JSON, nullable=True) # Essential for MCQ storage
    blooms_level = Column(String(50)) # Pedagogical alignment
    difficulty = Column(String(20))
    correct_answer = Column(Text)
    explanation = Column(Text)

#class SubmissionDB(Base):
#    __tablename__ = "submissions"
#    id = Column(Integer, primary_key=True, index=True)
#    student_name = Column(String)
#    submission_time = Column(String)
#    status = Column(String, default="pending") # 'pending', 'ready', 'graded'
#    ai_grade = Column(Integer, nullable=True)
#    plagiarism_score = Column(Integer, nullable=True)
#    essay_content = Column(Text, nullable=True)

# In models.py, update SubmissionDB


# models.py
class SubmissionDB(Base):
    __tablename__ = "submissions"
    id = Column(Integer, primary_key=True, index=True)
    student_name = Column(String)
    submission_time = Column(String)
    # This matches your UI's 'pending' | 'ready' | 'graded' statuses
    status = Column(String, default="pending")
    ai_grade = Column(Integer, nullable=True)
    plagiarism_score = Column(Integer, nullable=True) # Used for the UI color logic
    essay_content = Column(Text, nullable=True)
    grade_report = Column(JSON, nullable=True)

class PerformanceDB(Base):
    __tablename__ = "performance"
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id"))
    course_id = Column(Integer, ForeignKey("courses.id"))
    grade = Column(Float)
    attendance = Column(Integer)
    created_at = Column(DateTime, default=func.now())

class ErrorAnalysisDB(Base):
    __tablename__ = "error_analysis"
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id"))
    course_id = Column(Integer, ForeignKey("courses.id"))
    assignment_name = Column(String)
    error_category = Column(String)
    error_type = Column(String)  
    
class AssignmentDB(Base):
    __tablename__ = "assignments"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"))
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"))
    assignment_name = Column(String(100))
    rubric_text = Column(Text, nullable=True)
    is_submitted = Column(Boolean, default=False)

class GradeUpdate(BaseModel):
    ai_grade: int
    status: str
class FinalizeRequest(BaseModel):
    manual_grade: int