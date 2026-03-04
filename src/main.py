import os
from typing import Any, Dict

from dotenv import load_dotenv
from strands import Agent

from model.load import DEFAULT_MODEL_ID, load_model
from prompts import SYSTEM_PROMPT, chat_prompt, language_instruction, marketing_prompt

try:
    from bedrock_agentcore.runtime import BedrockAgentCoreApp
except Exception:
    class BedrockAgentCoreApp:
        def entrypoint(self, func):
            return func

        def run(self):
            raise RuntimeError("BedrockAgentCore runtime is not installed in this environment.")

load_dotenv()


DEFAULT_BRAND_VOICE = "professional, concise, and friendly"
VALID_CHANNELS = {
    "email",
    "linkedin",
    "x",
    "wechat",
    "landing_page",
    "other",
}

_agent_cache: dict[str, Agent] = {}


def _get_agent(model_id: str) -> Agent:
    if model_id not in _agent_cache:
        _agent_cache[model_id] = Agent(
            model=load_model(model_id=model_id),
            system_prompt=SYSTEM_PROMPT,
        )
    return _agent_cache[model_id]
app = BedrockAgentCoreApp()


def _error_response(code: str, message: str, details: str | None = None) -> Dict[str, Any]:
    error: Dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if details:
        error["details"] = details
    return {"error": error}


def _validate_payload(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object.")
    return payload


def _get_marketing_context(payload: Dict[str, Any]) -> Dict[str, Any]:
    context = payload.get("tool_args")
    if context is None:
        context = payload.get("context")
    if context is None:
        return {}
    if not isinstance(context, dict):
        raise ValueError("`tool_args` or `context` must be a JSON object when provided.")
    return context


def _ensure_string(value: Any, field_name: str, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"`{field_name}` must be a string.")
    return value.strip()


def _is_allowed_model_id(model_id: str) -> bool:
    allowed = os.getenv("NOVARED_ALLOWED_MODELS")
    if not allowed:
        return True
    allowed_set = {x.strip() for x in allowed.split(",") if x.strip()}
    return model_id in allowed_set


def _is_credentials_error(exc: Exception) -> bool:
    name = type(exc).__name__
    details = str(exc)
    if name in {"NoCredentialsError", "NoRegionError", "TokenRetrievalError"}:
        return True
    credential_signals = [
        "Unable to locate credentials",
        "Token has expired",
        "Unable to load credentials",
        "UnrecognizedClientException",
        "ExpiredToken",
        "InvalidClientTokenId",
        "AccessDenied",
        "Error when retrieving token from sso",
    ]
    return any(signal in details for signal in credential_signals)


def _local_fallback_response(
    user_prompt: str,
    channel: str,
    product: str,
    audience: str,
    objective: str,
    brand_voice: str,
) -> str:
    channel_label = channel or "general"
    product_label = product or "your product"
    audience_label = audience or "your audience"
    objective_label = objective or "drive results"

    return f"""
### Local Fallback Mode
AWS credentials are not configured, so this response is generated in local fallback mode.

### Campaign Summary
- Channel: {channel_label}
- Product: {product_label}
- Audience: {audience_label}
- Objective: {objective_label}
- Brand voice: {brand_voice}

### Copy Variant A
- Hook: {product_label} for {audience_label}
- Body: Discover how {product_label} helps {audience_label} achieve {objective_label} with a {brand_voice} tone.
- CTA: Get started today.

### Copy Variant B
- Hook: A smarter way to reach {objective_label}
- Body: Use {product_label} to simplify your workflow, communicate clearer value, and convert more of {audience_label}.
- CTA: Try it now.

### Your Original Prompt
{user_prompt}
""".strip()


def _extract_message_text(result: Any) -> str:
    if isinstance(result, str):
        return result.strip()

    message = getattr(result, "message", None)
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
                elif isinstance(item, str):
                    chunks.append(item)
            return "\n".join([x for x in chunks if x]).strip()

    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks = [x for x in content if isinstance(x, str)]
        return "\n".join(chunks).strip()

    return ""


@app.entrypoint
def invoke(payload: Dict[str, Any]):
    """
    AgentCore Runtime entrypoint.

    Expected payload shape:
    {
      "prompt": "<free-form user request>",
      "tool_args": {
         "channel": "email | linkedin | x | wechat | landing_page | other",
         "product": "<what we are promoting>",
         "audience": "<who we are targeting>",
         "objective": "<lead gen | sign-up | brand awareness | event registration | etc.>",
         "brand_voice": "<tone description>",
         "extra_requirements": "<additional constraints or instructions>"
      }
    }
    """
    try:
        payload_dict = _validate_payload(payload)
        user_prompt = _ensure_string(payload_dict.get("prompt", ""), "prompt")
        marketing_context = _get_marketing_context(payload_dict)

        channel = _ensure_string(marketing_context.get("channel"), "channel")
        product = _ensure_string(marketing_context.get("product"), "product")
        audience = _ensure_string(marketing_context.get("audience"), "audience")
        objective = _ensure_string(marketing_context.get("objective"), "objective")
        brand_voice = _ensure_string(
            marketing_context.get("brand_voice"),
            "brand_voice",
            default=DEFAULT_BRAND_VOICE,
        )
        ui_language = _ensure_string(marketing_context.get("ui_language"), "ui_language", default="").lower()
        extra = _ensure_string(marketing_context.get("extra_requirements"), "extra_requirements")
        model_id = _ensure_string(marketing_context.get("model_id"), "model_id", default=DEFAULT_MODEL_ID)

        if channel and channel.lower() not in VALID_CHANNELS:
            valid = ", ".join(sorted(VALID_CHANNELS))
            raise ValueError(f"`channel` must be one of: {valid}.")
        if not _is_allowed_model_id(model_id):
            raise ValueError(f"`model_id` is not allowed: {model_id}")

        has_structured_context = any([channel, product, audience, objective])
        if not user_prompt and not has_structured_context:
            raise ValueError("Either `prompt` or at least one marketing field is required.")

    except ValueError as exc:
        return _error_response("VALIDATION_ERROR", str(exc))

    try:
        language_rules = language_instruction(ui_language)

        if has_structured_context:
            final_prompt = marketing_prompt(
                user_prompt=user_prompt,
                channel=channel,
                product=product,
                audience=audience,
                objective=objective,
                brand_voice=brand_voice,
                extra=extra,
                language_rules=language_rules,
            )
        else:
            final_prompt = chat_prompt(user_prompt=user_prompt, language_rules=language_rules)

        agent = _get_agent(model_id)
        result = agent(final_prompt)
        message = _extract_message_text(result)
        if not message:
            raise RuntimeError("Agent returned an invalid response payload.")

        return {"result": message}

    except Exception as exc:  # pragma: no cover - ensures runtime safety for unexpected model/tool errors
        if _is_credentials_error(exc):
            return {
                "result": _local_fallback_response(
                    user_prompt=user_prompt,
                    channel=channel,
                    product=product,
                    audience=audience,
                    objective=objective,
                    brand_voice=brand_voice,
                ),
                "meta": {
                    "mode": "local_fallback",
                    "reason": "missing_aws_credentials",
                },
            }
        return _error_response(
            "INFERENCE_ERROR",
            "Failed to generate a response from the model.",
            f"{type(exc).__name__}: {exc}",
        )


if __name__ == "__main__":
    app.run()
