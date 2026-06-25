from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional


class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    full_name: str
    bio: str
    department: str


class ChangePasswordRequest(BaseModel):
    user_id: int
    current_password: str
    new_password: str


class VerifyPasswordRequest(BaseModel):
    user_id: int
    password: str


class PublicationCreate(BaseModel):
    user_id: int
    title: str
    journal: str
    year: int
    citations: int = 0


class ProjectCreate(BaseModel):
    user_id: int
    title: str
    team: str
    year: str
    status: str


class InterestCreate(BaseModel):
    user_id: int
    name: str


class CourseCreate(BaseModel):
    user_id: int
    code: str
    name: str
    semester: str
    department: Optional[str] = None


class CourseResponse(BaseModel):
    id: int
    code: str
    name: str
    semester: str
    students: int
    status: str
    schedule: Optional[str]
    room: Optional[str]
    progress: Optional[int]

    class Config:
        from_attributes = True


class LectureRequest(BaseModel):
    topic: str
    pages_count: int = Field(default=10, ge=3, le=70)
    additional_instructions: str = ""
    theme: str = "Modern Minimalist"


class ExamRequest(BaseModel):
    topic: str
    course_id: Optional[int] = None
    content_text: Optional[str] = None
    number_of_questions: int = Field(default=5, ge=1, le=50)
    difficulty: str = "Medium"
    blooms_level: str = "Apply"
    question_type: str = "MCQ"
    existing_exam_id: Optional[str] = None   # append questions to this exam instead of creating new


class Question(BaseModel):
    question_text: str
    options: Optional[List[str]] = None
    correct_answer: Optional[str] = None
    explanation: str
    difficulty: str
    question_type: str = "MCQ"


class ExamResponse(BaseModel):
    exam_id: str
    questions: List[Question]


class AssignmentCreate(BaseModel):
    assignment_name: str
    course_id: int
    is_model_answer: bool
    assignment_question: Optional[str] = None
    assignment_file_path: Optional[str] = None
    model_answer: Optional[str] = None
    rubric: Optional[str] = None


class ReportConfiguration(BaseModel):
    include_pii: bool = True
    include_benchmarks: bool = True
    error_analysis_detail: bool = True
    predictive_analytics: bool = True
    attendance_data: bool = True
    grade_distribution: bool = True
    export_format: str = "pdf"


class AnalysisRequest(BaseModel):
    course_id: Optional[int] = None
    semester: Optional[str] = None
    days: Optional[int] = None
    from_date: Optional[str] = None
    to_date: Optional[str] = None
