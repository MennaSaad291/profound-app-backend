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

from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib import colors
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


    # # Smooth actual
    # x_smooth = np.linspace(X.min(), X.max(), 200)
    # actual_spline = make_interp_spline(X, y, k=2)
    # actual_smooth = actual_spline(x_smooth)

    # # Smooth predicted
    # x_pred_smooth = np.linspace(X_all.min(), X_all.max(), 300)
    # pred_spline = make_interp_spline(X_all, preds, k=2)
    # pred_smooth = pred_spline(x_pred_smooth)

    # # clamp (UI safety)
    # pred_smooth = np.clip(pred_smooth, 40, 100)
    # actual_smooth = np.clip(actual_smooth, 40, 100)

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

    query = db.query(ErrorAnalysisDB)

    query = apply_filters(
        query,
        ErrorAnalysisDB,
        course_id,
        semester,
        days,
        from_date,
        to_date,
        join_course=True
    )

    total_errors = query.count()

    if total_errors == 0:
        return []

    categories = db.query(
        ErrorAnalysisDB.error_category,
        func.count(ErrorAnalysisDB.id).label("count")
    )

    categories = apply_filters(
        categories,
        ErrorAnalysisDB,
        course_id,
        semester,
        days,
        from_date,
        to_date,
        join_course=True
    ).group_by(ErrorAnalysisDB.error_category).all()

    result = []

    for cat in categories:

        percentage = (cat.count / total_errors) * 100

        error_types_query = db.query(
            ErrorAnalysisDB.error_type,
            func.count(ErrorAnalysisDB.id).label("count"),
            func.count(func.distinct(ErrorAnalysisDB.student_id)).label("students")
        )

        error_types_query = apply_filters(
            error_types_query,
            ErrorAnalysisDB,
            course_id,
            semester,
            days,
            from_date,
            to_date,
            join_course=True
        )

        error_types_query = error_types_query.filter(
            ErrorAnalysisDB.error_category == cat.error_category
        ).group_by(ErrorAnalysisDB.error_type).all()

        patterns = []

        for e in error_types_query:
            patterns.append({
                "error_type": e.error_type,
                "occurrences": e.count,
                "affected_students": e.students
            })

        result.append({
            "category": cat.error_category,
            "total_errors": cat.count,
            "percentage": round(percentage, 2),
            "patterns": patterns
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
    #  ASSIGNMENTS 

    # assign_course = db.query(AssignmentDB).filter(
    #     AssignmentDB.course_id == course_id
    # )

    # assign_course = apply_filters(
    #     assign_course,
    #     AssignmentDB,
    #     course_id,
    #     semester,
    #     days,
    #     from_date,
    #     to_date,
    #     join_course=False
    # )

    # total_assign = assign_course.count()

    # if total_assign == 0:
    #     your_assignment_completion = 0
    # else:
    #     submitted = assign_course.filter(AssignmentDB.is_submitted == True).count()
    #     your_assignment_completion = (submitted * 100.0) / total_assign

    # assign_dept = db.query(AssignmentDB)

    # assign_dept = apply_filters(
    #     assign_dept,
    #     AssignmentDB,
    #     None,
    #     semester,
    #     days,
    #     from_date,
    #     to_date,
    #     join_course=True
    # )

    # assign_dept = assign_dept.filter(CourseDB.department == department)

    # total_assign_dept = assign_dept.count()

    # if total_assign_dept == 0:
    #     dept_assignment_completion = 0
    # else:
    #     submitted_dept = assign_dept.filter(
    #         AssignmentDB.is_submitted == True
    #     ).count()

    #     dept_assignment_completion = (submitted_dept * 100.0) / total_assign_dept


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
            # {
            #     "metric": "Assignment Completion",
            #     "yourCourse": round(your_assignment_completion, 1),
            #     "department": round(dept_assignment_completion, 1),
            #     "difference": f"{'+' if your_assignment_completion >= dept_assignment_completion else ''}{round(your_assignment_completion - dept_assignment_completion, 1)}%"
            # }
            
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

    plt.figure()

    plt.pie(cleaned_values, labels=cleaned_labels, autopct="%1.1f%%")

    path = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
    plt.savefig(path)
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

def export_report(db, config, course_id=None, semester=None, days=None, from_date=None, to_date=None):

    data = {}

    if getattr(config, "grade_distribution", False):
        data["performance"] = get_performance_distribution(db, course_id, semester, days, from_date, to_date)

    if getattr(config, "predictive_analytics", False):
        data["prediction"] = get_prediction(db, course_id, semester, days, from_date, to_date)

    if getattr(config, "error_analysis_detail", False):
        data["errors"] = common_error_analysis(db, course_id, semester, days, from_date, to_date)

    if getattr(config, "include_benchmarks", False):
        data["benchmarks"] = department_benchmarks(db, course_id, semester, days, from_date, to_date)

    if getattr(config, "attendance_data", False):
        data["correlation"] = get_attendance_correlation_report(db, course_id, semester, days, from_date, to_date)

    if getattr(config, "include_pii", False):
        data["students"] = get_student_insights(db, course_id, semester, days, from_date, to_date)


    if config.export_format == "pdf":
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer)
        styles = getSampleStyleSheet()
        elements = []

        
        elements.append(Paragraph("Analytics Report", styles["Title"]))
        elements.append(Spacer(1, 20))

        # STUDENTS 
        if "students" in data:

            elements.append(Paragraph(" Students Information", styles["Heading2"]))
            elements.append(Spacer(1, 10))

            rows = [["Student ID", "Name", "Department"]]

            for s in data["students"]["students"]:
                rows.append([
                    s["id"],
                    s["name"],
                    s["department"]
                ])

            table = Table(rows, hAlign="CENTER")

            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]))

            elements.append(table)
            elements.append(Spacer(1, 20))

        #  CORRELATION 
        if "correlation" in data and "points" in data["correlation"]:

            elements.append(Paragraph("Attendance vs Grade Correlation", styles["Heading2"]))
            elements.append(Spacer(1, 10))

            chart_path = create_scatter_chart(data["correlation"]["points"])
            elements.append(Image(chart_path, width=400, height=300))
            elements.append(Spacer(1, 20))

        #  PERFORMANCE
        if "performance" in data:

            elements.append(Paragraph("📊 Grade Distribution", styles["Heading2"]))
            elements.append(Spacer(1, 10))

            chart_path = create_grade_chart(data["performance"])
            elements.append(Image(chart_path, width=400, height=300))
            elements.append(Spacer(1, 20))

        #  PREDICTION
        if "prediction" in data:

            elements.append(Paragraph(" Predictive Analytics", styles["Heading2"]))
            elements.append(Spacer(1, 10))

            rows = [["Week", "Actual", "Predicted", "At-Risk"]]

            for c in data["prediction"].get("chart", []):
                rows.append([
                    c.get("label"),
                    c.get("actual", "-"),
                    c.get("predicted", "-"),
                    c.get("at_risk_students", "-")
                ])

            table = Table(rows, hAlign="CENTER")

            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.darkgreen),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]))

            elements.append(table)
            elements.append(Spacer(1, 20))

        #  BENCHMARKS
        if "benchmarks" in data:

            elements.append(Paragraph(" Department Benchmarks", styles["Heading2"]))
            elements.append(Spacer(1, 10))

            rows = [["Metric", "Your Course", "Department", "Difference"]]

            for b in data["benchmarks"]:
                rows.append([
                    b["metric"],
                    b["yourCourse"],
                    b["department"],
                    b["difference"]
                ])

            table = Table(rows, hAlign="CENTER")

            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]))

            elements.append(table)
            elements.append(Spacer(1, 20))

        #  ERROR ANALYSIS 

        if "errors" in data and data["errors"]:

            elements.append(Paragraph(" Error Analysis", styles["Heading2"]))
            elements.append(Spacer(1, 10))

            rows = [["Category", "Type", "Common Mistake"]]

            for category in data["errors"]:
                cat_name = category["category"]

                for pattern in category.get("patterns", []):
                    rows.append([
                        cat_name,
                        pattern.get("error_type", "-"),
                        f"Occurs {pattern.get('occurrences', 0)} times"
                    ])

            table = Table(rows, hAlign="CENTER")

            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.red),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]))

            elements.append(table)
            elements.append(Spacer(1, 20))


        # BUILD PDF

            doc.build(elements)
            buffer.seek(0)

            return StreamingResponse(
                buffer,
                media_type="application/pdf",
                headers={"Content-Disposition": "attachment; filename=report.pdf"}
            )
    elif config.export_format == "excel":

        buffer = io.BytesIO()

        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:

    
            #  STUDENTS SHEET
    
            if "students" in data:

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

    
            #  BENCHMARKS SHEET
    
            if "benchmarks" in data:

                pd.DataFrame(data["benchmarks"]).to_excel(
                    writer,
                    sheet_name="Benchmarks",
                    index=False
                )

    
            #  ERRORS SHEET 
    
            if "errors" in data and data["errors"]:

                error_rows = []

                for category in data["errors"]:
                    cat_name = category.get("category", "-")

                    for pattern in category.get("patterns", []):
                        error_rows.append({
                            "Category": cat_name,
                            "Type": pattern.get("error_type", "-"),
                            "Occurrences": pattern.get("occurrences", 0),
                            "Affected Students": pattern.get("affected_students", 0)
                        })

                pd.DataFrame(error_rows).to_excel(
                    writer,
                    sheet_name="Errors",
                    index=False
                )

    
            #  PERFORMANCE SHEET
    
            if "performance" in data:

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

    
            # PREDICTION SHEET 
    
            if "prediction" in data:

                pred = data["prediction"]

                if "chart" in pred:

                    pd.DataFrame(pred["chart"]).to_excel(
                        writer,
                        sheet_name="Prediction",
                        index=False
                    )

        buffer.seek(0)

        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=report.xlsx"}
        )