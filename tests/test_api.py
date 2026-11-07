"""
Application REST API Tests.
Verifies all companion application endpoints, response schemas, and public access in local dev mode.
"""

from datetime import datetime, timezone, timedelta


def test_health_endpoint(client):
    """GET /health returns 200 OK and healthy database status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert data["database"] == "healthy"


def test_swagger_docs_accessible_without_auth(client):
    """FastAPI Swagger UI /docs is accessible without authentication in local dev."""
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()


def test_tasks_api_crud(client):
    """Test full CRUD via REST endpoints for tasks."""
    # Create
    create_res = client.post("/api/v1/tasks", json={
        "title": "Buy study planner",
        "description": "Stationery store"
    })
    assert create_res.status_code == 201
    task_data = create_res.json()
    task_id = task_data["id"]
    assert task_data["title"] == "Buy study planner"
    assert task_data["status"] == "pending"

    # List
    list_res = client.get("/api/v1/tasks")
    assert list_res.status_code == 200
    assert any(t["id"] == task_id for t in list_res.json())

    # Update
    patch_res = client.patch(f"/api/v1/tasks/{task_id}", json={
        "status": "completed"
    })
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "completed"

    # Delete
    del_res = client.delete(f"/api/v1/tasks/{task_id}")
    assert del_res.status_code == 204


def test_reminders_api(client):
    """Test reminder creation and acknowledgement via REST."""
    sch_time = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    create_res = client.post("/api/v1/reminders", json={
        "message": "Drink water",
        "scheduled_time": sch_time
    })
    assert create_res.status_code == 201
    rem_id = create_res.json()["id"]

    # Acknowledge
    ack_res = client.post(f"/api/v1/reminders/{rem_id}/acknowledge")
    assert ack_res.status_code == 200
    assert ack_res.json()["status"] == "acknowledged"


def test_preferences_api(client):
    """Test getting and updating user preferences via REST."""
    get_res = client.get("/api/v1/preferences")
    assert get_res.status_code == 200
    assert "cooldown_minutes" in get_res.json()

    put_res = client.put("/api/v1/preferences", json={
        "cooldown_minutes": 45,
        "morning_time": "07:30"
    })
    assert put_res.status_code == 200
    assert put_res.json()["cooldown_minutes"] == 45
    assert put_res.json()["morning_time"] == "07:30"


def test_conversations_api(client):
    """Test sending user message and retrieving session."""
    msg_res = client.post("/api/v1/conversations/message", json={
        "device_id": "dove-esp32-01",
        "message": "Hello from companion app test!"
    })
    assert msg_res.status_code == 200
    data = msg_res.json()
    assert "reply" in data
    session_id = data["session_id"]

    # Get session details
    sess_res = client.get(f"/api/v1/conversations/sessions/{session_id}")
    assert sess_res.status_code == 200
    assert len(sess_res.json()["messages"]) >= 2

    # Mark false trigger
    ft_res = client.post(f"/api/v1/conversations/sessions/{session_id}/false-trigger", json={"is_false_trigger": True})
    assert ft_res.status_code == 200


def test_user_statistics_api(client):
    """Test GET /api/v1/stats returns aggregated metrics."""
    res = client.get("/api/v1/stats")
    assert res.status_code == 200
    data = res.json()
    assert "conversations" in data
    assert "tasks" in data
    assert "reminders" in data
    assert "routines" in data
    assert "mood_distribution" in data
