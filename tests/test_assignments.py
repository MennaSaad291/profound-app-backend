"""
test_assignments.py — integration tests for Assignment & Grading endpoints.
"""
import io
import pytest
from conftest import register_and_login


@pytest.fixture
def setup(client):
    """Create a user, a course, and return both IDs."""
    user = register_and_login(client, "assign_owner@uni.edu")
    course_id = client.post("/courses", json={
        "user_id": user["id"], "code": "AS101",
        "name": "Assignment Test Course", "semester": "Fall 2025"
    }).json()["id"]
    return user, course_id


@pytest.fixture
def assignment(client, setup):
    """Create a model-answer assignment and return its ID."""
    _, course_id = setup
    resp = client.post("/assignments", data={
        "assignment_name": "HW1 - Data Structures",
        "course_id": str(course_id),
        "assignment_question": "Explain a linked list.",
        "is_model_answer": "true",
        "model_answer": "A linked list is a sequence of nodes each pointing to the next."
    })
    assert resp.status_code == 200
    return resp.json()["id"]


# ── Create Assignment ─────────────────────────────────────────────────────────

class TestCreateAssignment:
    def test_create_model_answer_assignment(self, client, setup):
        _, course_id = setup
        resp = client.post("/assignments", data={
            "assignment_name": "Essay Assignment",
            "course_id": str(course_id),
            "assignment_question": "What is recursion?",
            "is_model_answer": "true",
            "model_answer": "Recursion is a function calling itself."
        })
        assert resp.status_code == 200
        assert "id" in resp.json()

    def test_create_rubric_assignment(self, client, setup):
        _, course_id = setup
        resp = client.post("/assignments", data={
            "assignment_name": "Rubric Assignment",
            "course_id": str(course_id),
            "assignment_question": "Describe sorting algorithms.",
            "is_model_answer": "false",
            "rubric": "1. Correctness (50%) 2. Explanation (50%)"
        })
        assert resp.status_code == 200

    def test_create_assignment_invalid_course(self, client):
        resp = client.post("/assignments", data={
            "assignment_name": "Ghost Assignment",
            "course_id": "99999",
            "is_model_answer": "true"
        })
        assert resp.status_code == 400


# ── Update Assignment ─────────────────────────────────────────────────────────

class TestUpdateAssignment:
    def test_update_assignment_name(self, client, setup, assignment):
        resp = client.put(f"/assignments/{assignment}", data={
            "assignment_name": "HW1 - Updated Title",
            "assignment_question": "Explain a linked list.",
            "is_model_answer": "true",
            "model_answer": "A linked list is a sequence of nodes."
        })
        assert resp.status_code == 200
        assert resp.json()["assignment_name"] == "HW1 - Updated Title"

    def test_update_assignment_not_found(self, client):
        resp = client.put("/assignments/99999", data={
            "assignment_name": "Ghost", "is_model_answer": "true"
        })
        assert resp.status_code == 404

    def test_update_switches_mode_to_rubric(self, client, setup, assignment):
        resp = client.put(f"/assignments/{assignment}", data={
            "assignment_name": "HW1 - Rubric Mode",
            "assignment_question": "Explain a linked list.",
            "is_model_answer": "false",
            "rubric": "Accuracy 100%"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_model_answer"] is False
        assert data["model_answer"] is None
        assert data["rubric"] == "Accuracy 100%"


# ── List Assignments with Submissions ─────────────────────────────────────────

class TestListAssignments:
    def test_list_assignments_empty(self, client, setup):
        user, _ = setup
        # Use a new course with no assignments
        new_course_id = client.post("/courses", json={
            "user_id": user["id"], "code": "EMPTY101",
            "name": "Empty Course", "semester": "Fall 2025"
        }).json()["id"]
        resp = client.get(f"/assignments-with-submissions/{new_course_id}")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_assignments_includes_assignment_question(self, client, setup, assignment):
        _, course_id = setup
        resp = client.get(f"/assignments-with-submissions/{course_id}")
        assert resp.status_code == 200
        assignments = resp.json()
        assert len(assignments) >= 1
        found = next((a for a in assignments if a["id"] == assignment), None)
        assert found is not None
        assert found["assignment_question"] == "Explain a linked list."
        assert "submissions" in found


# ── Get Submissions ───────────────────────────────────────────────────────────

class TestGetSubmissions:
    def test_get_submissions_empty(self, client, assignment):
        resp = client.get("/submissions", params={"assignment_id": assignment})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ── Grade Override ────────────────────────────────────────────────────────────

class TestGradeOverride:
    def test_update_submission_grade_not_found(self, client):
        resp = client.put("/update-submission-grade/99999", json={"final_grade": 85})
        assert resp.status_code == 404

    def test_api_submissions_update_not_found(self, client):
        resp = client.put("/api/submissions/99999", json={"ai_grade": 90, "status": "graded"})
        assert resp.status_code == 404

    def test_submission_details_not_found(self, client):
        resp = client.get("/submission-details/99999")
        assert resp.status_code == 404
