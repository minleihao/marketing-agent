from typing import Any, Dict

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent

from model.load import load_model


SYSTEM_PROMPT = """
You are the in-house marketing co-pilot for our company.

You primarily support:
- Campaign planning and messaging.
- Channel-specific copywriting (email, LinkedIn, X/Twitter, WeChat, landing pages, in-product banners).
- Light analysis of campaign performance and suggestions based on user-provided metrics.

Guidelines:
- If the user request is ambiguous, ask exactly one clarifying question.
- When generating copy, prefer giving 2–3 variants so the marketing team can choose.
- Keep outputs structured in clear Markdown sections that are easy to copy-paste into tools like HubSpot, Marketo, social schedulers, or slide decks.
- Respect the brand voice provided by the user. If none is provided, default to “professional, concise, and friendly”.
"""

DEFAULT_BRAND_VOICE = "professional, concise, and friendly"
VALID_CHANNELS = {
    "email",
    "linkedin",
    "x",
    "wechat",
    "landing_page",
    "other",
}

model = load_model()

agent = Agent(
    model=model,
    system_prompt=SYSTEM_PROMPT,
)
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
        extra = _ensure_string(marketing_context.get("extra_requirements"), "extra_requirements")

        if channel and channel.lower() not in VALID_CHANNELS:
            valid = ", ".join(sorted(VALID_CHANNELS))
            raise ValueError(f"`channel` must be one of: {valid}.")

        has_structured_context = any([channel, product, audience, objective])
        if not user_prompt and not has_structured_context:
            raise ValueError("Either `prompt` or at least one marketing field is required.")

    except ValueError as exc:
        return _error_response("VALIDATION_ERROR", str(exc))

    try:
        if has_structured_context:
            structured_prompt = f"""
You are helping the marketing team craft channel-specific copy.

Campaign inputs:
- Channel: {channel or "unspecified"}
- Product / offer: {product or "unspecified"}
- Target audience: {audience or "unspecified"}
- Objective: {objective or "unspecified"}
- Brand voice: {brand_voice}

Extra requirements: {extra or "None"}

Please:
1. Generate 2–3 alternative versions of copy optimized for this channel.
2. For each version, include:
   - A short title / hook.
   - Main body copy.
   - 1–2 clear calls-to-action (CTAs).
3. Keep the output in well-structured Markdown with headings, bullet points, and clear separation between variants.

User’s free-form instructions or additional context:
{user_prompt}
"""
            final_prompt = structured_prompt
        else:
            final_prompt = f"""
The user is asking for help related to marketing.

First:
- Identify whether this is primarily about copywriting, campaign idea brainstorming,
  performance analysis, or something else.
- If the request is ambiguous, ask exactly one clarifying question.

Then:
- Provide a helpful, marketing-focused answer or content.

User message:
{user_prompt}
"""

        result = agent(final_prompt)
        message = getattr(result, "message", None)
        if not isinstance(message, str) or not message:
            raise RuntimeError("Agent returned an invalid response payload.")

        return {"result": message}

    except Exception as exc:  # pragma: no cover - ensures runtime safety for unexpected model/tool errors
        return _error_response(
            "INFERENCE_ERROR",
            "Failed to generate a response from the model.",
            f"{type(exc).__name__}: {exc}",
        )


if __name__ == "__main__":
    app.run()
