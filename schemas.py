from pydantic import BaseModel, EmailStr
from typing import List, Optional

# --- Auth Schemas ---
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

# --- Course Schemas ---
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

# --- AI & Lecture Schemas ---
class LectureRequest(BaseModel):
    topic: str
    course_level: str
    pages_count: int
    additional_instructions: str
    include_media: bool
    theme: str