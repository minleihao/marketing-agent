from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


SRC_DIR = Path(__file__).parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture
def webapp_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "nova_data"
    monkeypatch.setenv("NOVARED_DATA_DIR", str(data_dir))
    monkeypatch.setenv("NOVARED_ENFORCE_DEFAULT_ADMIN_PASSWORD_CHANGE", "0")
    if "webapp" in sys.modules:
        del sys.modules["webapp"]
    module = importlib.import_module("webapp")
    importlib.reload(module)
    return module


def _fetch_csrf(client: TestClient) -> str:
    res = client.get("/api/csrf")
    assert res.status_code == 200, res.text
    token = res.json().get("csrf_token", "")
    assert token
    return token


def _register(client: TestClient, username: str, password: str = "password123") -> dict[str, str]:
    res = client.post(
        "/register",
        json={
            "username": username,
            "password": password,
            "join_group_ids": [],
        },
    )
    assert res.status_code == 200, res.text
    return {"X-CSRF-Token": _fetch_csrf(client)}


def _login_admin(client: TestClient) -> dict[str, str]:
    res = client.post("/login", json={"username": "admin", "password": "admin123456"})
    assert res.status_code == 200, res.text
    return {"X-CSRF-Token": _fetch_csrf(client)}


def test_csrf_rejects_mutation_without_token(webapp_module):
    with TestClient(webapp_module.app) as client:
        _login_admin(client)
        res = client.post("/api/conversations", json={"task_mode": "chat"})
        assert res.status_code == 403
        assert "Invalid CSRF token" in res.text


def test_csrf_allows_mutation_with_token(webapp_module):
    with TestClient(webapp_module.app) as client:
        headers = _login_admin(client)
        res = client.post("/api/conversations", json={"task_mode": "chat"}, headers=headers)
        assert res.status_code == 200, res.text
        payload = res.json()
        assert payload["task_mode"] == "chat"
        assert payload["thinking_depth"] == "low"
        assert payload["id"] > 0


def test_create_conversation_uses_english_default_title_when_ui_language_en(webapp_module):
    with TestClient(webapp_module.app) as client:
        headers = _register(client, "en_default_user")
        res = client.post(
            "/api/conversations",
            json={"task_mode": "chat", "ui_language": "en"},
            headers=headers,
        )
        assert res.status_code == 200, res.text
        payload = res.json()
        assert payload["title"] == "New Chat"


def test_conversation_thinking_depth_create_and_update(webapp_module):
    with TestClient(webapp_module.app) as client:
        headers = _register(client, "depth_user")
        create_res = client.post(
            "/api/conversations",
            json={"task_mode": "chat", "thinking_depth": "medium"},
            headers=headers,
        )
        assert create_res.status_code == 200, create_res.text
        created = create_res.json()
        assert created["thinking_depth"] == "medium"

        conv_id = created["id"]
        patch_res = client.patch(
            f"/api/conversations/{conv_id}/thinking-depth",
            json={"thinking_depth": "high"},
            headers=headers,
        )
        assert patch_res.status_code == 200, patch_res.text
        assert patch_res.json()["thinking_depth"] == "high"

        list_res = client.get("/api/conversations")
        assert list_res.status_code == 200, list_res.text
        rows = list_res.json()
        row = next((item for item in rows if item["id"] == conv_id), None)
        assert row is not None
        assert row["thinking_depth"] == "high"


def test_auto_renames_english_default_title_on_first_message(webapp_module):
    with TestClient(webapp_module.app) as client:
        headers = _register(client, "rename_en_user")
        conv_res = client.post(
            "/api/conversations",
            json={"task_mode": "chat", "title": "New Chat"},
            headers=headers,
        )
        assert conv_res.status_code == 200, conv_res.text
        conversation_id = conv_res.json()["id"]

        webapp_module.invoke = lambda _payload: {"result": "assistant reply"}
        msg_res = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "Launch plan for Q2 campaign"},
            headers=headers,
        )
        assert msg_res.status_code == 200, msg_res.text

        list_res = client.get("/api/conversations")
        assert list_res.status_code == 200, list_res.text
        rows = list_res.json()
        conversation = next((row for row in rows if row["id"] == conversation_id), None)
        assert conversation is not None
        assert conversation["title"] == "Launch plan for Q2 campaign"[:30]


def test_send_message_passes_thinking_depth_to_runtime(webapp_module):
    captured = {}

    def fake_invoke(payload):
        captured["payload"] = payload
        return {"result": "assistant reply"}

    webapp_module.invoke = fake_invoke

    with TestClient(webapp_module.app) as client:
        headers = _register(client, "depth_runtime_user")
        conv_res = client.post(
            "/api/conversations",
            json={"task_mode": "chat", "thinking_depth": "high"},
            headers=headers,
        )
        assert conv_res.status_code == 200, conv_res.text
        conversation_id = conv_res.json()["id"]

        msg_res = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "hello"},
            headers=headers,
        )
        assert msg_res.status_code == 200, msg_res.text
        assert captured["payload"]["tool_args"]["thinking_depth"] == "high"


def test_cannot_bind_private_kb_owned_by_other_user(webapp_module):
    with TestClient(webapp_module.app) as owner_client, TestClient(webapp_module.app) as member_client:
        owner_headers = _register(owner_client, "owner_user")
        kb_res = owner_client.post(
            "/api/kb",
            json={
                "kb_key": "owner_private_kb",
                "kb_name": "Owner Private KB",
                "visibility": "private",
            },
            headers=owner_headers,
        )
        assert kb_res.status_code == 200, kb_res.text
        kb_payload = kb_res.json()

        member_headers = _register(member_client, "member_user")
        conv_res = member_client.post(
            "/api/conversations",
            json={"task_mode": "chat"},
            headers=member_headers,
        )
        assert conv_res.status_code == 200, conv_res.text
        conv_id = conv_res.json()["id"]

        attach_res = member_client.patch(
            f"/api/conversations/{conv_id}/kb",
            json={"kb_key": kb_payload["kb_key"], "kb_version": kb_payload["version"]},
            headers=member_headers,
        )
        assert attach_res.status_code == 403
        assert "No access to this Knowledge Base version" in attach_res.text


def test_experiment_lifecycle_api(webapp_module):
    with TestClient(webapp_module.app) as client:
        headers = _register(client, "exp_user")
        conv_res = client.post(
            "/api/conversations",
            json={"task_mode": "marketing"},
            headers=headers,
        )
        assert conv_res.status_code == 200, conv_res.text
        conversation_id = conv_res.json()["id"]

        create_res = client.post(
            "/api/experiments",
            json={
                "title": "Hook A/B Test",
                "hypothesis": "Outcome-first hook should improve CTR.",
                "conversation_id": conversation_id,
                "traffic_allocation": {"A": 50, "B": 50},
            },
            headers=headers,
        )
        assert create_res.status_code == 200, create_res.text
        experiment_id = create_res.json()["id"]
        assert experiment_id > 0

        variant_res = client.post(
            f"/api/experiments/{experiment_id}/variants",
            json={"variant_key": "A", "content": "Version A copy"},
            headers=headers,
        )
        assert variant_res.status_code == 200, variant_res.text
        assert variant_res.json()["ok"] is True

        detail_res = client.get(f"/api/experiments/{experiment_id}")
        assert detail_res.status_code == 200, detail_res.text
        detail = detail_res.json()
        assert detail["title"] == "Hook A/B Test"
        assert detail["traffic_allocation"] == {"A": 50, "B": 50}
        assert len(detail["variants"]) == 1
        assert detail["variants"][0]["variant_key"] == "a"

        meta_res = client.patch(
            f"/api/experiments/{experiment_id}",
            json={
                "title": "Hook A/B Test v2",
                "hypothesis": "Problem-first hook may outperform outcome-first for this audience.",
                "traffic_allocation": {"A": 40, "B": 60},
            },
            headers=headers,
        )
        assert meta_res.status_code == 200, meta_res.text
        assert meta_res.json()["ok"] is True

        status_res = client.patch(
            f"/api/experiments/{experiment_id}/status",
            json={"status": "running", "result": {"ctr_lift": 0.12}},
            headers=headers,
        )
        assert status_res.status_code == 200, status_res.text
        assert status_res.json()["ok"] is True

        detail_res_2 = client.get(f"/api/experiments/{experiment_id}")
        assert detail_res_2.status_code == 200, detail_res_2.text
        detail_2 = detail_res_2.json()
        assert detail_2["title"] == "Hook A/B Test v2"
        assert detail_2["traffic_allocation"] == {"A": 40, "B": 60}
        assert detail_2["status"] == "running"
        assert detail_2["result"] == {"ctr_lift": 0.12}

        delete_res = client.delete(f"/api/experiments/{experiment_id}", headers=headers)
        assert delete_res.status_code == 200, delete_res.text
        assert delete_res.json()["ok"] is True

        not_found_res = client.get(f"/api/experiments/{experiment_id}")
        assert not_found_res.status_code == 404
