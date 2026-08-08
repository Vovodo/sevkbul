from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_uptimerobot_head_requests():
    endpoints = ["/", "/ping", "/healthz", "/api/health"]
    for path in endpoints:
        res = client.head(path)
        assert res.status_code == 200, f"HEAD failed on {path}"
        assert res.headers.get("X-Uptime-Robot") == "OK"
        assert res.content == b""

def test_uptimerobot_get_requests():
    endpoints = ["/", "/ping", "/healthz", "/api/health"]
    for path in endpoints:
        res = client.get(path)
        assert res.status_code == 200, f"GET failed on {path}"
        assert res.headers.get("X-Uptime-Robot") == "OK"
        data = res.json()
        assert data["status"] == "ok"
        assert "uptimerobot" in data
