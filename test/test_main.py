from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import main  # noqa: E402


def test_invoke_with_structured_context_returns_result(monkeypatch):
    captured = {}

    def fake_agent(prompt: str):
        captured["prompt"] = prompt
        return SimpleNamespace(message="generated copy")

    monkeypatch.setattr(main, "_get_agent", lambda _model_id: fake_agent)

    payload = {
        "prompt": "Promote our upcoming webinar.",
        "tool_args": {
            "channel": "email",
            "product": "AI assistant",
            "audience": "B2B marketers",
            "objective": "event registration",
            "brand_voice": "confident and concise",
            "extra_requirements": "mention limited seats",
        },
    }

    result = main.invoke(payload)

    assert result == {"result": "generated copy"}
    assert "Campaign inputs:" in captured["prompt"]
    assert "- Channel: email" in captured["prompt"]
    assert "- Product / offer: AI assistant" in captured["prompt"]


def test_invoke_without_structured_context_uses_general_prompt(monkeypatch):
    captured = {}

    def fake_agent(prompt: str):
        captured["prompt"] = prompt
        return SimpleNamespace(message="general answer")

    monkeypatch.setattr(main, "_get_agent", lambda _model_id: fake_agent)

    result = main.invoke({"prompt": "给我一个下季度campaign idea"})

    assert result == {"result": "general answer"}
    assert "The user is asking for help related to marketing." in captured["prompt"]


def test_invoke_uses_selected_model(monkeypatch):
    used = {}

    def fake_get_agent(model_id: str):
        used["model_id"] = model_id

        def fake_agent(_prompt: str):
            return SimpleNamespace(message="ok")

        return fake_agent

    monkeypatch.setattr(main, "_get_agent", fake_get_agent)

    result = main.invoke({"prompt": "hi", "tool_args": {"model_id": "us.amazon.nova-lite-v1:0"}})

    assert result == {"result": "ok"}
    assert used["model_id"] == "us.amazon.nova-lite-v1:0"


@pytest.mark.parametrize(
    "payload, expected_message",
    [
        (None, "Payload must be a JSON object."),
        ({"prompt": "hi", "tool_args": "bad"}, "`tool_args` or `context` must be a JSON object when provided."),
        ({"prompt": 123}, "`prompt` must be a string."),
        ({"prompt": "", "tool_args": {}}, "Either `prompt` or at least one marketing field is required."),
        ({"prompt": "hi", "tool_args": {"channel": "sms"}}, "`channel` must be one of:"),
    ],
)
def test_invoke_validation_errors(payload, expected_message):
    result = main.invoke(payload)

    assert "error" in result
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert expected_message in result["error"]["message"]


def test_invoke_rejects_disallowed_model(monkeypatch):
    monkeypatch.setenv("NOVARED_ALLOWED_MODELS", "us.amazon.nova-micro-v1:0")
    result = main.invoke({"prompt": "hi", "tool_args": {"model_id": "us.amazon.nova-lite-v1:0"}})
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert "`model_id` is not allowed" in result["error"]["message"]


def test_invoke_returns_inference_error_when_agent_raises(monkeypatch):
    def boom(_prompt: str):
        raise RuntimeError("bedrock timeout")

    monkeypatch.setattr(main, "_get_agent", lambda _model_id: boom)

    result = main.invoke({"prompt": "write ad copy"})

    assert "error" in result
    assert result["error"]["code"] == "INFERENCE_ERROR"
    assert result["error"]["message"] == "Failed to generate a response from the model."
    assert "RuntimeError: bedrock timeout" in result["error"]["details"]


def test_invoke_returns_local_fallback_when_credentials_missing(monkeypatch):
    class NoCredentialsError(Exception):
        pass

    def boom(_prompt: str):
        raise NoCredentialsError("Unable to locate credentials")

    monkeypatch.setattr(main, "_get_agent", lambda _model_id: boom)

    result = main.invoke({"prompt": "write ad copy"})

    assert "result" in result
    assert "Local Fallback Mode" in result["result"]
    assert result["meta"]["mode"] == "local_fallback"
    assert result["meta"]["reason"] == "missing_aws_credentials"


def test_invoke_accepts_agent_result_message_dict(monkeypatch):
    def fake_agent(_prompt: str):
        return SimpleNamespace(
            message={
                "role": "assistant",
                "content": [{"text": "dict message payload"}],
            }
        )

    monkeypatch.setattr(main, "_get_agent", lambda _model_id: fake_agent)

    result = main.invoke({"prompt": "write ad copy"})

    assert result == {"result": "dict message payload"}


def test_invoke_returns_inference_error_when_agent_message_missing(monkeypatch):
    def fake_agent(_prompt: str):
        return SimpleNamespace(text="missing_message")

    monkeypatch.setattr(main, "_get_agent", lambda _model_id: fake_agent)

    result = main.invoke({"prompt": "write ad copy"})

    assert "error" in result
    assert result["error"]["code"] == "INFERENCE_ERROR"
    assert "Agent returned an invalid response payload." in result["error"]["details"]
