"""
test_courses.py — integration tests for Course & Student endpoints.
"""
import pytest
from conftest import register_and_login


@pytest.fixture
def user_and_course(client):
    """Register a user and create a course, return both."""
    user = register_and_login(client, "course_owner@uni.edu")
    resp = client.post("/courses", json={
        "user_id": user["id"],
        "code": "CS101",
        "name": "Intro to CS",
        "semester": "Fall 2025",
        "department": "Computer Science"
    })
    assert resp.status_code == 200
    course_id = resp.json()["id"]
    return user, course_id


# ── Course CRUD ───────────────────────────────────────────────────────────────

class TestCourseCRUD:
    def test_create_course(self, client):
        user = register_and_login(client, "newcourse@uni.edu")
        resp = client.post("/courses", json={
            "user_id": user["id"],
            "code": "DS201",
            "name": "Data Structures",
            "semester": "Spring 2026"
        })
        assert resp.status_code == 200
        assert "id" in resp.json()

    def test_update_course(self, client, user_and_course):
        _, course_id = user_and_course
        resp = client.put(f"/courses/{course_id}", json={
            "code": "CS101",
            "name": "Updated Course Name",
            "semester": "Fall 2025",
            "status": "active",
            "schedule": "Mon 10:00",
            "room": "Room 301"
        })
        assert resp.status_code == 200
        assert resp.json()["message"] == "Course updated"

    def test_update_course_not_found(self, client):
        resp = client.put("/courses/99999", json={
            "code": "XX", "name": "X", "semester": "Fall 2025",
            "status": "active", "schedule": "TBA", "room": "TBA"
        })
        assert resp.status_code == 404

    def test_delete_course(self, client):
        user = register_and_login(client, "deletecourse@uni.edu")
        create_resp = client.post("/courses", json={
            "user_id": user["id"], "code": "DEL101",
            "name": "To Delete", "semester": "Fall 2025"
        })
        course_id = create_resp.json()["id"]
        del_resp = client.delete(f"/courses/{course_id}")
        assert del_resp.status_code == 200

    def test_delete_course_not_found(self, client):
        resp = client.delete("/courses/99999")
        assert resp.status_code == 404


# ── Students ──────────────────────────────────────────────────────────────────

class TestStudents:
    def test_add_student(self, client, user_and_course):
        _, course_id = user_and_course
        resp = client.post(f"/courses/{course_id}/students", json={
            "student_id": "20220001",
            "name": "Ahmed Mohamed",
            "department": "CS",
            "course_id": course_id
        })
        assert resp.status_code == 200
        assert "id" in resp.json()

    def test_add_duplicate_student(self, client, user_and_course):
        _, course_id = user_and_course
        payload = {"student_id": "20220002", "name": "Duplicate",
                   "department": "CS", "course_id": course_id}
        client.post(f"/courses/{course_id}/students", json=payload)
        resp = client.post(f"/courses/{course_id}/students", json=payload)
        assert resp.status_code == 400
        assert "already enrolled" in resp.json()["detail"]

    def test_get_students(self, client, user_and_course):
        _, course_id = user_and_course
        client.post(f"/courses/{course_id}/students", json={
            "student_id": "20220003", "name": "Student A",
            "department": "CS", "course_id": course_id
        })
        resp = client.get(f"/courses/{course_id}/students")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) >= 1

    def test_delete_student(self, client, user_and_course):
        _, course_id = user_and_course
        add_resp = client.post(f"/courses/{course_id}/students", json={
            "student_id": "20220099", "name": "To Remove",
            "department": "CS", "course_id": course_id
        })
        student_id = add_resp.json()["id"]
        del_resp = client.delete(f"/courses/{course_id}/students/{student_id}")
        assert del_resp.status_code == 200

    def test_delete_student_not_found(self, client, user_and_course):
        _, course_id = user_and_course
        resp = client.delete(f"/courses/{course_id}/students/99999")
        assert resp.status_code == 404

    def test_add_student_course_not_found(self, client):
        resp = client.post("/courses/99999/students", json={
            "student_id": "20220005", "name": "Ghost",
            "department": "CS", "course_id": 99999
        })
        assert resp.status_code == 404


# ── Course Analytics ──────────────────────────────────────────────────────────

class TestCourseAnalytics:
    def test_analytics_no_data(self, client, user_and_course):
        _, course_id = user_and_course
        resp = client.get(f"/course-analytics/{course_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["average"] == "N/A"
        assert data["at_risk"] == 0


# ── Schedule ──────────────────────────────────────────────────────────────────

class TestSchedule:
    def test_add_and_get_slot(self, client, user_and_course):
        _, course_id = user_and_course
        add_resp = client.post(f"/courses/{course_id}/schedule", json={
            "day": "Monday", "start_time": "09:00",
            "end_time": "10:30", "room": "Hall A"
        })
        assert add_resp.status_code == 200
        slot_id = add_resp.json()["id"]

        get_resp = client.get(f"/courses/{course_id}/schedule")
        assert get_resp.status_code == 200
        slots = get_resp.json()
        assert any(s["id"] == slot_id for s in slots)

    def test_update_slot(self, client, user_and_course):
        _, course_id = user_and_course
        slot_id = client.post(f"/courses/{course_id}/schedule", json={
            "day": "Tuesday", "start_time": "11:00",
            "end_time": "12:30", "room": "Hall B"
        }).json()["id"]

        resp = client.put(f"/courses/{course_id}/schedule/{slot_id}", json={
            "day": "Wednesday", "start_time": "14:00",
            "end_time": "15:30", "room": "Hall C"
        })
        assert resp.status_code == 200

    def test_delete_slot(self, client, user_and_course):
        _, course_id = user_and_course
        slot_id = client.post(f"/courses/{course_id}/schedule", json={
            "day": "Thursday", "start_time": "08:00",
            "end_time": "09:30", "room": "Hall D"
        }).json()["id"]

        resp = client.delete(f"/courses/{course_id}/schedule/{slot_id}")
        assert resp.status_code == 200

    def test_delete_slot_not_found(self, client, user_and_course):
        _, course_id = user_and_course
        resp = client.delete(f"/courses/{course_id}/schedule/99999")
        assert resp.status_code == 404
