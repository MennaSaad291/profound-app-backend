"""
test_auth.py — integration tests for Auth & User endpoints.

Covers:
  POST /register
  POST /login
  GET  /profile/{user_id}
  PUT  /profile/{user_id}
  POST /verify-password
  POST /change-password
"""
import pytest
from conftest import register_and_login


# ── Registration ──────────────────────────────────────────────────────────────

class TestRegister:
    def test_register_success(self, client):
        resp = client.post("/register", json={
            "full_name": "Ahmed Ali",
            "email": "ahmed@university.edu",
            "password": "SecurePass1"
        })
        assert resp.status_code == 200
        assert resp.json()["message"] == "Success"

    def test_register_duplicate_email(self, client):
        payload = {"full_name": "Sara", "email": "dup@university.edu", "password": "Pass123"}
        client.post("/register", json=payload)
        resp = client.post("/register", json=payload)
        assert resp.status_code == 400
        assert "already registered" in resp.json()["detail"]

    def test_register_invalid_email(self, client):
        resp = client.post("/register", json={
            "full_name": "Bad Email",
            "email": "not-an-email",
            "password": "Pass123"
        })
        assert resp.status_code == 422   # Pydantic validation


# ── Login ─────────────────────────────────────────────────────────────────────

class TestLogin:
    def test_login_success(self, client):
        client.post("/register", json={"full_name": "Omar", "email": "omar@uni.edu", "password": "Pass123"})
        resp = client.post("/login", json={"email": "omar@uni.edu", "password": "Pass123"})
        assert resp.status_code == 200
        data = resp.json()
        assert "user" in data
        assert "id" in data["user"]
        assert "name" in data["user"]

    def test_login_wrong_password(self, client):
        client.post("/register", json={"full_name": "Nour", "email": "nour@uni.edu", "password": "RealPass"})
        resp = client.post("/login", json={"email": "nour@uni.edu", "password": "WrongPass"})
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        resp = client.post("/login", json={"email": "ghost@uni.edu", "password": "Pass"})
        assert resp.status_code == 401

    def test_login_case_insensitive_email(self, client):
        client.post("/register", json={"full_name": "Case", "email": "case@uni.edu", "password": "Pass123"})
        resp = client.post("/login", json={"email": "CASE@UNI.EDU", "password": "Pass123"})
        assert resp.status_code == 200


# ── Profile ───────────────────────────────────────────────────────────────────

class TestProfile:
    def test_get_profile(self, client):
        user = register_and_login(client, "profile@uni.edu")
        resp = client.get(f"/profile/{user['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["full_name"] == "Test Professor"
        assert "metrics" in data

    def test_get_profile_not_found(self, client):
        resp = client.get("/profile/99999")
        assert resp.status_code == 404

    def test_update_profile(self, client):
        user = register_and_login(client, "update@uni.edu")
        resp = client.put(f"/profile/{user['id']}", json={
            "full_name": "Updated Name",
            "bio": "New bio text",
            "department": "Computer Science"
        })
        assert resp.status_code == 200
        # Confirm it was saved
        profile = client.get(f"/profile/{user['id']}").json()
        assert profile["full_name"] == "Updated Name"
        assert profile["department"] == "Computer Science"


# ── Password Management ───────────────────────────────────────────────────────

class TestPassword:
    def test_verify_password_correct(self, client):
        user = register_and_login(client, "verify@uni.edu")
        resp = client.post("/verify-password", json={
            "user_id": user["id"],
            "password": "TestPass123"
        })
        assert resp.status_code == 200

    def test_verify_password_wrong(self, client):
        user = register_and_login(client, "verify2@uni.edu")
        resp = client.post("/verify-password", json={
            "user_id": user["id"],
            "password": "WrongPassword"
        })
        assert resp.status_code == 401

    def test_change_password_success(self, client):
        user = register_and_login(client, "changepw@uni.edu")
        resp = client.post("/change-password", json={
            "user_id": user["id"],
            "current_password": "TestPass123",
            "new_password": "NewSecurePass456"
        })
        assert resp.status_code == 200
        # Old password should no longer work
        login = client.post("/login", json={"email": "changepw@uni.edu", "password": "TestPass123"})
        assert login.status_code == 401

    def test_change_password_wrong_current(self, client):
        user = register_and_login(client, "changepw2@uni.edu")
        resp = client.post("/change-password", json={
            "user_id": user["id"],
            "current_password": "WrongCurrent",
            "new_password": "NewPass456"
        })
        assert resp.status_code == 401

    def test_change_password_same_as_current(self, client):
        user = register_and_login(client, "changepw3@uni.edu")
        resp = client.post("/change-password", json={
            "user_id": user["id"],
            "current_password": "TestPass123",
            "new_password": "TestPass123"
        })
        assert resp.status_code == 400

    def test_change_password_too_short(self, client):
        user = register_and_login(client, "changepw4@uni.edu")
        resp = client.post("/change-password", json={
            "user_id": user["id"],
            "current_password": "TestPass123",
            "new_password": "ab"
        })
        assert resp.status_code == 400
