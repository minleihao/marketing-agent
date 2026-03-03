# src/main.py

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

model = load_model()

# You can wire tools later if needed. For now we keep the agent simple.
agent = Agent(
    model=model,
    system_prompt=SYSTEM_PROMPT,
)
# AgentCore Runtime app
app = BedrockAgentCoreApp()


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

    user_prompt: str = payload.get("prompt", "") or ""
    # Prefer `tool_args`, but also accept `context` for flexibility
    marketing_context: Dict[str, Any] = (
        payload.get("tool_args")
        or payload.get("context")
        or {}
    )

    channel = marketing_context.get("channel")
    product = marketing_context.get("product")
    audience = marketing_context.get("audience")
    objective = marketing_context.get("objective")
    brand_voice = marketing_context.get("brand_voice", "professional, concise, and friendly")
    extra = marketing_context.get("extra_requirements", "")

    # If structured marketing parameters are provided, build a focused prompt
    if channel or product or audience or objective:
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
        # No structured parameters: let the agent decide the best way to help,
        # but still treat this as a marketing-oriented question.
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

    return {
        "result": result.message,
    }


if __name__ == "__main__":
    # Optional local run; for development we mainly use `agentcore dev`.
    app.run()