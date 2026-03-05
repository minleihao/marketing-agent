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
    assert "Assume the product and campaign are primarily designed for US-centered customers." in captured["prompt"]


def test_invoke_chat_mode_includes_context_block(monkeypatch):
    captured = {}

    def fake_agent(prompt: str):
        captured["prompt"] = prompt
        return SimpleNamespace(message="context-aware answer")

    monkeypatch.setattr(main, "_get_agent", lambda _model_id: fake_agent)

    result = main.invoke(
        {
            "prompt": "continue",
            "tool_args": {
                "extra_requirements": "Recent conversation context:\n- User: We target SMB founders\n- Assistant: Focus on LinkedIn\n\nShared brand knowledge context:\n- Brand voice: concise",
            },
        }
    )

    assert result == {"result": "context-aware answer"}
    assert "Conversation context from previous turns and attached sources:" in captured["prompt"]
    assert "We target SMB founders" in captured["prompt"]


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
    "thinking_depth, expected_multiplier",
    [
        ("medium", 2),
        ("high", 4),
    ],
)
def test_invoke_uses_thinking_depth_token_multiplier(monkeypatch, thinking_depth, expected_multiplier):
    used = {}

    def fake_get_agent(_model_id: str):
        raise AssertionError("default agent path should not be used for medium/high depth")

    def fake_get_agent_with_max_tokens(model_id: str, max_tokens: int):
        used["model_id"] = model_id
        used["max_tokens"] = max_tokens

        def fake_agent(_prompt: str):
            return SimpleNamespace(message="ok")

        return fake_agent

    monkeypatch.setattr(main, "_get_agent", fake_get_agent)
    monkeypatch.setattr(main, "_get_agent_with_max_tokens", fake_get_agent_with_max_tokens)

    result = main.invoke(
        {"prompt": "hi", "tool_args": {"model_id": "us.amazon.nova-lite-v1:0", "thinking_depth": thinking_depth}}
    )

    assert result == {"result": "ok"}
    assert used["model_id"] == "us.amazon.nova-lite-v1:0"
    assert used["max_tokens"] == main.DEFAULT_MAX_TOKENS * expected_multiplier


def test_invoke_rejects_invalid_thinking_depth():
    result = main.invoke({"prompt": "hi", "tool_args": {"thinking_depth": "ultra"}})
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert "`thinking_depth` must be one of:" in result["error"]["message"]


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


def test_invoke_returns_local_fallback_when_sso_token_expired(monkeypatch):
    class TokenRetrievalError(Exception):
        pass

    def boom(_prompt: str):
        raise TokenRetrievalError("Error when retrieving token from sso: Token has expired and refresh failed")

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


def test_invoke_returns_orchestrator_trace_when_include_trace_enabled(monkeypatch):
    outputs = iter(
        [
            # BriefNormalizer output
            SimpleNamespace(
                message=(
                    '{"task_type":"campaign planning","objective":"trial signup","audience":"SMB founders",'
                    '"channel_plan":["email"],"constraints":["brand","legal","format"],'
                    '"missing_info":[],"assumptions":["assume baseline"],"success_metrics":["CTR","CVR","CPL"],'
                    '"experiment_hypotheses":[{"name":"Hook test","variant_a":"A","variant_b":"B","expected_impact":"CTR lift"}]}'
                )
            ),
            # Planner output
            SimpleNamespace(
                message=(
                    '{"strategy":{"positioning_angle":"Outcome-first","message_pillars":["p1","p2","p3"],'
                    '"funnel_stage":"mid_funnel","offer_strategy":"free_trial"},'
                    '"channel_execution":[{"channel":"email","asset_types":["copy"],"distribution_notes":"notes","primary_kpi":"CTR"}],'
                    '"experiment_matrix":[{"name":"Hook test","variant_a":"A","variant_b":"B","expected_impact":"CTR lift"}],'
                    '"risks_and_mitigations":[{"risk":"claim risk","mitigation":"use evidence"}]}'
                )
            ),
            # Generator output
            SimpleNamespace(message="Generated campaign copy"),
            # Evaluator output
            SimpleNamespace(
                message=(
                    '{"scores":{"brand_consistency":88,"clarity":90,"conversion_potential":84,"compliance_risk":20},'
                    '"overall_verdict":"pass","reasons":[{"dimension":"clarity","score":90,"reason":"clear","evidence":"structured"}],'
                    '"required_revisions":[],"approved_claims":["claim a"],"flagged_claims":[]}'
                )
            ),
        ]
    )

    def fake_agent(_prompt: str):
        return next(outputs)

    monkeypatch.setattr(main, "_get_agent", lambda _model_id: fake_agent)

    result = main.invoke(
        {
            "prompt": "Generate launch copy",
            "tool_args": {
                "channel": "email",
                "product": "Acme AI",
                "audience": "SMB founders",
                "objective": "trial signup",
                "include_trace": True,
            },
        }
    )

    assert result["result"] == "Generated campaign copy"
    assert "orchestrator" in result
    assert result["orchestrator"]["brief"]["task_type"] == "campaign planning"
    assert result["orchestrator"]["plan"]["strategy"]["positioning_angle"] == "Outcome-first"
    assert result["orchestrator"]["evaluation"]["overall_verdict"] == "pass"


def test_invoke_supports_output_sections_brief_only(monkeypatch):
    outputs = iter(
        [
            SimpleNamespace(
                message=(
                    '{"task_type":"campaign planning","objective":"trial signup","audience":"SMB founders",'
                    '"channel_plan":["email"],"constraints":["brand","legal","format"],'
                    '"missing_info":[],"assumptions":["assume baseline"],"success_metrics":["CTR","CVR","CPL"],'
                    '"experiment_hypotheses":[{"name":"Hook test","variant_a":"A","variant_b":"B","expected_impact":"CTR lift"}]}'
                )
            ),
            SimpleNamespace(
                message=(
                    '{"strategy":{"positioning_angle":"Outcome-first","message_pillars":["p1","p2","p3"],'
                    '"funnel_stage":"mid_funnel","offer_strategy":"free_trial"},'
                    '"channel_execution":[{"channel":"email","asset_types":["copy"],"distribution_notes":"notes","primary_kpi":"CTR"}],'
                    '"experiment_matrix":[{"name":"Hook test","variant_a":"A","variant_b":"B","expected_impact":"CTR lift"}],'
                    '"risks_and_mitigations":[{"risk":"claim risk","mitigation":"use evidence"}]}'
                )
            ),
            SimpleNamespace(message="Generated campaign copy"),
            SimpleNamespace(
                message=(
                    '{"scores":{"brand_consistency":88,"clarity":90,"conversion_potential":84,"compliance_risk":20},'
                    '"overall_verdict":"pass","reasons":[{"dimension":"clarity","score":90,"reason":"clear","evidence":"structured"}],'
                    '"required_revisions":[],"approved_claims":["claim a"],"flagged_claims":[]}'
                )
            ),
        ]
    )

    def fake_agent(_prompt: str):
        return next(outputs)

    monkeypatch.setattr(main, "_get_agent", lambda _model_id: fake_agent)

    result = main.invoke(
        {
            "prompt": "Generate launch copy",
            "tool_args": {
                "channel": "email",
                "product": "Acme AI",
                "audience": "SMB founders",
                "objective": "trial signup",
                "output_sections": ["brief"],
            },
        }
    )

    assert "## Brief" in result["result"]
    assert "## Plan" not in result["result"]
    assert "## Evaluator" not in result["result"]
    assert "Generated campaign copy" not in result["result"]


def test_invoke_rejects_invalid_output_section():
    result = main.invoke(
        {
            "prompt": "Generate launch copy",
            "tool_args": {
                "channel": "email",
                "output_sections": ["not_supported"],
            },
        }
    )

    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert "`output_sections` contains unsupported value" in result["error"]["message"]
