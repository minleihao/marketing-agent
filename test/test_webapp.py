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
    monkeypatch.delenv("NOVARED_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
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


def _current_user_id(client: TestClient) -> int:
    res = client.get("/api/me")
    assert res.status_code == 200, res.text
    return int(res.json()["id"])


def test_csrf_rejects_mutation_without_token(webapp_module):
    with TestClient(webapp_module.app) as client:
        _login_admin(client)
        res = client.post("/api/conversations", json={"task_mode": "chat"})
        assert res.status_code == 403
        assert "Invalid CSRF token" in res.text


def test_translate_qmark_to_postgres_keeps_quoted_question_marks(webapp_module):
    sql = "SELECT '?' AS literal, \"?\" AS ident FROM users WHERE username = ? AND id = ?"
    converted = webapp_module._translate_qmark_to_postgres(sql)
    assert "literal" in converted
    assert "WHERE username = %s AND id = %s" in converted
    assert "'?'" in converted
    assert '"?"' in converted


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
            json={"content": "hello", "channels": ["email", "linkedin"]},
            headers=headers,
        )
        assert msg_res.status_code == 200, msg_res.text
        assert captured["payload"]["tool_args"]["thinking_depth"] == "high"
        assert captured["payload"]["tool_args"]["channels"] == ["email", "linkedin"]
        assert captured["payload"]["tool_args"]["channel"] == "email"


def test_stream_message_endpoint_returns_sse(webapp_module):
    webapp_module.invoke = lambda _payload: {"result": "streamed assistant reply"}

    def fake_stream(payload, on_delta=None):
        if callable(on_delta):
            on_delta("streamed ")
            on_delta("assistant ")
            on_delta("reply")
        return {"result": "streamed assistant reply"}

    webapp_module.invoke_stream = fake_stream

    with TestClient(webapp_module.app) as client:
        headers = _register(client, "stream_user")
        conv_res = client.post(
            "/api/conversations",
            json={"task_mode": "chat"},
            headers=headers,
        )
        assert conv_res.status_code == 200, conv_res.text
        conversation_id = conv_res.json()["id"]

        with client.stream(
            "POST",
            f"/api/conversations/{conversation_id}/messages/stream",
            json={"content": "hello"},
            headers=headers,
        ) as res:
            assert res.status_code == 200, res.text
            body = "".join(res.iter_text())

        assert "event: delta" in body
        assert "streamed assistant reply" in body


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


def test_registered_user_auto_joins_general_group(webapp_module):
    with TestClient(webapp_module.app) as client:
        _register(client, "general_group_user")
        mine_res = client.get("/api/groups/mine")
        assert mine_res.status_code == 200, mine_res.text
        general_group = next((item for item in mine_res.json() if item["name"] == "General Group"), None)
        assert general_group is not None
        assert general_group["group_type"] == "company"
        assert general_group["role"] == "member"
        assert general_group["status"] == "approved"

        public_res = client.get("/api/public/groups")
        assert public_res.status_code == 200, public_res.text
        assert all(item["name"] != "General Group" for item in public_res.json())


def test_admin_manages_general_group_and_shared_default_kbs(webapp_module):
    with TestClient(webapp_module.app) as admin_client, TestClient(webapp_module.app) as member_client:
        _login_admin(admin_client)
        _register(member_client, "default_kb_user")

        admin_groups_res = admin_client.get("/api/groups/mine")
        assert admin_groups_res.status_code == 200, admin_groups_res.text
        general_group = next((item for item in admin_groups_res.json() if item["name"] == "General Group"), None)
        assert general_group is not None
        assert general_group["role"] == "admin"

        kb_res = member_client.get("/api/kb/list")
        assert kb_res.status_code == 200, kb_res.text
        kb_rows = {item["kb_key"]: item for item in kb_res.json()}
        assert "default_brand_guidelines" in kb_rows
        assert "default_campaign_playbook" in kb_rows
        assert kb_rows["default_brand_guidelines"]["owner_username"] == "admin"
        assert kb_rows["default_brand_guidelines"]["visibility"] == "company"
        assert kb_rows["default_brand_guidelines"]["share_group_name"] == "General Group"
        assert kb_rows["default_campaign_playbook"]["owner_username"] == "admin"
        assert kb_rows["default_campaign_playbook"]["visibility"] == "company"
        assert kb_rows["default_campaign_playbook"]["share_group_name"] == "General Group"


def test_general_group_sample_chats_are_visible_to_new_user(webapp_module):
    with TestClient(webapp_module.app) as client:
        _register(client, "general_group_sample_user")

        conversations_res = client.get("/api/conversations")
        assert conversations_res.status_code == 200, conversations_res.text
        rows = conversations_res.json()
        by_title = {item["title"]: item for item in rows}

        marketing_chat = by_title.get("Sample Marketing Chat")
        random_chat = by_title.get("Sample General Chat")
        assert marketing_chat is not None
        assert random_chat is not None
        assert marketing_chat["owner_username"] == "admin"
        assert marketing_chat["visibility"] == "company"
        assert marketing_chat["share_group_name"] == "General Group"
        assert marketing_chat["task_mode"] == "marketing"
        assert random_chat["task_mode"] == "chat"

        messages_res = client.get(f"/api/conversations/{marketing_chat['id']}/messages")
        assert messages_res.status_code == 200, messages_res.text
        messages = messages_res.json()
        assert len(messages) >= 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert "Channel Plan" in messages[1]["content"]


def test_member_can_leave_and_rejoin_general_group(webapp_module):
    with TestClient(webapp_module.app) as client:
        headers = _register(client, "general_leave_user")
        mine_res = client.get("/api/groups/mine")
        assert mine_res.status_code == 200, mine_res.text
        general_group = next((item for item in mine_res.json() if item["name"] == "General Group"), None)
        assert general_group is not None
        group_id = general_group["id"]

        conversations_before_leave = client.get("/api/conversations")
        assert conversations_before_leave.status_code == 200, conversations_before_leave.text
        titles_before_leave = {item["title"] for item in conversations_before_leave.json()}
        assert "Sample Marketing Chat" in titles_before_leave
        assert "Sample General Chat" in titles_before_leave

        leave_res = client.post(f"/api/groups/{group_id}/leave", headers=headers)
        assert leave_res.status_code == 200, leave_res.text

        mine_after_leave = client.get("/api/groups/mine")
        assert mine_after_leave.status_code == 200, mine_after_leave.text
        assert all(item["id"] != group_id for item in mine_after_leave.json())

        kb_after_leave = client.get("/api/kb/list")
        assert kb_after_leave.status_code == 200, kb_after_leave.text
        kb_keys_after_leave = {item["kb_key"] for item in kb_after_leave.json()}
        assert "default_brand_guidelines" not in kb_keys_after_leave
        assert "default_campaign_playbook" not in kb_keys_after_leave

        conversations_after_leave = client.get("/api/conversations")
        assert conversations_after_leave.status_code == 200, conversations_after_leave.text
        titles_after_leave = {item["title"] for item in conversations_after_leave.json()}
        assert "Sample Marketing Chat" not in titles_after_leave
        assert "Sample General Chat" not in titles_after_leave

        rejoin_res = client.post(f"/api/groups/{group_id}/join", headers=headers)
        assert rejoin_res.status_code == 200, rejoin_res.text
        assert rejoin_res.json()["status"] == "approved"

        kb_after_rejoin = client.get("/api/kb/list")
        assert kb_after_rejoin.status_code == 200, kb_after_rejoin.text
        kb_keys_after_rejoin = {item["kb_key"] for item in kb_after_rejoin.json()}
        assert "default_brand_guidelines" in kb_keys_after_rejoin
        assert "default_campaign_playbook" in kb_keys_after_rejoin

        conversations_after_rejoin = client.get("/api/conversations")
        assert conversations_after_rejoin.status_code == 200, conversations_after_rejoin.text
        titles_after_rejoin = {item["title"] for item in conversations_after_rejoin.json()}
        assert "Sample Marketing Chat" in titles_after_rejoin
        assert "Sample General Chat" in titles_after_rejoin


def test_general_group_cannot_be_deleted_or_transferred(webapp_module):
    with TestClient(webapp_module.app) as admin_client:
        headers = _login_admin(admin_client)
        mine_res = admin_client.get("/api/groups/mine")
        assert mine_res.status_code == 200, mine_res.text
        general_group = next((item for item in mine_res.json() if item["name"] == "General Group"), None)
        assert general_group is not None
        group_id = general_group["id"]

        delete_res = admin_client.delete(f"/api/groups/{group_id}", headers=headers)
        assert delete_res.status_code == 400, delete_res.text
        assert "General Group is protected" in delete_res.text

        transfer_res = admin_client.post(
            f"/api/groups/{group_id}/transfer-admin",
            json={"new_admin_user_id": _current_user_id(admin_client)},
            headers=headers,
        )
        assert transfer_res.status_code == 400, transfer_res.text
        assert "General Group admin is fixed to admin" in transfer_res.text


def test_create_group_rejects_blank_name_after_trim(webapp_module):
    with TestClient(webapp_module.app) as client:
        headers = _register(client, "group_blank_name_user")
        res = client.post(
            "/api/groups",
            json={"name": "   ", "group_type": "task"},
            headers=headers,
        )
        assert res.status_code == 400, res.text
        assert "Group name must be at least 2 characters" in res.text


def test_group_member_can_leave_group(webapp_module):
    with TestClient(webapp_module.app) as owner_client, TestClient(webapp_module.app) as member_client:
        owner_headers = _register(owner_client, "group_owner_user")
        create_res = owner_client.post(
            "/api/groups",
            json={"name": "Growth Team", "group_type": "task"},
            headers=owner_headers,
        )
        assert create_res.status_code == 200, create_res.text
        group_id = create_res.json()["id"]

        member_headers = _register(member_client, "group_member_user")
        member_profile = member_client.get("/api/me")
        assert member_profile.status_code == 200, member_profile.text
        member_user_id = member_profile.json()["id"]

        join_res = member_client.post(f"/api/groups/{group_id}/join", headers=member_headers)
        assert join_res.status_code == 200, join_res.text
        assert join_res.json()["status"] == "pending"

        approve_res = owner_client.post(
            f"/api/groups/{group_id}/requests/{member_user_id}/approve",
            headers=owner_headers,
        )
        assert approve_res.status_code == 200, approve_res.text

        leave_res = member_client.post(f"/api/groups/{group_id}/leave", headers=member_headers)
        assert leave_res.status_code == 200, leave_res.text
        assert leave_res.json()["ok"] is True

        mine_res = member_client.get("/api/groups/mine")
        assert mine_res.status_code == 200, mine_res.text
        assert all(item["id"] != group_id for item in mine_res.json())


def test_group_admin_can_invite_user_and_user_can_accept_invite(webapp_module):
    with TestClient(webapp_module.app) as owner_client, TestClient(webapp_module.app) as invited_client:
        owner_headers = _register(owner_client, "invite_owner_user")
        create_res = owner_client.post(
            "/api/groups",
            json={"name": "Invite Accept Group", "group_type": "task"},
            headers=owner_headers,
        )
        assert create_res.status_code == 200, create_res.text
        group_id = create_res.json()["id"]

        invited_headers = _register(invited_client, "invite_target_user")
        invite_res = owner_client.post(
            f"/api/groups/{group_id}/invite",
            json={"username": "invite_target_user"},
            headers=owner_headers,
        )
        assert invite_res.status_code == 200, invite_res.text
        assert invite_res.json()["status"] == "invited"

        members_before_accept = owner_client.get(f"/api/groups/{group_id}/members")
        assert members_before_accept.status_code == 200, members_before_accept.text
        assert all(item["username"] != "invite_target_user" for item in members_before_accept.json())

        requests_before_accept = owner_client.get(f"/api/groups/{group_id}/requests")
        assert requests_before_accept.status_code == 200, requests_before_accept.text
        assert all(item["username"] != "invite_target_user" for item in requests_before_accept.json())

        approve_invite_res = owner_client.post(
            f"/api/groups/{group_id}/requests/{_current_user_id(invited_client)}/approve",
            headers=owner_headers,
        )
        assert approve_invite_res.status_code == 400, approve_invite_res.text
        assert "Only pending join requests can be approved" in approve_invite_res.text

        invites_res = invited_client.get("/api/groups/invitations")
        assert invites_res.status_code == 200, invites_res.text
        invites = invites_res.json()
        assert any(item["group_id"] == group_id for item in invites)

        accept_res = invited_client.post(
            f"/api/groups/{group_id}/invitations/accept",
            headers=invited_headers,
        )
        assert accept_res.status_code == 200, accept_res.text
        assert accept_res.json()["status"] == "approved"

        mine_res = invited_client.get("/api/groups/mine")
        assert mine_res.status_code == 200, mine_res.text
        group_row = next((item for item in mine_res.json() if item["id"] == group_id), None)
        assert group_row is not None
        assert group_row["role"] == "member"
        assert group_row["status"] == "approved"

        members_res = owner_client.get(f"/api/groups/{group_id}/members")
        assert members_res.status_code == 200, members_res.text
        usernames = {item["username"] for item in members_res.json()}
        assert "invite_owner_user" in usernames
        assert "invite_target_user" in usernames


def test_group_invite_can_be_rejected(webapp_module):
    with TestClient(webapp_module.app) as owner_client, TestClient(webapp_module.app) as invited_client:
        owner_headers = _register(owner_client, "invite_reject_owner")
        create_res = owner_client.post(
            "/api/groups",
            json={"name": "Invite Reject Group", "group_type": "company"},
            headers=owner_headers,
        )
        assert create_res.status_code == 200, create_res.text
        group_id = create_res.json()["id"]

        invited_headers = _register(invited_client, "invite_reject_target")
        invite_res = owner_client.post(
            f"/api/groups/{group_id}/invite",
            json={"username": "invite_reject_target"},
            headers=owner_headers,
        )
        assert invite_res.status_code == 200, invite_res.text

        requests_res = owner_client.get(f"/api/groups/{group_id}/requests")
        assert requests_res.status_code == 200, requests_res.text
        assert all(item["username"] != "invite_reject_target" for item in requests_res.json())

        reject_res = invited_client.post(
            f"/api/groups/{group_id}/invitations/reject",
            headers=invited_headers,
        )
        assert reject_res.status_code == 200, reject_res.text

        invites_res = invited_client.get("/api/groups/invitations")
        assert invites_res.status_code == 200, invites_res.text
        assert all(item["group_id"] != group_id for item in invites_res.json())

        members_res = owner_client.get(f"/api/groups/{group_id}/members")
        assert members_res.status_code == 200, members_res.text
        assert all(item["username"] != "invite_reject_target" for item in members_res.json())


def test_only_group_admin_can_invite_users(webapp_module):
    with TestClient(webapp_module.app) as owner_client, TestClient(webapp_module.app) as member_client, TestClient(webapp_module.app) as target_client:
        owner_headers = _register(owner_client, "invite_perm_owner")
        create_res = owner_client.post(
            "/api/groups",
            json={"name": "Invite Permission Group", "group_type": "task"},
            headers=owner_headers,
        )
        assert create_res.status_code == 200, create_res.text
        group_id = create_res.json()["id"]

        member_headers = _register(member_client, "invite_perm_member")
        _register(target_client, "invite_perm_target")
        member_id = _current_user_id(member_client)

        join_res = member_client.post(f"/api/groups/{group_id}/join", headers=member_headers)
        assert join_res.status_code == 200, join_res.text

        approve_res = owner_client.post(
            f"/api/groups/{group_id}/requests/{member_id}/approve",
            headers=owner_headers,
        )
        assert approve_res.status_code == 200, approve_res.text

        invite_res = member_client.post(
            f"/api/groups/{group_id}/invite",
            json={"username": "invite_perm_target"},
            headers=member_headers,
        )
        assert invite_res.status_code == 403, invite_res.text
        assert "Admin only for this group" in invite_res.text


def test_transfer_admin_updates_group_roles_and_permissions(webapp_module):
    with TestClient(webapp_module.app) as owner_client, TestClient(webapp_module.app) as member_client, TestClient(webapp_module.app) as target_client:
        owner_headers = _register(owner_client, "transfer_owner_user")
        create_res = owner_client.post(
            "/api/groups",
            json={"name": "Transfer Admin Group", "group_type": "task"},
            headers=owner_headers,
        )
        assert create_res.status_code == 200, create_res.text
        group_id = create_res.json()["id"]

        member_headers = _register(member_client, "transfer_member_user")
        _register(target_client, "transfer_target_user")
        member_id = _current_user_id(member_client)

        join_res = member_client.post(f"/api/groups/{group_id}/join", headers=member_headers)
        assert join_res.status_code == 200, join_res.text
        approve_res = owner_client.post(
            f"/api/groups/{group_id}/requests/{member_id}/approve",
            headers=owner_headers,
        )
        assert approve_res.status_code == 200, approve_res.text

        transfer_res = owner_client.post(
            f"/api/groups/{group_id}/transfer-admin",
            json={"new_admin_user_id": member_id},
            headers=owner_headers,
        )
        assert transfer_res.status_code == 200, transfer_res.text
        assert transfer_res.json()["new_admin_user_id"] == member_id

        members_res = owner_client.get(f"/api/groups/{group_id}/members")
        assert members_res.status_code == 200, members_res.text
        roles = {item["username"]: item["role"] for item in members_res.json()}
        assert roles["transfer_owner_user"] == "member"
        assert roles["transfer_member_user"] == "admin"

        old_admin_invite = owner_client.post(
            f"/api/groups/{group_id}/invite",
            json={"username": "transfer_target_user"},
            headers=owner_headers,
        )
        assert old_admin_invite.status_code == 403, old_admin_invite.text

        new_admin_invite = member_client.post(
            f"/api/groups/{group_id}/invite",
            json={"username": "transfer_target_user"},
            headers=member_headers,
        )
        assert new_admin_invite.status_code == 200, new_admin_invite.text
        assert new_admin_invite.json()["status"] == "invited"


def test_group_members_are_scoped_per_group(webapp_module):
    with TestClient(webapp_module.app) as owner_client, TestClient(webapp_module.app) as alpha_client, TestClient(webapp_module.app) as beta_client:
        owner_headers = _register(owner_client, "scoped_group_owner")
        alpha_headers = _register(alpha_client, "scoped_alpha_user")
        beta_headers = _register(beta_client, "scoped_beta_user")
        alpha_id = _current_user_id(alpha_client)
        beta_id = _current_user_id(beta_client)

        group_a_res = owner_client.post(
            "/api/groups",
            json={"name": "Scoped Alpha Group", "group_type": "task"},
            headers=owner_headers,
        )
        assert group_a_res.status_code == 200, group_a_res.text
        group_a_id = group_a_res.json()["id"]

        group_b_res = owner_client.post(
            "/api/groups",
            json={"name": "Scoped Beta Group", "group_type": "company"},
            headers=owner_headers,
        )
        assert group_b_res.status_code == 200, group_b_res.text
        group_b_id = group_b_res.json()["id"]

        assert alpha_client.post(f"/api/groups/{group_a_id}/join", headers=alpha_headers).status_code == 200
        assert beta_client.post(f"/api/groups/{group_b_id}/join", headers=beta_headers).status_code == 200

        assert owner_client.post(
            f"/api/groups/{group_a_id}/requests/{alpha_id}/approve",
            headers=owner_headers,
        ).status_code == 200
        assert owner_client.post(
            f"/api/groups/{group_b_id}/requests/{beta_id}/approve",
            headers=owner_headers,
        ).status_code == 200

        members_a_res = owner_client.get(f"/api/groups/{group_a_id}/members")
        members_b_res = owner_client.get(f"/api/groups/{group_b_id}/members")
        assert members_a_res.status_code == 200, members_a_res.text
        assert members_b_res.status_code == 200, members_b_res.text

        usernames_a = {item["username"] for item in members_a_res.json()}
        usernames_b = {item["username"] for item in members_b_res.json()}
        assert "scoped_alpha_user" in usernames_a
        assert "scoped_beta_user" not in usernames_a
        assert "scoped_beta_user" in usernames_b
        assert "scoped_alpha_user" not in usernames_b


def test_group_admin_can_remove_member(webapp_module):
    with TestClient(webapp_module.app) as owner_client, TestClient(webapp_module.app) as member_client:
        owner_headers = _register(owner_client, "remove_member_owner")
        member_headers = _register(member_client, "remove_member_target")

        create_res = owner_client.post(
            "/api/groups",
            json={"name": "Remove Member Group", "group_type": "task"},
            headers=owner_headers,
        )
        assert create_res.status_code == 200, create_res.text
        group_id = create_res.json()["id"]

        member_id = _current_user_id(member_client)
        join_res = member_client.post(f"/api/groups/{group_id}/join", headers=member_headers)
        assert join_res.status_code == 200, join_res.text

        approve_res = owner_client.post(
            f"/api/groups/{group_id}/requests/{member_id}/approve",
            headers=owner_headers,
        )
        assert approve_res.status_code == 200, approve_res.text

        remove_res = owner_client.delete(
            f"/api/groups/{group_id}/members/{member_id}",
            headers=owner_headers,
        )
        assert remove_res.status_code == 200, remove_res.text
        assert remove_res.json()["removed_user_id"] == member_id

        members_res = owner_client.get(f"/api/groups/{group_id}/members")
        assert members_res.status_code == 200, members_res.text
        assert all(item["user_id"] != member_id for item in members_res.json())

        member_groups_res = member_client.get("/api/groups/mine")
        assert member_groups_res.status_code == 200, member_groups_res.text
        assert all(item["id"] != group_id for item in member_groups_res.json())


def test_system_admin_can_remove_general_group_member_and_revoke_shared_defaults(webapp_module):
    with TestClient(webapp_module.app) as admin_client, TestClient(webapp_module.app) as member_client:
        admin_headers = _login_admin(admin_client)
        _register(member_client, "general_group_removed_user")
        member_id = _current_user_id(member_client)

        admin_groups_res = admin_client.get("/api/groups")
        assert admin_groups_res.status_code == 200, admin_groups_res.text
        general_group = next((item for item in admin_groups_res.json() if item["name"] == "General Group"), None)
        assert general_group is not None
        group_id = general_group["id"]

        remove_res = admin_client.delete(
            f"/api/groups/{group_id}/members/{member_id}",
            headers=admin_headers,
        )
        assert remove_res.status_code == 200, remove_res.text

        member_groups_res = member_client.get("/api/groups/mine")
        assert member_groups_res.status_code == 200, member_groups_res.text
        assert all(item["id"] != group_id for item in member_groups_res.json())

        member_kb_res = member_client.get("/api/kb/list")
        assert member_kb_res.status_code == 200, member_kb_res.text
        member_kb_keys = {item["kb_key"] for item in member_kb_res.json()}
        assert "default_brand_guidelines" not in member_kb_keys
        assert "default_campaign_playbook" not in member_kb_keys

        member_conv_res = member_client.get("/api/conversations")
        assert member_conv_res.status_code == 200, member_conv_res.text
        member_conv_titles = {item["title"] for item in member_conv_res.json()}
        assert "Sample Marketing Chat" not in member_conv_titles
        assert "Sample General Chat" not in member_conv_titles


def test_last_group_admin_cannot_leave_group(webapp_module):
    with TestClient(webapp_module.app) as client:
        headers = _register(client, "solo_group_admin_user")
        create_res = client.post(
            "/api/groups",
            json={"name": "Solo Admin Group", "group_type": "company"},
            headers=headers,
        )
        assert create_res.status_code == 200, create_res.text
        group_id = create_res.json()["id"]

        leave_res = client.post(f"/api/groups/{group_id}/leave", headers=headers)
        assert leave_res.status_code == 400, leave_res.text
        assert "last admin" in leave_res.text


def test_group_admin_can_delete_group(webapp_module):
    with TestClient(webapp_module.app) as client:
        headers = _register(client, "delete_group_owner")
        create_res = client.post(
            "/api/groups",
            json={"name": "Delete By Owner", "group_type": "task"},
            headers=headers,
        )
        assert create_res.status_code == 200, create_res.text
        group_id = create_res.json()["id"]

        delete_res = client.delete(f"/api/groups/{group_id}", headers=headers)
        assert delete_res.status_code == 200, delete_res.text
        payload = delete_res.json()
        assert payload["ok"] is True
        assert payload["group_id"] == group_id

        groups_res = client.get("/api/groups")
        assert groups_res.status_code == 200, groups_res.text
        assert all(item["id"] != group_id for item in groups_res.json())


def test_system_admin_can_delete_any_group(webapp_module):
    with TestClient(webapp_module.app) as owner_client, TestClient(webapp_module.app) as admin_client:
        owner_headers = _register(owner_client, "group_owner_for_admin_delete")
        create_res = owner_client.post(
            "/api/groups",
            json={"name": "Delete By System Admin", "group_type": "company"},
            headers=owner_headers,
        )
        assert create_res.status_code == 200, create_res.text
        group_id = create_res.json()["id"]

        admin_headers = _login_admin(admin_client)
        delete_res = admin_client.delete(f"/api/groups/{group_id}", headers=admin_headers)
        assert delete_res.status_code == 200, delete_res.text
        assert delete_res.json()["ok"] is True

        owner_groups_res = owner_client.get("/api/groups")
        assert owner_groups_res.status_code == 200, owner_groups_res.text
        assert all(item["id"] != group_id for item in owner_groups_res.json())


def test_non_admin_cannot_delete_group(webapp_module):
    with TestClient(webapp_module.app) as owner_client, TestClient(webapp_module.app) as member_client:
        owner_headers = _register(owner_client, "owner_for_forbidden_delete")
        create_res = owner_client.post(
            "/api/groups",
            json={"name": "Forbidden Delete Group", "group_type": "task"},
            headers=owner_headers,
        )
        assert create_res.status_code == 200, create_res.text
        group_id = create_res.json()["id"]

        member_headers = _register(member_client, "member_for_forbidden_delete")
        delete_res = member_client.delete(f"/api/groups/{group_id}", headers=member_headers)
        assert delete_res.status_code == 403, delete_res.text
        assert "Only group admin or system admin can delete this group" in delete_res.text


def test_delete_group_detaches_shared_conversation_and_kb_visibility(webapp_module):
    with TestClient(webapp_module.app) as owner_client, TestClient(webapp_module.app) as teammate_client:
        owner_headers = _register(owner_client, "owner_for_detach")
        teammate_headers = _register(teammate_client, "teammate_for_detach")

        group_res = owner_client.post(
            "/api/groups",
            json={"name": "Detach Target Group", "group_type": "task"},
            headers=owner_headers,
        )
        assert group_res.status_code == 200, group_res.text
        group_id = group_res.json()["id"]

        teammate_me = teammate_client.get("/api/me")
        assert teammate_me.status_code == 200, teammate_me.text
        teammate_id = teammate_me.json()["id"]

        join_res = teammate_client.post(f"/api/groups/{group_id}/join", headers=teammate_headers)
        assert join_res.status_code == 200, join_res.text
        approve_res = owner_client.post(
            f"/api/groups/{group_id}/requests/{teammate_id}/approve",
            headers=owner_headers,
        )
        assert approve_res.status_code == 200, approve_res.text

        kb_res = owner_client.post(
            "/api/kb",
            json={
                "kb_key": "shared_detach_kb",
                "kb_name": "Shared Detach KB",
                "visibility": "task",
                "share_group_id": group_id,
                "brand_voice": "Concise and trusted.",
            },
            headers=owner_headers,
        )
        assert kb_res.status_code == 200, kb_res.text
        kb_payload = kb_res.json()

        conv_res = owner_client.post(
            "/api/conversations",
            json={"task_mode": "chat", "visibility": "task", "share_group_id": group_id},
            headers=owner_headers,
        )
        assert conv_res.status_code == 200, conv_res.text
        conversation_id = conv_res.json()["id"]

        bind_res = owner_client.patch(
            f"/api/conversations/{conversation_id}/kb",
            json={"kb_key": kb_payload["kb_key"], "kb_version": kb_payload["version"]},
            headers=owner_headers,
        )
        assert bind_res.status_code == 200, bind_res.text

        teammate_conversations_before = teammate_client.get("/api/conversations")
        assert teammate_conversations_before.status_code == 200, teammate_conversations_before.text
        assert any(row["id"] == conversation_id for row in teammate_conversations_before.json())

        teammate_kb_before = teammate_client.get("/api/kb/list")
        assert teammate_kb_before.status_code == 200, teammate_kb_before.text
        assert any(item["kb_key"] == "shared_detach_kb" for item in teammate_kb_before.json())

        delete_group_res = owner_client.delete(f"/api/groups/{group_id}", headers=owner_headers)
        assert delete_group_res.status_code == 200, delete_group_res.text
        assert delete_group_res.json()["ok"] is True

        owner_conversations_after = owner_client.get("/api/conversations")
        assert owner_conversations_after.status_code == 200, owner_conversations_after.text
        owner_conv = next((row for row in owner_conversations_after.json() if row["id"] == conversation_id), None)
        assert owner_conv is not None
        assert owner_conv["visibility"] == "private"
        assert owner_conv["share_group_id"] is None

        owner_kb_after = owner_client.get("/api/kb/list")
        assert owner_kb_after.status_code == 200, owner_kb_after.text
        owner_kb = next((item for item in owner_kb_after.json() if item["kb_key"] == "shared_detach_kb"), None)
        assert owner_kb is not None
        assert owner_kb["visibility"] == "private"
        assert owner_kb["share_group_id"] is None

        teammate_conversations_after = teammate_client.get("/api/conversations")
        assert teammate_conversations_after.status_code == 200, teammate_conversations_after.text
        assert all(row["id"] != conversation_id for row in teammate_conversations_after.json())

        teammate_kb_after = teammate_client.get("/api/kb/list")
        assert teammate_kb_after.status_code == 200, teammate_kb_after.text
        assert all(item["kb_key"] != "shared_detach_kb" for item in teammate_kb_after.json())


def test_authenticated_static_pages_render_successfully(webapp_module):
    with TestClient(webapp_module.app) as client:
        _register(client, "page_smoke_user")
        for path in ("/app", "/kb", "/groups"):
            res = client.get(path)
            assert res.status_code == 200, f"{path} failed: {res.status_code} {res.text[:120]}"
            assert "Marketing Copilot" in res.text


def test_experiments_page_is_removed(webapp_module):
    with TestClient(webapp_module.app) as client:
        _register(client, "removed_experiment_page_user")
        res = client.get("/experiments")
        assert res.status_code == 404


def test_experiments_api_is_removed(webapp_module):
    with TestClient(webapp_module.app) as client:
        headers = _register(client, "removed_experiment_api_user")
        res = client.get("/api/experiments", headers=headers)
        assert res.status_code == 404
def test_experiment_routes_are_not_available(webapp_module):
    with TestClient(webapp_module.app) as client:
        _register(client, "page_no_experiments_user")
        for path in ("/experiments", "/api/experiments"):
            res = client.get(path)
            assert res.status_code == 404, f"{path} should be removed"
