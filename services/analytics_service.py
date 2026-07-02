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
def get_at_risk_students(
    db,
    course_id=None,
    semester=None,
    department_id=None
):
    """
    Get filtered students and calculate risk using:
    Grade + Attendance
    """

    query = db.query(
        StudentDB.student_id.label("student_id"),
        StudentDB.name.label("student_name"),
        PerformanceDB.grade,
        PerformanceDB.attendance
    ).join(
        PerformanceDB,
        StudentDB.id == PerformanceDB.student_id
    )

    if course_id:
        query = query.filter(
            PerformanceDB.course_id == course_id
        )


    if semester and semester.strip() and semester != "All Semesters":
        query = query.join(
            CourseDB,
            CourseDB.id == PerformanceDB.course_id
        ).filter(
            CourseDB.semester == semester.strip()
        )

    if department_id:
        query = query.filter(
            StudentDB.department_id == department_id
        )


    students = query.all()


    risk_students = []


    for student in students:


        # Grade risk

        grade_risk = 100 - float(student.grade)


        # Attendance risk

        attendance_risk = 100 - float(student.attendance)



        # Risk score

        risk_score = (
            (grade_risk * 0.7)
            +
            (attendance_risk * 0.3)
        )



        # Risk level
        # Direct grade override: below 55 is always High risk
        if float(student.grade) < 55:
            risk_level = "High"

        elif risk_score >= 60:
            risk_level = "High"

        elif risk_score >= 45:
            risk_level = "Medium"

        else:
            risk_level = "Low"



        # Only add risky students

        if risk_level != "Low":


            risk_students.append({

                "Student ID":
                    student.student_id,


                "Student Name":
                    student.student_name,


                "Grade":
                    student.grade,


                "Attendance":
                    student.attendance,


                "Risk Score":
                    round(risk_score, 2),


                "Risk Level":
                    risk_level

            })


    return risk_students
def generate_recommendations(perf_dist, correlation, errors, prediction, at_risk_list):
    """
    Analyse the collected analytics data and return a list of actionable
    recommendations for the professor.  Each recommendation is a dict:
        {
            "priority": "High" | "Medium" | "Low",
            "area":     short label,
            "finding":  what the data shows,
            "action":   concrete thing the professor should do,
        }
    """
    recs = []

    # ── 1. Grade distribution ─────────────────────────────────────────────
    total_students = sum(perf_dist.values()) if perf_dist else 0
    at_risk_count  = len(at_risk_list)

    if total_students > 0:
        at_risk_pct    = (perf_dist.get("At-Risk (<70)", 0) / total_students) * 100
        excellent_pct  = (perf_dist.get("Excellent (90-100)", 0) / total_students) * 100
        avg_grade_vals = []
        weights        = {"Excellent (90-100)": 95, "Good (80-89)": 84,
                          "Average (70-79)": 74, "At-Risk (<70)": 55}
        for bucket, cnt in perf_dist.items():
            avg_grade_vals.extend([weights.get(bucket, 60)] * cnt)
        class_avg = sum(avg_grade_vals) / len(avg_grade_vals) if avg_grade_vals else 0

        if at_risk_pct >= 40:
            recs.append({
                "priority": "High",
                "area": "Overall Performance",
                "finding": f"{at_risk_pct:.0f}% of students are below 70 — class average is approximately {class_avg:.0f}%.",
                "action": (
                    "Conduct an urgent course review session. Revisit foundational topics "
                    "and consider simplifying assessment difficulty or adding remedial materials."
                ),
            })
        elif at_risk_pct >= 20:
            recs.append({
                "priority": "Medium",
                "area": "Overall Performance",
                "finding": f"{at_risk_pct:.0f}% of students are below 70.",
                "action": (
                    "Schedule targeted revision sessions for weaker topics. "
                    "Identify the specific modules where grades drop and reinforce them."
                ),
            })

        if excellent_pct >= 50 and at_risk_pct <= 10:
            recs.append({
                "priority": "Low",
                "area": "Overall Performance",
                "finding": f"{excellent_pct:.0f}% of students are in the Excellent range.",
                "action": (
                    "Class is performing well. Consider introducing advanced extension tasks "
                    "or research challenges to keep high achievers engaged."
                ),
            })


    # ── 2. Attendance correlation ─────────────────────────────────────────
    r2 = correlation.get("stats", {}).get("r_squared", 0) if correlation else 0
    if r2 >= 0.5:
        recs.append({
            "priority": "High",
            "area": "Attendance",
            "finding": f"Attendance strongly predicts grade performance (R² = {r2:.2f}).",
            "action": (
                "Enforce attendance policy and introduce engagement incentives. "
                "Follow up with students who have missed more than 2 consecutive sessions."
            ),
        })
    elif r2 >= 0.3:
        recs.append({
            "priority": "Medium",
            "area": "Attendance",
            "finding": f"Moderate link between attendance and grades (R² = {r2:.2f}).",
            "action": (
                "Monitor attendance trends. Send reminders to students with declining "
                "attendance before it starts affecting their performance."
            ),
        })

    # ── 3. Error category analysis ────────────────────────────────────────
    if errors:
        top_error = errors[0]  # already sorted by frequency
        cat   = top_error.get("category", "")
        pct   = top_error.get("percentage", 0)
        count = top_error.get("affected_students", 0)

        action_map = {
            "Conceptual": (
                "Students are struggling with core concepts. Dedicate extra lecture time "
                "to the most misunderstood topics and use concept-check quizzes."
            ),
            "Structural": (
                "Students have difficulty organising their answers. Provide clear templates "
                "and examples of well-structured responses for upcoming assignments."
            ),
            "Language": (
                "Language and clarity issues are common. Recommend academic writing "
                "resources and consider holding a writing workshop."
            ),
            "Completeness": (
                "Students consistently miss required points. Make assessment criteria more "
                "explicit — share a detailed marking rubric before each assignment."
            ),
        }

        recs.append({
            "priority": "High" if pct >= 40 else "Medium",
            "area": f"Error Pattern — {cat}",
            "finding": (
                f"{cat} errors are the most frequent ({pct:.0f}% of all errors, "
                f"affecting {count} student(s))."
            ),
            "action": action_map.get(cat, "Review related course material with the class."),
        })

        # Second-most-common error if significant
        if len(errors) >= 2:
            second = errors[1]
            s_cat  = second.get("category", "")
            s_pct  = second.get("percentage", 0)
            if s_pct >= 20 and s_cat != cat:
                recs.append({
                    "priority": "Medium",
                    "area": f"Error Pattern — {s_cat}",
                    "finding": f"{s_cat} errors represent {s_pct:.0f}% of all errors.",
                    "action": action_map.get(s_cat, "Review related course material."),
                })

    # ── 4. Predictive trend ───────────────────────────────────────────────
    if prediction and prediction.get("chart"):
        chart = prediction["chart"]
        actual_points = [c["actual"] for c in chart if c.get("actual") is not None]
        pred_points   = [c["predicted"] for c in chart if c.get("predicted") is not None]

        if len(actual_points) >= 2:
            trend_direction = actual_points[-1] - actual_points[0]
            final_pred      = pred_points[-1] if pred_points else None

            if trend_direction < -5:
                recs.append({
                    "priority": "High",
                    "area": "Performance Trend",
                    "finding": (
                        f"Class average is declining (dropped {abs(trend_direction):.1f}% "
                        f"over the recorded period)."
                        + (f" Forecast: {final_pred:.0f}% by end of term." if final_pred else "")
                    ),
                    "action": (
                        "Investigate what changed in recent weeks — new topics, harder assignments, "
                        "or reduced engagement. Adjust pacing or difficulty accordingly."
                    ),
                })
            elif trend_direction > 5:
                recs.append({
                    "priority": "Low",
                    "area": "Performance Trend",
                    "finding": (
                        f"Class average is improving (+{trend_direction:.1f}% over the period)."
                        + (f" Forecast: {final_pred:.0f}% by end of term." if final_pred else "")
                    ),
                    "action": (
                        "Current teaching strategy is working well. "
                        "Keep the momentum and maintain the same feedback approach."
                    ),
                })

    # Sort: High first, then Medium, then Low
    priority_order = {"High": 0, "Medium": 1, "Low": 2}
    recs.sort(key=lambda r: priority_order.get(r["priority"], 3))

    return recs


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

    # Always collect performance + errors for recommendations,
    # regardless of which toggles the professor chose
    _perf_all  = get_performance_distribution(db, course_id, semester, days, from_date, to_date)
    _corr_all  = get_attendance_correlation_report(db, course_id, semester, days, from_date, to_date)
    _err_all   = common_error_analysis(db, course_id, semester, days, from_date, to_date)
    _pred_all  = get_prediction(db, course_id, semester, days, from_date, to_date)
    _risk_all  = get_at_risk_students(db, course_id=course_id, semester=semester)
    data["recommendations"] = generate_recommendations(
        _perf_all, _corr_all, _err_all, _pred_all, _risk_all
    )

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

    if getattr(config, "include_at_risk", False):
        data["at_risk"] = get_at_risk_students(
            db, course_id=course_id, semester=semester
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
        # RECOMMENDATIONS
        # =====================================================

        recs = data.get("recommendations", [])

        if recs:
            elements.append(Paragraph("Recommendations & Insights", section_style))
            elements.append(
                Paragraph(
                    "Based on the collected analytics, the following actions are recommended "
                    "to improve student outcomes and course effectiveness.",
                    description_style,
                )
            )
            elements.append(Spacer(1, 8))

            priority_colors = {
                "High":   colors.HexColor("#FEF2F2"),
                "Medium": colors.HexColor("#FFFBEB"),
                "Low":    colors.HexColor("#F0FDF4"),
            }
            priority_text_colors = {
                "High":   colors.HexColor("#DC2626"),
                "Medium": colors.HexColor("#D97706"),
                "Low":    colors.HexColor("#16A34A"),
            }

            # Paragraph styles for wrapping inside cells
            cell_style = ParagraphStyle(
                "CellStyle",
                parent=styles["BodyText"],
                fontSize=9,
                leading=13,
                textColor=colors.HexColor("#111827"),
            )
            header_cell_style = ParagraphStyle(
                "HeaderCellStyle",
                parent=styles["BodyText"],
                fontSize=9,
                leading=13,
                textColor=colors.white,
                fontName="Helvetica-Bold",
            )

            rec_rows = [[
                Paragraph("Priority", header_cell_style),
                Paragraph("Area", header_cell_style),
                Paragraph("Finding", header_cell_style),
                Paragraph("Recommended Action", header_cell_style),
            ]]

            for r in recs:
                p_color = priority_text_colors.get(r["priority"], colors.black)
                priority_style = ParagraphStyle(
                    f"P_{r['priority']}",
                    parent=cell_style,
                    textColor=p_color,
                    fontName="Helvetica-Bold",
                    alignment=1,  # center
                )
                rec_rows.append([
                    Paragraph(r["priority"], priority_style),
                    Paragraph(r["area"], cell_style),
                    Paragraph(r["finding"], cell_style),
                    Paragraph(r["action"], cell_style),
                ])

            rec_table = Table(
                rec_rows,
                colWidths=[55, 120, 265, 210],
            )

            rec_style = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#10B981")),
                ("GRID",       (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                ("VALIGN",     (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING",    (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ]

            # Colour the priority cell background per row
            for i, r in enumerate(recs, start=1):
                bg = priority_colors.get(r["priority"], colors.white)
                rec_style.append(("BACKGROUND", (0, i), (0, i), bg))

            rec_table.setStyle(TableStyle(rec_style))
            elements.append(rec_table)
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

            for row in prediction_chart:

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

            for s in students_list:

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
        # AT-RISK STUDENTS
        # =====================================================

        at_risk_list = data.get("at_risk", [])

        if len(at_risk_list) > 0:

            elements.append(
                Paragraph("At-Risk Students", section_style)
            )

            elements.append(
                Paragraph(
                    "The following students have been identified as at risk based on "
                    "their grade and attendance scores. Risk Score = (grade risk × 0.7) + (attendance risk × 0.3). "
                    "Immediate intervention is recommended.",
                    description_style,
                )
            )

            elements.append(Spacer(1, 6))

            cell_wrap = ParagraphStyle(
                "AtRiskCell",
                parent=styles["BodyText"],
                fontSize=9,
                leading=12,
                textColor=colors.HexColor("#111827"),
            )
            hdr_wrap = ParagraphStyle(
                "AtRiskHdr",
                parent=cell_wrap,
                textColor=colors.white,
                fontName="Helvetica-Bold",
            )

            at_risk_rows = [[
                Paragraph("Student ID", hdr_wrap),
                Paragraph("Name", hdr_wrap),
                Paragraph("Grade", hdr_wrap),
                Paragraph("Attendance", hdr_wrap),
                Paragraph("Risk Score", hdr_wrap),
                Paragraph("Risk Level", hdr_wrap),
            ]]

            for s in at_risk_list:
                level = s.get("Risk Level", "-")
                level_color = (
                    colors.HexColor("#DC2626") if level == "High"
                    else colors.HexColor("#D97706") if level == "Medium"
                    else colors.HexColor("#111827")
                )
                level_style = ParagraphStyle(
                    f"RiskLevel_{level}",
                    parent=cell_wrap,
                    textColor=level_color,
                    fontName="Helvetica-Bold",
                    alignment=1,
                )
                at_risk_rows.append([
                    Paragraph(str(s.get("Student ID", "-")), cell_wrap),
                    Paragraph(str(s.get("Student Name", "-")), cell_wrap),
                    Paragraph(str(s.get("Grade", "-")), cell_wrap),
                    Paragraph(str(s.get("Attendance", "-")), cell_wrap),
                    Paragraph(str(s.get("Risk Score", "-")), cell_wrap),
                    Paragraph(level, level_style),
                ])

            at_risk_table = Table(
                at_risk_rows,
                colWidths=[80, 170, 60, 70, 70, 60],
            )

            at_risk_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EF4444")),
                ("GRID",       (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
                ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING",    (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ]))

            elements.append(at_risk_table)
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
            err_cell = ParagraphStyle(
                "ErrCell",
                parent=styles["BodyText"],
                fontSize=9,
                leading=12,
                textColor=colors.HexColor("#111827"),
            )
            err_hdr = ParagraphStyle(
                "ErrHdr",
                parent=err_cell,
                textColor=colors.white,
                fontName="Helvetica-Bold",
            )

            error_rows = [[
                Paragraph("Category", err_hdr),
                Paragraph("Affected Students", err_hdr),
                Paragraph("% of Errors", err_hdr),
                Paragraph("Description (latest)", err_hdr),
            ]]

            for category in data["errors"][:5]:
                notes = category.get("notes", [])
                latest_note = notes[0].get("description", "-") if notes else "-"

                error_rows.append([
                    Paragraph(str(category["category"]), err_cell),
                    Paragraph(str(category.get("affected_students", 0)), err_cell),
                    Paragraph(f"{category.get('percentage', 0)}%", err_cell),
                    Paragraph(latest_note, err_cell),
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
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#10B981")),
                    ('GRID',       (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                    ('VALIGN',     (0, 0), (-1, -1), 'TOP'),
                    ('ALIGN',      (0, 0), (2, -1),  'CENTER'),
                    ('TOPPADDING',    (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ('LEFTPADDING',   (0, 0), (-1, -1), 6),
                    ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
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

            # Recommendations sheet — always first
            if data.get("recommendations"):
                rec_rows = [
                    {
                        "Priority":             r["priority"],
                        "Area":                 r["area"],
                        "Finding":              r["finding"],
                        "Recommended Action":   r["action"],
                    }
                    for r in data["recommendations"]
                ]
                pd.DataFrame(rec_rows).to_excel(
                    writer,
                    sheet_name="Recommendations",
                    index=False,
                )

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

            if "at_risk" in data and data["at_risk"]:

                pd.DataFrame(data["at_risk"]).to_excel(
                    writer,
                    sheet_name="At-Risk Students",
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