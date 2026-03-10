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

<<<<<<< HEAD
# --- Change Password Schema ---
class ChangePasswordRequest(BaseModel):
    user_id: int
    current_password: str
    new_password: str

# --- Verify Password Schema ---
class VerifyPasswordRequest(BaseModel):
    user_id: int
    password: str

# --- Profile Metric Schemas ---
class PublicationCreate(BaseModel): 
=======
class PublicationCreate(BaseModel):
>>>>>>> origin/main
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

class ExamRequest(BaseModel):
    topic: str
    course_id: Optional[int] = None
    content_text: Optional[str] = None
    # ✅ Enforce exact count on backend
    number_of_questions: int = Field(default=5, ge=1, le=50)
    difficulty: str = "Medium"
    blooms_level: str = "Apply"
    question_type: str = "MCQ"

class LectureRequest(BaseModel):
    topic: str
    course_level: str
    pages_count: int
    additional_instructions: str
    include_media: bool
    theme: str

class Question(BaseModel):
    question_text: str
    options: Optional[List[str]] = None
    correct_answer: str
    explanation: str
    difficulty: str
    question_type: str = "MCQ"

class ExamResponse(BaseModel):
    exam_id: str
    questions: List[Question]