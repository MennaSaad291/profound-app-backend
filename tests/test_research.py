"""
test_research.py — integration tests for Research endpoints.
"""
import pytest
from conftest import register_and_login


@pytest.fixture
def user(client):
    return register_and_login(client, "researcher@uni.edu")


# ── Research Dashboard ────────────────────────────────────────────────────────

class TestResearchDashboard:
    def test_get_research_empty(self, client, user):
        resp = client.get(f"/research/{user['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert "publications" in data
        assert "projects" in data
        assert "interests" in data
        assert "literature" in data
        assert "stats" in data

    def test_research_stats_structure(self, client, user):
        resp = client.get(f"/research/{user['id']}")
        stats = resp.json()["stats"]
        assert "active_projects" in stats
        assert "total_publications" in stats
        assert "total_citations" in stats


# ── Publications ──────────────────────────────────────────────────────────────

class TestPublications:
    def test_add_publication(self, client, user):
        resp = client.post("/publications", json={
            "user_id": user["id"],
            "title": "Deep Learning in Education",
            "journal": "IEEE Transactions",
            "year": 2024,
            "citations": 15
        })
        assert resp.status_code == 200

    def test_update_publication(self, client, user):
        # First add
        client.post("/publications", json={
            "user_id": user["id"], "title": "Old Title",
            "journal": "Journal X", "year": 2023, "citations": 5
        })
        # Get the profile to find the pub id
        pubs = client.get(f"/profile/{user['id']}").json()["publications"]
        pub_id = pubs[0]["id"]

        resp = client.put(f"/publications/{pub_id}", json={
            "title": "New Title", "journal": "Journal Y",
            "year": 2024, "citations": 20
        })
        assert resp.status_code == 200

    def test_delete_publication(self, client, user):
        client.post("/publications", json={
            "user_id": user["id"], "title": "To Delete",
            "journal": "Journal Z", "year": 2022, "citations": 0
        })
        pubs = client.get(f"/profile/{user['id']}").json()["publications"]
        pub_id = pubs[-1]["id"]
        resp = client.delete(f"/publications/{pub_id}")
        assert resp.status_code == 200

    def test_delete_publication_not_found(self, client):
        resp = client.delete("/publications/99999")
        assert resp.status_code == 404


# ── Research Projects ─────────────────────────────────────────────────────────

class TestResearchProjects:
    def test_add_project(self, client, user):
        resp = client.post("/projects", json={
            "user_id": user["id"],
            "title": "AI Grading System",
            "team": "Team A",
            "year": "2025",
            "status": "ongoing",
            "deadline": "2025-12-31",
            "progress": 40
        })
        assert resp.status_code == 200

    def test_update_project(self, client, user):
        client.post("/projects", json={
            "user_id": user["id"], "title": "Project X",
            "team": "Team B", "year": "2024",
            "status": "in progress", "deadline": None, "progress": 10
        })
        research = client.get(f"/research/{user['id']}").json()
        project_id = research["projects"][0]["id"]
        resp = client.put(f"/projects/{project_id}", json={
            "title": "Updated Project", "team": "Team C",
            "year": "2025", "status": "completed",
            "deadline": "2025-06-30", "progress": 100
        })
        assert resp.status_code == 200

    def test_delete_project(self, client, user):
        client.post("/projects", json={
            "user_id": user["id"], "title": "Delete Me",
            "team": "Solo", "year": "2023",
            "status": "done", "deadline": None, "progress": 0
        })
        projects = client.get(f"/research/{user['id']}").json()["projects"]
        project_id = projects[-1]["id"]
        resp = client.delete(f"/projects/{project_id}")
        assert resp.status_code == 200

    def test_delete_project_not_found(self, client):
        resp = client.delete("/projects/99999")
        assert resp.status_code == 404


# ── Literature Papers ─────────────────────────────────────────────────────────

class TestLiteraturePapers:
    def test_add_paper(self, client, user):
        resp = client.post("/literature-papers", json={
            "user_id": user["id"],
            "title": "NLP in Higher Education",
            "read_status": "to-read",
            "citation_format": "APA"
        })
        assert resp.status_code == 200
        assert "id" in resp.json()

    def test_update_paper(self, client, user):
        paper_id = client.post("/literature-papers", json={
            "user_id": user["id"], "title": "Paper X",
            "read_status": "to-read", "citation_format": "APA"
        }).json()["id"]
        resp = client.put(f"/literature-papers/{paper_id}", json={
            "title": "Paper X Updated",
            "read_status": "read",
            "citation_format": "IEEE"
        })
        assert resp.status_code == 200

    def test_delete_paper(self, client, user):
        paper_id = client.post("/literature-papers", json={
            "user_id": user["id"], "title": "Delete Paper",
            "read_status": "to-read", "citation_format": "APA"
        }).json()["id"]
        resp = client.delete(f"/literature-papers/{paper_id}")
        assert resp.status_code == 200

    def test_delete_paper_not_found(self, client):
        resp = client.delete("/literature-papers/99999")
        assert resp.status_code == 404


# ── Interests ─────────────────────────────────────────────────────────────────

class TestInterests:
    def test_add_interest(self, client, user):
        resp = client.post("/interests", json={
            "user_id": user["id"],
            "name": "Machine Learning"
        })
        assert resp.status_code == 200

    def test_delete_interest(self, client, user):
        client.post("/interests", json={"user_id": user["id"], "name": "Deep Learning"})
        resp = client.delete(f"/interests/{user['id']}/Deep Learning")
        assert resp.status_code == 200

    def test_delete_interest_not_found(self, client, user):
        resp = client.delete(f"/interests/{user['id']}/NonExistentInterest")
        assert resp.status_code == 404
