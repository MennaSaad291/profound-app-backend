from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from schemas import AnalysisRequest, ReportConfiguration
from database import get_db
from services import analytics_service

router = APIRouter(prefix="/analysis", tags=["Analysis"])


#  PERFORMANCE
@router.get("/performance")
def performance(
    course_id: int = None,
    semester: str = None,
    days: int = None,
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db)
):
    return analytics_service.get_performance_distribution(
        db, course_id, semester, days, from_date, to_date
    )


#  CORRELATION
@router.get("/correlation")
def correlation(
    course_id: int = None,
    semester: str = None,
    days: int = None,
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db)
):
    return analytics_service.get_attendance_correlation_report(
        db, course_id, semester, days, from_date, to_date
    )


#  PREDICTION
@router.get("/prediction")
def prediction(
    course_id: int = None,
    semester: str = None,
    days: int = None,
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db)
):
    return analytics_service.get_prediction(
        db, course_id, semester, days, from_date, to_date
    )


#  ERRORS
@router.get("/errors")
def errors(
    course_id: int = None,
    semester: str = None,
    days: int = None,
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db)
):
    return analytics_service.common_error_analysis(
        db, course_id, semester, days, from_date, to_date
    )


#  BENCHMARKS
@router.get("/benchmarks")
def benchmarks(
    course_id: int = None,
    semester: str = None,
    days: int = None,
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db)
):
    return analytics_service.department_benchmarks(
        db, course_id, semester, days, from_date, to_date

    )

@router.post("/export")
def export_report(
    config: ReportConfiguration,
    course_id: int = None,
    semester: str = None,
    days: int = None,
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db)
):
    return analytics_service.export_report(
        db,
        config,
        course_id,
        semester,
        days,
        from_date,
        to_date
    )
@router.get("/courses")
def get_courses(db: Session = Depends(get_db)):
    return analytics_service.get_courses(db)
@router.post("/")
def full_analysis(data: AnalysisRequest, db: Session = Depends(get_db)):

    course_id = data.course_id
    semester = data.semester
    days = data.days
    from_date = data.from_date
    to_date = data.to_date

    return {
        "performanceDistribution": analytics_service.get_performance_distribution(
    db,
    course_id,
    semester,
    days,
    from_date,
    to_date
),
        "correlation": analytics_service.get_attendance_correlation_report(
    db,
    course_id,
    semester,
    days,
    from_date,
    to_date
),
        "prediction": analytics_service.get_prediction(
    db,
    course_id,
    semester,
    days,
    from_date,
    to_date
),
        "errorAnalysis": analytics_service.common_error_analysis(
    db,
    course_id,
    semester,
    days,
    from_date,
    to_date
),
    }
