"""
test_exams.py — integration tests for Exam Generation endpoints.

Note: Actual AI calls are not made in tests. We verify the endpoint
contract (request/response shape) and database persistence only.
"""
import uuid
import pytest
from sqlalchemy.orm import Session
from models import ExamDB, QuestionDB
from tests.conftest import TestingSessionLocal


@pytest.fixture
def seeded_exam():
    """Insert a real exam + 3 questions using the same TestingSessionLocal
    that the TestClient uses, so the data is visible to the endpoints."""
    db = TestingSessionLocal()
    exam_id = str(uuid.uuid4())[:8]
    try:
        exam = ExamDB(id=exam_id, title="Test Exam: Data Structures")
        db.add(exam)
        for i in range(3):
            db.add(QuestionDB(
                id=str(uuid.uuid4())[:8],
                exam_id=exam_id,
                question_text=f"Q{i+1}: What is a data structure?",
                question_type="MCQ",
                options=["Array", "Linked List", "Both", "Neither"],
                blooms_level="Remember",
                difficulty="Easy",
                correct_answer="Both",
                explanation="Data structures organise data."
            ))
        db.commit()
        yield exam_id
    finally:
        db.close()


# ── Export Word ───────────────────────────────────────────────────────────────

class TestExamExport:
    def test_export_word_success(self, client, seeded_exam):
        resp = client.get(f"/exams/export-word/{seeded_exam}")
        assert resp.status_code == 200
        assert "application/vnd.openxmlformats" in resp.headers["content-type"]
        assert len(resp.content) > 0

    def test_export_word_not_found(self, client):
        resp = client.get("/exams/export-word/nonexistent")
        assert resp.status_code == 404


# ── Generate Exam (contract test — no real AI call) ───────────────────────────

class TestExamGenerate:
    def test_generate_exam_missing_topic(self, client):
        """Missing required field should return 422 validation error."""
        resp = client.post("/exams/generate", json={
            "number_of_questions": 5,
            "difficulty": "Easy",
            "blooms_level": "Remember",
            "question_type": "MCQ"
            # topic is missing
        })
        assert resp.status_code == 422

    def test_generate_exam_invalid_question_count(self, client):
        """question count must be >= 1; sending 0 should fail validation."""
        resp = client.post("/exams/generate", json={
            "topic": "Algorithms",
            "number_of_questions": 0,
            "difficulty": "Easy",
            "blooms_level": "Remember",
            "question_type": "MCQ"
        })
        assert resp.status_code == 422
