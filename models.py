from sqlalchemy import Column, Integer, String, ForeignKey, Text
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