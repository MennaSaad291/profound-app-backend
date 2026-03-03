from pydantic import BaseModel, EmailStr
from typing import List, Optional

class UserCreate(BaseModel): full_name: str; email: EmailStr; password: str
class UserLogin(BaseModel): email: EmailStr; password: str
class UserUpdate(BaseModel): full_name: str; bio: str; department: str
class LectureRequest(BaseModel):
    topic: str; course_level: str; pages_count: int
    additional_instructions: str; include_media: bool; theme: str

class CourseResponse(BaseModel):
    id: int; code: str; name: str; semester: str; students: int; status: str
    schedule: Optional[str]; room: Optional[str]; progress: Optional[int]
    class Config: from_attributes = True