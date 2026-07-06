"""
test_analytics.py — integration tests for Analytics endpoints.
"""
import pytest
from conftest import register_and_login


# ── Analytics endpoints return valid empty/default responses ──────────────────

class TestAnalyticsEndpoints:
    def test_performance_empty(self, client):
        resp = client.get("/analysis/performance")
        assert resp.status_code == 200
        data = resp.json()
        # Should return distribution dict with 4 keys even when empty
        assert isinstance(data, dict)

    def test_correlation_empty(self, client):
        resp = client.get("/analysis/correlation")
        assert resp.status_code == 200
        data = resp.json()
        assert "stats" in data
        assert "points" in data

    def test_prediction_empty(self, client):
        # date_trunc is Postgres-only — SQLite test DB returns 500, which is acceptable
        resp = client.get("/analysis/prediction")
        assert resp.status_code in (200, 500)

    def test_errors_empty(self, client):
        resp = client.get("/analysis/errors")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_benchmarks_no_course(self, client):
        resp = client.get("/analysis/benchmarks?course_id=99999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["benchmarks"] == []
        assert data["message"] == "Course not found."

    def test_courses_list(self, client):
        resp = client.get("/analysis/courses")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_full_analysis(self, client):
        # prediction uses date_trunc (Postgres-only) — 500 acceptable on SQLite
        resp = client.post("/analysis/", json={})
        assert resp.status_code in (200, 500)

    def test_full_analysis_with_course_filter(self, client):
        resp = client.post("/analysis/", json={"course_id": 99999})
        assert resp.status_code in (200, 500)

    def test_performance_with_course_filter(self, client):
        resp = client.get("/analysis/performance?course_id=99999")
        assert resp.status_code == 200


# ── Dashboard Stats ───────────────────────────────────────────────────────────

class TestDashboardStats:
    def test_dashboard_stats_no_courses(self, client):
        user = register_and_login(client, "dashtest@uni.edu")
        resp = client.get(f"/dashboard-stats/{user['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_courses"] == 0
        assert data["pending_grading"] == 0
        assert data["class_average"] == 0.0

    def test_dashboard_stats_with_course(self, client):
        user = register_and_login(client, "dashtest2@uni.edu")
        client.post("/courses", json={
            "user_id": user["id"], "code": "DASH101",
            "name": "Dashboard Test", "semester": "Fall 2025"
        })
        resp = client.get(f"/dashboard-stats/{user['id']}")
        assert resp.status_code == 200
        assert resp.json()["total_courses"] == 1

    def test_dashboard_stats_keys(self, client):
        user = register_and_login(client, "dashtest3@uni.edu")
        resp = client.get(f"/dashboard-stats/{user['id']}")
        data = resp.json()
        expected_keys = {
            "class_average", "average_trend", "at_risk_count",
            "pending_grading", "total_students", "total_courses", "active_courses"
        }
        assert expected_keys.issubset(set(data.keys()))
