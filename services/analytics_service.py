from models import PerformanceDB, CourseDB, ErrorAnalysisDB, AssignmentDB, StudentDB

import io, math, tempfile
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures
from scipy.interpolate import make_interp_spline

from sqlalchemy import func, case
from fastapi.responses import StreamingResponse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from models import SubmissionDB, AssignmentDB
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
)

from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.enums import TA_LEFT

def get_courses(db):
    courses = db.query(CourseDB).all()

    return [
        {
            "id": c.id,
            "code": c.code,
            "name": c.name,
            "display": f"{c.code} - {c.name}"
        }
        for c in courses
    ]
def apply_filters(
    query,
    model,
    course_id=None,
    semester=None,
    days=None,
    from_date=None,
    to_date=None,
    join_course=False
):

    if join_course or semester:
        query = query.join(
            CourseDB,
            CourseDB.id == model.course_id
        )

    if course_id:
        query = query.filter(model.course_id == course_id)

    if semester and semester.strip() and semester != "All Semesters":
        query = query.filter(CourseDB.semester == semester.strip())

    if days and hasattr(model, "created_at"):
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = query.filter(model.created_at >= cutoff)

    if from_date and to_date and hasattr(model, "created_at"):
        query = query.filter(model.created_at.between(from_date, to_date))

    return query
#  PERFORMANCE DISTRIBUTION 

def get_performance_distribution(db, course_id=None, semester=None, days=None, from_date=None, to_date=None):

    query = db.query(PerformanceDB.grade, PerformanceDB.course_id)

    query = apply_filters(
        query,
        PerformanceDB,
        course_id,
        semester,
        days,
        from_date,
        to_date,
        join_course=True
    )

    grades = [g[0] for g in query.all()]

    dist = {
        "Excellent (90-100)": 0,
        "Good (80-89)": 0,
        "Average (70-79)": 0,
        "At-Risk (<70)": 0
    }

    for g in grades:
        if g >= 90:
            dist["Excellent (90-100)"] += 1
        elif g >= 80:
            dist["Good (80-89)"] += 1
        elif g >= 70:
            dist["Average (70-79)"] += 1
        else:
            dist["At-Risk (<70)"] += 1

    return dist
# Attendance_Correlation
def get_attendance_correlation_report(
    db,
    course_id=None,
    semester=None,
    days=None,
    from_date=None,
    to_date=None
):

    query = db.query(PerformanceDB.attendance, PerformanceDB.grade)

    query = apply_filters(
        query,
        PerformanceDB,
        course_id,
        semester,
        days,
        from_date,
        to_date,
        join_course=True
    )

    data = query.all()

    if len(data) < 2:
        return {
            "stats": {
                "r_squared": 0,
                "label": "N/A"
            },
            "insight": "No data",
            "points": []
        }

    x = np.array([d.attendance for d in data]).reshape(-1, 1)
    y = np.array([d.grade for d in data])

    model = LinearRegression()
    model.fit(x, y)

    r_sq = model.score(x, y)
    slope = model.coef_[0]

    base_impact = slope * 10

    noise_factor = (1 - r_sq)

    lower = base_impact * (1 - noise_factor)
    upper = base_impact * (1 + noise_factor)

    lower = max(0, round(lower, 1))
    upper = round(upper, 1)

    insight_range = f"≈ {lower}–{upper}%"

    return {
        "stats": {
            "r_squared": round(r_sq, 2),
            "label": f"R² = {round(r_sq, 2)} ({'Strong' if r_sq > 0.7 else 'Moderate' if r_sq > 0.4 else 'Weak'})"
        },
        "insight": f"Each 10% attendance ↑ {insight_range} grade ↑",
        "points": [
            {
                "attendance": float(d.attendance),
                "grade": float(d.grade)
            }
            for d in data
        ]
    }
# prediction 
def get_prediction(
    db,
    course_id=None,
    semester=None,
    days=None,
    from_date=None,
    to_date=None
):

    query = db.query(
        func.date_trunc('week', PerformanceDB.created_at).label('week_start'),
        func.avg(PerformanceDB.grade).label('avg_grade'),
        func.sum(
            case((PerformanceDB.grade < 70, 1), else_=0)
        ).label("at_risk_count")
    )

    query = apply_filters(
        query,
        PerformanceDB,
        course_id,
        semester,
        days,
        from_date,
        to_date,
        join_course=True
    )

    weekly_data = query.group_by("week_start").order_by("week_start").all()

    if len(weekly_data) < 3:
        return {"chart": [], "message": "Need at least 3 weeks"}

    X = np.arange(len(weekly_data))
    y = np.array([float(w.avg_grade) for w in weekly_data])

    if len(weekly_data) >= 8:
        degree = 3
    elif len(weekly_data) >= 5:
        degree = 2
    else:
        degree = 1

    poly = PolynomialFeatures(degree=degree)
    X_poly = poly.fit_transform(X.reshape(-1, 1))

    model = LinearRegression()
    model.fit(X_poly, y)

    future_weeks = 3
    total = len(weekly_data) + future_weeks

    X_all = np.arange(total)
    X_all_poly = poly.transform(X_all.reshape(-1, 1))

    preds = model.predict(X_all_poly)

    chart = []

    for i, w in enumerate(weekly_data):
        chart.append({
            "label": f"Week {i+1}",
            "actual": round(float(w.avg_grade), 1),
            "predicted": round(float(preds[i]), 1),
            "at_risk_students": int(w.at_risk_count)
        })

    for i in range(len(weekly_data), total):
        chart.append({
            "label": f"Week {i+1}",
            "actual": None,
            "predicted": round(float(preds[i]), 1),
            "at_risk_students": None
        })

    last_pred = round(preds[-1], 1)

    last_risk = next(
        (c["at_risk_students"] for c in reversed(chart) if c["at_risk_students"] is not None),
        0
    )

    insight = f"""
    Class expected to reach {last_pred}% by Week {total}.
    {last_risk} students are at risk → intervention recommended.
    """

    return {
        "chart": chart,

        "insight": insight.strip(),

        "meta": {
            "final_prediction": float(round(preds[-1], 1)),
            "weeks": total,
            "at_risk_students": int(last_risk)
        }
    }
### common_error_analysis
def common_error_analysis(db, course_id=None, semester=None, days=None, from_date=None, to_date=None):
    """
    Returns one entry per error category (Conceptual, Structural, Language,
    Completeness) with:
      - total_errors   : how many submissions had at least one error in this category
      - percentage     : share of that category out of all error rows
      - affected_students : distinct students who had this category of error
      - notes          : list of the AI-generated descriptions (one per submission)
                         so the professor can read actual error details

    The old approach tried to GROUP BY error_type (raw AI text) which produced
    occurrences=1 / affected_students=1 for every row because every AI description
    is unique text.  We no longer aggregate by description — descriptions are
    shown as individual notes instead.
    """

    # ── base filtered query ───────────────────────────────────────────────
    base_q = db.query(ErrorAnalysisDB)
    base_q = apply_filters(
        base_q, ErrorAnalysisDB,
        course_id, semester, days, from_date, to_date,
        join_course=True
    )

    total_errors = base_q.count()
    if total_errors == 0:
        return []

    # ── Step 1: count rows per category ──────────────────────────────────
    cat_q = db.query(
        ErrorAnalysisDB.error_category,
        func.count(ErrorAnalysisDB.id).label("count"),
        func.count(func.distinct(ErrorAnalysisDB.student_id)).label("students"),
    )
    cat_q = apply_filters(
        cat_q, ErrorAnalysisDB,
        course_id, semester, days, from_date, to_date,
        join_course=True
    )
    categories = (
        cat_q
        .group_by(ErrorAnalysisDB.error_category)
        .order_by(func.count(ErrorAnalysisDB.id).desc())   # highest-frequency first
        .all()
    )

    # ── Step 2: fetch all individual descriptions per category ───────────
    #   We order by newest first so the professor sees recent errors at the top.
    rows_q = db.query(
        ErrorAnalysisDB.error_category,
        ErrorAnalysisDB.error_type,
        ErrorAnalysisDB.assignment_name,
        ErrorAnalysisDB.created_at,
    )
    rows_q = apply_filters(
        rows_q, ErrorAnalysisDB,
        course_id, semester, days, from_date, to_date,
        join_course=True
    )
    all_rows = rows_q.order_by(ErrorAnalysisDB.created_at.desc()).all()

    # Group descriptions by category into a dict for O(1) lookup
    notes_by_category: dict[str, list[dict]] = {}
    for row in all_rows:
        notes_by_category.setdefault(row.error_category, []).append({
            "description": row.error_type,
            "assignment":  row.assignment_name,
        })

    # ── Step 3: build result ──────────────────────────────────────────────
    result = []
    for cat in categories:
        result.append({
            "category":          cat.error_category,
            "total_errors":      cat.count,
            "percentage":        round((cat.count / total_errors) * 100, 2),
            "affected_students": cat.students,
            # individual AI descriptions — shown as readable notes, not aggregated
            "notes":             notes_by_category.get(cat.error_category, []),
        })

    return result

def get_student_insights(db, course_id, semester=None, days=None, from_date=None, to_date=None):

    query = db.query(
        StudentDB.student_id,
        StudentDB.name,
        StudentDB.department
    )

    query = apply_filters(
        query,
        StudentDB,
        course_id,
        semester,
        days,
        from_date,
        to_date,
        join_course=False
    )

    students = query.all()

    if not students:
        return {"students": []}

    return {
        "students": [
            {
                "id": s.student_id,
                "name": s.name,
                "department": s.department
            }
            for s in students
        ]
    }
def department_benchmarks(
    db,
    course_id,
    semester=None,
    days=None,
    from_date=None,
    to_date=None
):

    course = db.query(CourseDB).filter(CourseDB.id == course_id).first()

    if not course:
        return []

    department = course.department

    perf_course = db.query(PerformanceDB).filter(
        PerformanceDB.course_id == course_id
    )

    perf_course = apply_filters(
        perf_course,
        PerformanceDB,
        course_id,
        semester,
        days,
        from_date,
        to_date,
        join_course=True
    )

    total = perf_course.count()

    your_avg_grade = perf_course.with_entities(func.avg(PerformanceDB.grade)).scalar() or 0
    your_attendance = perf_course.with_entities(func.avg(PerformanceDB.attendance)).scalar() or 0

    if total == 0:
        your_pass_rate = 0
    else:
        passed = perf_course.filter(PerformanceDB.grade >= 50).count()
        your_pass_rate = (passed * 100.0) / total

    #  DEPARTMENT METRICS

    perf_dept = db.query(PerformanceDB)

    perf_dept = apply_filters(
        perf_dept,
        PerformanceDB,
        None,
        semester,
        days,
        from_date,
        to_date,
        join_course=True
    )

    perf_dept = perf_dept.filter(CourseDB.department == department)
    
    total_dept = perf_dept.count()

    dept_avg_grade = perf_dept.with_entities(func.avg(PerformanceDB.grade)).scalar() or 0
    dept_attendance = perf_dept.with_entities(func.avg(PerformanceDB.attendance)).scalar() or 0

    if total_dept == 0:
        dept_pass_rate = 0
    else:
        passed_dept = perf_dept.filter(PerformanceDB.grade >= 50).count()
        dept_pass_rate = (passed_dept * 100.0) / total_dept

    assign_course = db.query(AssignmentDB).filter(
        AssignmentDB.course_id == course_id
    )

    total_assign = assign_course.count()

    if total_assign == 0:
        your_assignment_completion = 0
    else:
        submitted = (
            db.query(SubmissionDB.assignment_id)
            .join(AssignmentDB, SubmissionDB.assignment_id == AssignmentDB.id)
            .filter(AssignmentDB.course_id == course_id)
            .distinct()
            .count()
        )

    your_assignment_completion = (submitted * 100.0) / total_assign

    assign_dept = db.query(AssignmentDB).join(CourseDB)

    assign_dept = assign_dept.filter(CourseDB.department == department)

    total_assign_dept = assign_dept.count()

    if total_assign_dept == 0:
        dept_assignment_completion = 0
    else:
        submitted_dept = (
            db.query(SubmissionDB.assignment_id)
            .join(AssignmentDB, SubmissionDB.assignment_id == AssignmentDB.id)
            .join(CourseDB, AssignmentDB.course_id == CourseDB.id)
            .filter(CourseDB.department == department)
            .distinct()
            .count()
        )

        dept_assignment_completion = (submitted_dept * 100.0) / total_assign_dept
    benchmarks_list = [
            {
                "metric": "Average Grade",
                "yourCourse": round(your_avg_grade, 1),
                "department": round(dept_avg_grade, 1),
                "difference": f"{'+' if your_avg_grade >= dept_avg_grade else ''}{round(your_avg_grade - dept_avg_grade, 1)}"
            },
            {
                "metric": "Pass Rate",
                "yourCourse": round(your_pass_rate, 1),
                "department": round(dept_pass_rate, 1),
                "difference": f"{'+' if your_pass_rate >= dept_pass_rate else ''}{round(your_pass_rate - dept_pass_rate, 1)}%"
            },
            {
                "metric": "Attendance Rate",
                "yourCourse": round(your_attendance, 1),
                "department": round(dept_attendance, 1),
                "difference": f"{'+' if your_attendance >= dept_attendance else ''}{round(your_attendance - dept_attendance, 1)}%"
            },
            {
                "metric": "Assignment Completion",
                "yourCourse": round(your_assignment_completion, 1),
                "department": round(dept_assignment_completion, 1),
                "difference": f"{'+' if your_assignment_completion >= dept_assignment_completion else ''}{round(your_assignment_completion - dept_assignment_completion, 1)}%"
            }
            
        ]
    return benchmarks_list

def create_grade_chart(perf_data):

    labels = list(perf_data.keys())
    values = list(perf_data.values())

    cleaned_values = []
    cleaned_labels = []

    for l, v in zip(labels, values):

        if v is None or (isinstance(v, float) and math.isnan(v)):
            v = 0

        cleaned_values.append(v)
        cleaned_labels.append(l)

    if sum(cleaned_values) == 0:
        cleaned_values = [1]
        cleaned_labels = ["No Data"]

    colors_list = [
        '#22C55E',
        '#3B82F6',
        '#F59E0B',
        '#EF4444'
    ]

    plt.figure(figsize=(6, 6))

    plt.pie(
        cleaned_values,
        labels=cleaned_labels,
        autopct='%1.1f%%',
        startangle=140,
        colors=colors_list,
        wedgeprops={'edgecolor': 'white'}
    )

    plt.title("Performance Distribution", fontsize=14)

    path = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".png"
    ).name

    plt.savefig(path, bbox_inches='tight')

    plt.close()

    return path
def create_scatter_chart(points):
    grades = [p["grade"] for p in points]
    attendance = [p["attendance"] for p in points]

    plt.figure()
    plt.scatter(attendance, grades)

    plt.xlabel("Attendance")
    plt.ylabel("Grade")

    path = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
    plt.savefig(path)
    plt.close()
    return path

def export_report(
    db,
    config,
    course_id=None,
    semester=None,
    days=None,
    from_date=None,
    to_date=None
):

    data = {}

    if getattr(config, "grade_distribution", False):
        data["performance"] = get_performance_distribution(
            db, course_id, semester, days, from_date, to_date
        )

    if getattr(config, "predictive_analytics", False):
        data["prediction"] = get_prediction(
            db, course_id, semester, days, from_date, to_date
        )

    if getattr(config, "error_analysis_detail", False):
        data["errors"] = common_error_analysis(
            db, course_id, semester, days, from_date, to_date
        )

    if getattr(config, "include_benchmarks", False):
        data["benchmarks"] = department_benchmarks(
            db, course_id, semester, days, from_date, to_date
        )

    if getattr(config, "attendance_data", False):
        data["correlation"] = get_attendance_correlation_report(
            db, course_id, semester, days, from_date, to_date
        )

    if getattr(config, "include_pii", False):
        data["students"] = get_student_insights(
            db, course_id, semester, days, from_date, to_date
        )

    # =====================================================
    # PDF EXPORT
    # =====================================================

    if config.export_format == "pdf":

        buffer = io.BytesIO()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(letter),
            rightMargin=18,
            leftMargin=18,
            topMargin=18,
            bottomMargin=18
        )

        styles = getSampleStyleSheet()

        page_width = landscape(letter)[0]
        usable_width = page_width - 36

        title_style = ParagraphStyle(
            "TitleStyle",
            parent=styles["Heading1"],
            fontSize=24,
            leading=28,
            textColor=colors.white,
            alignment=TA_LEFT
        )

        subtitle_style = ParagraphStyle(
            "SubtitleStyle",
            parent=styles["BodyText"],
            fontSize=10,
            leading=14,
            textColor=colors.white
        )

        section_style = ParagraphStyle(
            "SectionStyle",
            parent=styles["Heading2"],
            fontSize=15,
            leading=18,
            textColor=colors.HexColor("#111827"),
            spaceAfter=8,
            spaceBefore=10
        )

        description_style = ParagraphStyle(
            "DescriptionStyle",
            parent=styles["BodyText"],
            fontSize=9,
            leading=14,
            textColor=colors.HexColor("#4B5563")
        )

        elements = []

        # =====================================================
        # HEADER FULL WIDTH
        # =====================================================

        generated_date = datetime.now().strftime("%d %b %Y")

        logo = Image(
            "assets/logo.jpeg",
            width=55,
            height=55
        )

        title = Paragraph(
            "<b>ProFound Academic Analytics Report</b>",
            title_style
        )

        subtitle = Paragraph(
            f"""
            Professional academic performance and student analytics dashboard.<br/>
            Generated on {generated_date}
            """,
            subtitle_style
        )

        header_content = Table(
            [
                [
                    [title, subtitle],
                    logo
                ]
            ],
            colWidths=[usable_width - 90, 70]
        )

        header_content.setStyle(TableStyle([

            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),

            ('LEFTPADDING', (0,0), (-1,-1), 18),
            ('RIGHTPADDING', (0,0), (-1,-1), 18),

            ('TOPPADDING', (0,0), (-1,-1), 16),
            ('BOTTOMPADDING', (0,0), (-1,-1), 16),

        ]))

        header = Table(
            [[header_content]],
            colWidths=[usable_width]
        )

        header.setStyle(TableStyle([

            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#10B981")),

            ('BOX', (0,0), (-1,-1), 0, colors.white),

            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),

            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),

        ]))

        elements.append(header)

        elements.append(Spacer(1, 18))

        # =====================================================
        # PERFORMANCE CHART
        # =====================================================

        if (
            "performance" in data
            and data["performance"]
            and len(data["performance"]) > 0
        ):

            elements.append(
                Paragraph(
                    "Grade Distribution",
                    section_style
                )
            )

            elements.append(
                Paragraph(
                    """
                    This section presents the overall grade distribution
                    of students enrolled in the selected course. The chart
                    provides a visual overview of academic performance levels
                    and helps identify achievement trends.
                    """,
                    description_style
                )
            )

            elements.append(Spacer(1, 6))

            chart_path = create_grade_chart(data["performance"])

            elements.append(
                Image(
                    chart_path,
                    width=420,
                    height=220
                )
            )

            elements.append(Spacer(1, 14))

        # =====================================================
        # CORRELATION CHART
        # =====================================================

        if (
            "correlation" in data
            and data["correlation"]
            and data["correlation"].get("points")
        ):

            elements.append(
                Paragraph(
                    "Attendance Correlation",
                    section_style
                )
            )

            elements.append(
                Paragraph(
                    """
                    This analysis illustrates the relationship between
                    attendance rates and student academic performance.
                    The scatter chart assists instructors in identifying
                    how attendance behavior may impact grades.
                    """,
                    description_style
                )
            )

            elements.append(Spacer(1, 6))

            scatter_path = create_scatter_chart(
                data["correlation"]["points"]
            )

            elements.append(
                Image(
                    scatter_path,
                    width=420,
                    height=220
                )
            )

            elements.append(Spacer(1, 14))

        # =====================================================
        # PREDICTIVE ANALYTICS
        # =====================================================

        prediction_chart = []

        if (
            "prediction" in data
            and data["prediction"]
        ):

            prediction_chart = data["prediction"].get("chart", [])

        if len(prediction_chart) > 0:

            elements.append(
                Paragraph(
                    "Predictive Analytics",
                    section_style
                )
            )

            elements.append(
                Paragraph(
                    """
                    Predictive analytics compares actual academic outcomes
                    with forecasted performance values. This section supports
                    early identification of performance patterns and future
                    academic expectations.
                    """,
                    description_style
                )
            )

            elements.append(Spacer(1, 6))

            prediction_rows = [
                ["Week", "Actual", "Predicted"]
            ]

            for row in prediction_chart[:6]:

                prediction_rows.append([
                    str(row.get("label", "-")),
                    str(row.get("actual", "-")),
                    str(row.get("predicted", "-"))
                ])

            prediction_table = Table(
                prediction_rows,
                colWidths=[180, 180, 180]
            )

            prediction_table.setStyle(TableStyle([

                ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#10B981")),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),

                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#D1D5DB")),

                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),

                ('FONTSIZE', (0,0), (-1,-1), 9),

                ('ALIGN', (0,0), (-1,-1), 'CENTER'),

                ('TOPPADDING', (0,0), (-1,-1), 7),
                ('BOTTOMPADDING', (0,0), (-1,-1), 7),

            ]))

            elements.append(prediction_table)

            elements.append(Spacer(1, 14))

        # =====================================================
        # BENCHMARKS
        # =====================================================

        if (
            "benchmarks" in data
            and data["benchmarks"]
            and len(data["benchmarks"]) > 0
        ):

            elements.append(
                Paragraph(
                    "Department Benchmarks",
                    section_style
                )
            )

            elements.append(
                Paragraph(
                    """
                    Department benchmarks compare course performance metrics
                    against departmental averages. This comparison provides
                    insight into relative course effectiveness and academic quality.
                    """,
                    description_style
                )
            )

            elements.append(Spacer(1, 6))

            benchmark_rows = [
                ["Metric", "Course", "Department"]
            ]

            for b in data["benchmarks"][:6]:

                benchmark_rows.append([
                    str(b["metric"]),
                    str(b["yourCourse"]),
                    str(b["department"])
                ])

            benchmark_table = Table(
                benchmark_rows,
                colWidths=[300, 120, 120]
            )

            benchmark_table.setStyle(TableStyle([

                ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#10B981")),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),

                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#D1D5DB")),

                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),

                ('FONTSIZE', (0,0), (-1,-1), 9),

                ('ALIGN', (0,0), (-1,-1), 'CENTER'),

                ('TOPPADDING', (0,0), (-1,-1), 7),
                ('BOTTOMPADDING', (0,0), (-1,-1), 7),

            ]))

            elements.append(benchmark_table)

            elements.append(Spacer(1, 14))

        # =====================================================
        # STUDENTS INFORMATION
        # =====================================================

        students_list = []

        if (
            "students" in data
            and data["students"]
        ):

            students_list = data["students"].get("students", [])

        if len(students_list) > 0:

            elements.append(
                Paragraph(
                    "Students Information",
                    section_style
                )
            )

            elements.append(
                Paragraph(
                    """
                    This section provides a summary of student information
                    included in the generated report. It supports academic
                    tracking, departmental analysis, and institutional reporting.
                    """,
                    description_style
                )
            )

            elements.append(Spacer(1, 6))

            student_rows = [
                ["Student ID", "Name", "Department"]
            ]

            for s in students_list[:8]:

                student_rows.append([
                    str(s["id"]),
                    str(s["name"]),
                    str(s["department"])
                ])

            students_table = Table(
                student_rows,
                colWidths=[150, 260, 180]
            )

            students_table.setStyle(TableStyle([

                ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#10B981")),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),

                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#D1D5DB")),

                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),

                ('FONTSIZE', (0,0), (-1,-1), 9),

                ('ALIGN', (0,0), (-1,-1), 'CENTER'),

                ('TOPPADDING', (0,0), (-1,-1), 7),
                ('BOTTOMPADDING', (0,0), (-1,-1), 7),

            ]))

            elements.append(students_table)

            elements.append(Spacer(1, 14))

        # =====================================================
        # ERROR ANALYSIS
        # =====================================================

        if (
            "errors" in data
            and data["errors"]
            and len(data["errors"]) > 0
        ):
            # New shape: category / total_errors / percentage /
            #            affected_students / notes[{description, assignment}]
            error_rows = [
                ["Category", "Affected Students", "% of Errors", "Description (latest)"]
            ]

            for category in data["errors"][:5]:
                notes = category.get("notes", [])
                # Take the most recent note as a representative description
                latest_note = notes[0].get("description", "-") if notes else "-"
                # Truncate long descriptions so they fit in the PDF cell
                if len(latest_note) > 120:
                    latest_note = latest_note[:117] + "..."

                error_rows.append([
                    str(category["category"]),
                    str(category.get("affected_students", 0)),
                    f"{category.get('percentage', 0)}%",
                    latest_note,
                ])

            if len(error_rows) > 1:

                elements.append(
                    Paragraph(
                        "Error Analysis",
                        section_style
                    )
                )

                elements.append(
                    Paragraph(
                        """
                        Error analysis identifies the most frequent academic
                        or assessment-related issues observed in the selected
                        course. This information helps instructors improve
                        teaching strategies and student outcomes.
                        """,
                        description_style
                    )
                )

                elements.append(Spacer(1, 6))

                error_table = Table(
                    error_rows,
                    colWidths=[100, 90, 70, 380]
                )

                error_table.setStyle(TableStyle([

                    ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#10B981")),
                    ('TEXTCOLOR', (0,0), (-1,0), colors.white),

                    ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#D1D5DB")),

                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),

                    ('FONTSIZE', (0,0), (-1,-1), 9),

                    # Left-align the description column for readability
                    ('ALIGN', (0,0), (2,-1), 'CENTER'),
                    ('ALIGN', (3,0), (3,-1), 'LEFT'),

                    ('VALIGN', (0,0), (-1,-1), 'TOP'),

                    ('TOPPADDING', (0,0), (-1,-1), 7),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 7),
                    ('LEFTPADDING', (3,1), (3,-1), 6),

                ]))

                elements.append(error_table)

        # =====================================================
        # BUILD PDF
        # =====================================================

        doc.build(elements)

        buffer.seek(0)

        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename=analytics_report.pdf"
            }
        )

    # =====================================================
    # EXCEL EXPORT
    # =====================================================

    elif config.export_format == "excel":

        buffer = io.BytesIO()

        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:

            if "students" in data and data["students"].get("students"):

                students_rows = [
                    {
                        "Student ID": s["id"],
                        "Name": s["name"],
                        "Department": s["department"]
                    }
                    for s in data["students"]["students"]
                ]

                pd.DataFrame(students_rows).to_excel(
                    writer,
                    sheet_name="Students",
                    index=False
                )

            if "benchmarks" in data and data["benchmarks"]:

                pd.DataFrame(data["benchmarks"]).to_excel(
                    writer,
                    sheet_name="Benchmarks",
                    index=False
                )

            if "errors" in data and data["errors"]:
                # New shape: category / total_errors / percentage /
                #            affected_students / notes[{description, assignment}]
                error_rows = []
                for category in data["errors"]:
                    notes = category.get("notes", [])
                    if notes:
                        for note in notes:
                            error_rows.append({
                                "Category":          category.get("category", "-"),
                                "Affected Students": category.get("affected_students", 0),
                                "% of Errors":       category.get("percentage", 0),
                                "Assignment":        note.get("assignment", "-"),
                                "Description":       note.get("description", "-"),
                            })
                    else:
                        # category has no notes yet — still include the summary row
                        error_rows.append({
                            "Category":          category.get("category", "-"),
                            "Affected Students": category.get("affected_students", 0),
                            "% of Errors":       category.get("percentage", 0),
                            "Assignment":        "-",
                            "Description":       "-",
                        })

                if error_rows:
                    pd.DataFrame(error_rows).to_excel(
                        writer,
                        sheet_name="Errors",
                        index=False
                    )

            if "performance" in data and data["performance"]:

                perf_rows = [
                    {
                        "Category": k,
                        "Count": v
                    }
                    for k, v in data["performance"].items()
                ]

                pd.DataFrame(perf_rows).to_excel(
                    writer,
                    sheet_name="Performance",
                    index=False
                )

            if (
                "prediction" in data
                and data["prediction"]
                and data["prediction"].get("chart")
            ):

                pd.DataFrame(
                    data["prediction"]["chart"]
                ).to_excel(
                    writer,
                    sheet_name="Prediction",
                    index=False
                )

        buffer.seek(0)

        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": "attachment; filename=analytics_report.xlsx"
            }
        )
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": "attachment; filename=report.xlsx"
            }
        )