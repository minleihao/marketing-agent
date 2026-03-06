import json
import os
import re
import asyncio
from typing import Any, Callable, Dict

from dotenv import load_dotenv
from strands import Agent

from model.load import DEFAULT_MAX_TOKENS, DEFAULT_MODEL_ID, load_model
from prompts import (
    SYSTEM_PROMPT,
    ORCHESTRATOR_JSON_TEMPLATE,
    brief_normalizer_prompt,
    chat_prompt,
    evaluator_prompt,
    generator_prompt,
    language_instruction,
    marketing_prompt,
    planner_prompt,
)

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
MODEL_ID_ALIASES = {
    "anthropic.claude-sonnet-4-6": "us.anthropic.claude-sonnet-4-6",
}
VALID_CHANNELS = {
    "email",
    "linkedin",
    "x",
    "wechat",
    "landing_page",
    "other",
}
VALID_OUTPUT_SECTIONS = {"brief", "plan", "generator", "evaluation"}
OUTPUT_SECTION_ALIASES = {
    "assets": "generator",
    "generated": "generator",
    "copy": "generator",
    "eval": "evaluation",
}
THINKING_DEPTH_MULTIPLIERS = {
    "low": 1,
    "medium": 2,
    "high": 4,
}
ORCHESTRATOR_ENABLED = os.getenv("NOVARED_ORCHESTRATOR_ENABLED", "1").strip() not in {"0", "false", "False"}

_agent_cache: dict[str, Agent] = {}
_agent_profile_cache: dict[tuple[str, int], Agent] = {}


def _get_agent(model_id: str) -> Agent:
    if model_id not in _agent_cache:
        _agent_cache[model_id] = Agent(
            model=load_model(model_id=model_id),
            system_prompt=SYSTEM_PROMPT,
        )
    return _agent_cache[model_id]


def _get_agent_with_max_tokens(model_id: str, max_tokens: int) -> Agent:
    cache_key = (model_id, max_tokens)
    if cache_key not in _agent_profile_cache:
        _agent_profile_cache[cache_key] = Agent(
            model=load_model(model_id=model_id, max_tokens=max_tokens),
            system_prompt=SYSTEM_PROMPT,
        )
    return _agent_profile_cache[cache_key]


def _normalize_thinking_depth(raw_depth: str) -> str:
    thinking_depth = raw_depth.strip().lower() or "low"
    if thinking_depth not in THINKING_DEPTH_MULTIPLIERS:
        allowed = ", ".join(THINKING_DEPTH_MULTIPLIERS.keys())
        raise ValueError(f"`thinking_depth` must be one of: {allowed}.")
    return thinking_depth


def _max_tokens_for_thinking_depth(thinking_depth: str) -> int:
    multiplier = THINKING_DEPTH_MULTIPLIERS.get(thinking_depth, 1)
    return DEFAULT_MAX_TOKENS * multiplier


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


def _normalize_channel_selection(raw_channel: Any, raw_channels: Any) -> list[str]:
    selected: list[str] = []
    if isinstance(raw_channels, str):
        raw_channels = [item.strip() for item in raw_channels.split(",")]
    if isinstance(raw_channels, list):
        for item in raw_channels:
            if item is None:
                continue
            if not isinstance(item, str):
                raise ValueError("`channels` must be a list of strings.")
            value = item.strip().lower()
            if value and value not in selected:
                selected.append(value)
    channel_value = _ensure_string(raw_channel, "channel")
    if channel_value:
        normalized = channel_value.lower()
        if normalized not in selected:
            selected.insert(0, normalized)
    return selected


def _normalize_model_id(model_id: str) -> str:
    return MODEL_ID_ALIASES.get(model_id, model_id)


def _is_allowed_model_id(model_id: str) -> bool:
    normalized = _normalize_model_id(model_id)
    allowed = os.getenv("NOVARED_ALLOWED_MODELS")
    if not allowed:
        return True
    allowed_set = {_normalize_model_id(x.strip()) for x in allowed.split(",") if x.strip()}
    return normalized in allowed_set


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


def _stream_agent_text(agent: Agent, prompt: str, on_delta: Callable[[str], None] | None = None) -> str:
    async def _runner() -> str:
        chunks: list[str] = []
        final_from_result = ""
        async for event in agent.stream_async(prompt):
            if not isinstance(event, dict):
                continue
            delta = event.get("data")
            if isinstance(delta, str) and delta:
                chunks.append(delta)
                if on_delta:
                    on_delta(delta)
            if not final_from_result and "result" in event:
                final_from_result = _extract_message_text(event.get("result"))
        if chunks:
            return "".join(chunks).strip()
        return final_from_result.strip()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_runner())
    finally:
        loop.close()


def _extract_json_candidate(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return "{}"
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        raw = fenced.group(1).strip()
    if raw.startswith("{") and raw.endswith("}"):
        return raw
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start : end + 1]
    return "{}"


def _safe_json_loads(text: str, default: Any) -> Any:
    try:
        return json.loads(_extract_json_candidate(text))
    except Exception:
        return default


def _ensure_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _normalize_output_sections(value: Any) -> list[str]:
    if value is None:
        return ["generator"]
    raw_sections = _ensure_str_list(value)
    if not raw_sections:
        return ["generator"]
    normalized: list[str] = []
    for item in raw_sections:
        key = item.strip().lower()
        key = OUTPUT_SECTION_ALIASES.get(key, key)
        if key not in VALID_OUTPUT_SECTIONS:
            valid = ", ".join(sorted(VALID_OUTPUT_SECTIONS))
            raise ValueError(f"`output_sections` contains unsupported value: {item}. Allowed: {valid}.")
        if key not in normalized:
            normalized.append(key)
    return normalized or ["generator"]


def _format_brief_section(brief: dict[str, Any]) -> str:
    lines = [
        "## Brief",
        f"- Task type: {brief.get('task_type', 'n/a')}",
        f"- Objective: {brief.get('objective', 'n/a')}",
        f"- Audience: {brief.get('audience', 'n/a')}",
        f"- Channel plan: {', '.join(brief.get('channel_plan') or ['n/a'])}",
        f"- Success metrics: {', '.join(brief.get('success_metrics') or ['n/a'])}",
    ]
    constraints = brief.get("constraints") or []
    if constraints:
        lines.append("- Constraints:")
        lines.extend([f"  - {item}" for item in constraints])
    missing = brief.get("missing_info") or []
    if missing:
        lines.append("- Missing info:")
        lines.extend([f"  - {item}" for item in missing])
    assumptions = brief.get("assumptions") or []
    if assumptions:
        lines.append("- Assumptions:")
        lines.extend([f"  - {item}" for item in assumptions])
    return "\n".join(lines)


def _format_plan_section(plan: dict[str, Any]) -> str:
    strategy = plan.get("strategy") or {}
    lines = [
        "## Plan",
        "### Strategy",
        f"- Positioning angle: {strategy.get('positioning_angle', 'n/a')}",
        f"- Funnel stage: {strategy.get('funnel_stage', 'n/a')}",
        f"- Offer strategy: {strategy.get('offer_strategy', 'n/a')}",
    ]
    pillars = strategy.get("message_pillars") or []
    if pillars:
        lines.append("- Message pillars:")
        lines.extend([f"  - {item}" for item in pillars])

    channel_execution = plan.get("channel_execution") or []
    if channel_execution:
        lines.append("### Channel Execution")
        for item in channel_execution:
            if not isinstance(item, dict):
                continue
            channel = item.get("channel", "n/a")
            asset_types = ", ".join(item.get("asset_types") or ["n/a"])
            execution_notes = item.get("execution_notes", "n/a")
            primary_kpi = item.get("primary_kpi", "n/a")
            lines.append(f"- {channel}: assets={asset_types}; primary KPI={primary_kpi}")
            lines.append(f"  - Notes: {execution_notes}")

    experiments = plan.get("experiment_matrix") or []
    if experiments:
        lines.append("### Experiment Matrix")
        for item in experiments:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('name', 'Experiment')}: {item.get('variant_a', 'A')} vs {item.get('variant_b', 'B')} "
                f"(expected impact: {item.get('expected_impact', 'n/a')})"
            )

    risks = plan.get("risks_and_mitigations") or []
    if risks:
        lines.append("### Risks & Mitigations")
        for item in risks:
            if not isinstance(item, dict):
                continue
            lines.append(f"- Risk: {item.get('risk', 'n/a')}")
            lines.append(f"  - Mitigation: {item.get('mitigation', 'n/a')}")
    return "\n".join(lines)


def _format_evaluation_section(evaluation: dict[str, Any]) -> str:
    scores = evaluation.get("scores") or {}
    lines = [
        "## Evaluator",
        f"- Overall verdict: {evaluation.get('overall_verdict', 'n/a')}",
        "### Scores",
        f"- Brand consistency: {scores.get('brand_consistency', 'n/a')}/100",
        f"- Clarity: {scores.get('clarity', 'n/a')}/100",
        f"- Conversion potential: {scores.get('conversion_potential', 'n/a')}/100",
        f"- Compliance risk: {scores.get('compliance_risk', 'n/a')}/100",
    ]
    reasons = evaluation.get("reasons") or []
    if reasons:
        lines.append("### Reasons")
        for item in reasons:
            if not isinstance(item, dict):
                continue
            dimension = item.get("dimension", "general")
            reason = item.get("reason", "")
            evidence = item.get("evidence", "")
            evidence_block = f" (evidence: {evidence})" if evidence else ""
            lines.append(f"- [{dimension}] {reason}{evidence_block}")
    required_revisions = evaluation.get("required_revisions") or []
    if required_revisions:
        lines.append("### Required Revisions")
        lines.extend([f"- {item}" for item in required_revisions])
    flagged_claims = evaluation.get("flagged_claims") or []
    if flagged_claims:
        lines.append("### Flagged Claims")
        lines.extend([f"- {item}" for item in flagged_claims])
    return "\n".join(lines)


def _compose_orchestrator_message(orchestrator_payload: dict[str, Any], output_sections: list[str]) -> str:
    if output_sections == ["generator"]:
        return str(orchestrator_payload.get("generated_output", "")).strip()

    blocks: list[str] = []
    for section in output_sections:
        if section == "brief":
            blocks.append(_format_brief_section(orchestrator_payload.get("brief") or {}))
        elif section == "plan":
            blocks.append(_format_plan_section(orchestrator_payload.get("plan") or {}))
        elif section == "generator":
            generated_output = str(orchestrator_payload.get("generated_output", "")).strip()
            if generated_output:
                blocks.append("## Marketing Content\n" + generated_output)
        elif section == "evaluation":
            blocks.append(_format_evaluation_section(orchestrator_payload.get("evaluation") or {}))

    combined = "\n\n---\n\n".join([block for block in blocks if block.strip()])
    return combined.strip() or str(orchestrator_payload.get("generated_output", "")).strip()


def _normalize_experiment_hypothesis(item: Any) -> dict[str, str]:
    if not isinstance(item, dict):
        return {
            "name": "Hypothesis",
            "variant_a": "Control",
            "variant_b": "Variant",
            "expected_impact": "Increase conversion rate",
        }
    return {
        "name": str(item.get("name", "Hypothesis")).strip() or "Hypothesis",
        "variant_a": str(item.get("variant_a", "Control")).strip() or "Control",
        "variant_b": str(item.get("variant_b", "Variant")).strip() or "Variant",
        "expected_impact": str(item.get("expected_impact", "Increase conversion rate")).strip()
        or "Increase conversion rate",
    }


def _normalize_brief_json(candidate: Any, *, fallback: dict[str, Any]) -> dict[str, Any]:
    base = dict(ORCHESTRATOR_JSON_TEMPLATE)
    if isinstance(candidate, dict):
        base.update(candidate)
    base["task_type"] = str(base.get("task_type") or fallback.get("task_type") or "marketing_content_generation").strip()
    base["objective"] = str(base.get("objective") or fallback.get("objective") or "Increase qualified conversions").strip()
    base["audience"] = str(base.get("audience") or fallback.get("audience") or "Broad target audience").strip()
    channel_plan = _ensure_str_list(base.get("channel_plan"))
    if not channel_plan:
        fallback_channels = _ensure_str_list(fallback.get("channel_plan"))
        if fallback_channels:
            channel_plan = fallback_channels
        else:
            fallback_channel = str(fallback.get("channel", "")).strip()
            channel_plan = [fallback_channel] if fallback_channel else ["general"]
    base["channel_plan"] = channel_plan
    constraints = _ensure_str_list(base.get("constraints"))
    if not constraints:
        constraints = ["brand", "legal", "format"]
    base["constraints"] = constraints
    base["missing_info"] = _ensure_str_list(base.get("missing_info"))
    assumptions = _ensure_str_list(base.get("assumptions"))
    if not assumptions:
        assumptions = _ensure_str_list(fallback.get("assumptions")) or ["Use minimum viable assumptions and proceed"]
    base["assumptions"] = assumptions
    success_metrics = _ensure_str_list(base.get("success_metrics"))
    if not success_metrics:
        success_metrics = ["CTR", "CVR", "CPL"]
    base["success_metrics"] = success_metrics
    raw_hypotheses = base.get("experiment_hypotheses")
    if not isinstance(raw_hypotheses, list):
        raw_hypotheses = []
    base["experiment_hypotheses"] = [_normalize_experiment_hypothesis(item) for item in raw_hypotheses]
    if not base["experiment_hypotheses"]:
        base["experiment_hypotheses"] = [
            {
                "name": "Value prop clarity test",
                "variant_a": "Feature-first hook",
                "variant_b": "Outcome-first hook",
                "expected_impact": "Improve CTR",
            }
        ]
    return base


def _normalize_planner_json(candidate: Any, *, brief: dict[str, Any]) -> dict[str, Any]:
    default_plan = {
        "strategy": {
            "positioning_angle": f"Outcome-first positioning for {brief.get('audience', 'target audience')}",
            "message_pillars": [
                "Primary customer pain and urgency",
                "Credible proof and differentiation",
                "Clear next action and low-friction CTA",
            ],
            "funnel_stage": "mid_funnel",
            "offer_strategy": "Value-first offer framing",
        },
        "channel_execution": [
            {
                "channel": channel,
                "asset_types": ["primary_copy", "headline", "cta"],
                "execution_notes": "Manual execution guidance: align message and targeting to audience intent",
                "primary_kpi": (brief.get("success_metrics") or ["CTR"])[0],
            }
            for channel in (brief.get("channel_plan") or ["general"])
        ],
        "experiment_matrix": brief.get("experiment_hypotheses") or [],
        "risks_and_mitigations": [
            {"risk": "Unverifiable claims", "mitigation": "Use defensible claims and concise proof points"}
        ],
    }
    if not isinstance(candidate, dict):
        return default_plan
    plan = dict(default_plan)
    plan.update(candidate)
    if not isinstance(plan.get("strategy"), dict):
        plan["strategy"] = default_plan["strategy"]
    strategy = dict(default_plan["strategy"])
    strategy.update(plan["strategy"])
    strategy["message_pillars"] = _ensure_str_list(strategy.get("message_pillars")) or default_plan["strategy"]["message_pillars"]
    plan["strategy"] = strategy

    channel_execution = plan.get("channel_execution")
    if not isinstance(channel_execution, list) or not channel_execution:
        channel_execution = default_plan["channel_execution"]
    normalized_channels: list[dict[str, Any]] = []
    for item in channel_execution:
        if not isinstance(item, dict):
            continue
        normalized_channels.append(
            {
                "channel": str(item.get("channel", "general")).strip() or "general",
                "asset_types": _ensure_str_list(item.get("asset_types")) or ["primary_copy"],
                # Backward compatible: accept legacy distribution_notes, normalize to execution_notes.
                "execution_notes": str(item.get("execution_notes", "")).strip()
                or str(item.get("distribution_notes", "")).strip()
                or "Manual execution guidance: align message and targeting to audience intent",
                "primary_kpi": str(item.get("primary_kpi", "CTR")).strip() or "CTR",
            }
        )
    plan["channel_execution"] = normalized_channels or default_plan["channel_execution"]

    experiments = plan.get("experiment_matrix")
    if not isinstance(experiments, list):
        experiments = []
    plan["experiment_matrix"] = [_normalize_experiment_hypothesis(item) for item in experiments] or default_plan["experiment_matrix"]

    risks = plan.get("risks_and_mitigations")
    if not isinstance(risks, list) or not risks:
        risks = default_plan["risks_and_mitigations"]
    normalized_risks: list[dict[str, str]] = []
    for item in risks:
        if not isinstance(item, dict):
            continue
        normalized_risks.append(
            {
                "risk": str(item.get("risk", "Execution risk")).strip() or "Execution risk",
                "mitigation": str(item.get("mitigation", "Define clear controls")).strip() or "Define clear controls",
            }
        )
    plan["risks_and_mitigations"] = normalized_risks or default_plan["risks_and_mitigations"]
    return plan


def _normalize_evaluator_json(candidate: Any) -> dict[str, Any]:
    default_eval = {
        "scores": {
            "brand_consistency": 70,
            "clarity": 70,
            "conversion_potential": 70,
            "compliance_risk": 30,
        },
        "overall_verdict": "pass",
        "reasons": [],
        "required_revisions": [],
        "approved_claims": [],
        "flagged_claims": [],
    }
    if not isinstance(candidate, dict):
        return default_eval
    out = dict(default_eval)
    out.update(candidate)
    scores = out.get("scores")
    if not isinstance(scores, dict):
        scores = dict(default_eval["scores"])
    normalized_scores: dict[str, int] = {}
    for key, fallback in default_eval["scores"].items():
        value = scores.get(key, fallback)
        try:
            numeric = int(value)
        except Exception:
            numeric = fallback
        normalized_scores[key] = max(0, min(100, numeric))
    out["scores"] = normalized_scores
    verdict = str(out.get("overall_verdict", "pass")).strip().lower()
    out["overall_verdict"] = verdict if verdict in {"pass", "needs_revision"} else "pass"
    out["required_revisions"] = _ensure_str_list(out.get("required_revisions"))
    out["approved_claims"] = _ensure_str_list(out.get("approved_claims"))
    out["flagged_claims"] = _ensure_str_list(out.get("flagged_claims"))
    reasons = out.get("reasons")
    normalized_reasons: list[dict[str, Any]] = []
    if isinstance(reasons, list):
        for item in reasons:
            if not isinstance(item, dict):
                continue
            normalized_reasons.append(
                {
                    "dimension": str(item.get("dimension", "general")).strip() or "general",
                    "score": max(0, min(100, int(item.get("score", 70)))) if str(item.get("score", "")).isdigit() else 70,
                    "reason": str(item.get("reason", "")).strip(),
                    "evidence": str(item.get("evidence", "")).strip(),
                }
            )
    out["reasons"] = normalized_reasons
    return out


def _run_marketing_orchestration(
    *,
    agent: Agent,
    user_prompt: str,
    channel: str,
    channels: list[str],
    product: str,
    audience: str,
    objective: str,
    brand_voice: str,
    extra: str,
    language_rules: str,
    stream_generator: bool = False,
    on_delta: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    brief_prompt = brief_normalizer_prompt(
        user_prompt=user_prompt,
        channel=channel,
        product=product,
        audience=audience,
        objective=objective,
        brand_voice=brand_voice,
        extra=extra,
    )
    brief_text = _extract_message_text(agent(brief_prompt))
    brief_fallback = {
        "task_type": "marketing_content_generation",
        "objective": objective or "Increase qualified conversions",
        "audience": audience or "Broad target audience",
        "channel": channel,
        "channel_plan": channels,
        "assumptions": [f"Assume product is {product}" if product else "Assume standard SaaS offer context"],
    }
    brief = _normalize_brief_json(_safe_json_loads(brief_text, {}), fallback=brief_fallback)

    planner_text = _extract_message_text(
        agent(
            planner_prompt(
                normalized_brief_json=json.dumps(brief, ensure_ascii=False),
                language_rules=language_rules,
            )
        )
    )
    plan = _normalize_planner_json(_safe_json_loads(planner_text, {}), brief=brief)

    generator_stage_prompt = generator_prompt(
        normalized_brief_json=json.dumps(brief, ensure_ascii=False),
        planner_json=json.dumps(plan, ensure_ascii=False),
        user_prompt=user_prompt,
        language_rules=language_rules,
    )
    if stream_generator:
        generated_output = _stream_agent_text(agent, generator_stage_prompt, on_delta=on_delta)
    else:
        generated_output = _extract_message_text(
            agent(generator_stage_prompt)
        )
    
    if not generated_output:
        raise RuntimeError("Generator stage produced empty output.")

    evaluator_text = _extract_message_text(
        agent(
            evaluator_prompt(
                normalized_brief_json=json.dumps(brief, ensure_ascii=False),
                planner_json=json.dumps(plan, ensure_ascii=False),
                generated_output=generated_output,
                channel=channel,
                product=product,
                audience=audience,
                objective=objective,
                language_rules=language_rules,
            )
        )
    )
    evaluation = _normalize_evaluator_json(_safe_json_loads(evaluator_text, {}))

    return {
        "generated_output": generated_output,
        "brief": brief,
        "plan": plan,
        "evaluation": evaluation,
    }


@app.entrypoint
def invoke(payload: Dict[str, Any]):
    """
    AgentCore Runtime entrypoint.

    Expected payload shape:
    {
      "prompt": "<free-form user request>",
      "tool_args": {
         "channel": "email | linkedin | x | wechat | landing_page | other",
         "channels": ["email", "linkedin"],
         "product": "<what we are promoting>",
         "audience": "<who we are targeting>",
         "objective": "<lead gen | sign-up | brand awareness | event registration | etc.>",
         "brand_voice": "<tone description>",
         "extra_requirements": "<additional constraints or instructions>",
         "thinking_depth": "low | medium | high",
         "output_sections": ["brief", "plan", "generator", "evaluation"]
      }
    }
    """
    try:
        payload_dict = _validate_payload(payload)
        user_prompt = _ensure_string(payload_dict.get("prompt", ""), "prompt")
        marketing_context = _get_marketing_context(payload_dict)

        raw_channels = marketing_context.get("channels")
        channel = _ensure_string(marketing_context.get("channel"), "channel")
        channels = _normalize_channel_selection(channel, raw_channels)
        if channels:
            channel = channels[0]
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
        thinking_depth = _ensure_string(marketing_context.get("thinking_depth"), "thinking_depth", default="low")
        model_id = _normalize_model_id(model_id)
        thinking_depth = _normalize_thinking_depth(thinking_depth)
        include_trace = bool(marketing_context.get("include_trace", False))
        output_sections = _normalize_output_sections(marketing_context.get("output_sections"))

        if raw_channels is not None and channels:
            invalid_channels = [item for item in channels if item not in VALID_CHANNELS]
            if invalid_channels:
                valid = ", ".join(sorted(VALID_CHANNELS))
                raise ValueError(
                    f"`channels` contains unsupported value(s): {', '.join(invalid_channels)}. Allowed: {valid}."
                )
        elif channel and channel.lower() not in VALID_CHANNELS:
            valid = ", ".join(sorted(VALID_CHANNELS))
            raise ValueError(f"`channel` must be one of: {valid}.")
        if not _is_allowed_model_id(model_id):
            raise ValueError(f"`model_id` is not allowed: {model_id}")

        channel_label = ", ".join(channels) if channels else channel
        has_structured_context = any([channel_label, product, audience, objective])
        if not user_prompt and not has_structured_context:
            raise ValueError("Either `prompt` or at least one marketing field is required.")

    except ValueError as exc:
        return _error_response("VALIDATION_ERROR", str(exc))

    try:
        language_rules = language_instruction(ui_language)
        max_tokens = _max_tokens_for_thinking_depth(thinking_depth)
        if max_tokens == DEFAULT_MAX_TOKENS:
            agent = _get_agent(model_id)
        else:
            agent = _get_agent_with_max_tokens(model_id, max_tokens)
        orchestrator_payload: dict[str, Any] | None = None

        if has_structured_context:
            if ORCHESTRATOR_ENABLED:
                orchestrator_payload = _run_marketing_orchestration(
                    agent=agent,
                    user_prompt=user_prompt,
                    channel=channel_label,
                    channels=channels,
                    product=product,
                    audience=audience,
                    objective=objective,
                    brand_voice=brand_voice,
                    extra=extra,
                    language_rules=language_rules,
                )
                message = _compose_orchestrator_message(orchestrator_payload, output_sections)
            else:
                final_prompt = marketing_prompt(
                    user_prompt=user_prompt,
                    channel=channel_label,
                    product=product,
                    audience=audience,
                    objective=objective,
                    brand_voice=brand_voice,
                    extra=extra,
                    language_rules=language_rules,
                )
                result = agent(final_prompt)
                message = _extract_message_text(result)
        else:
            final_prompt = chat_prompt(
                user_prompt=user_prompt,
                language_rules=language_rules,
                context_block=extra,
            )
            result = agent(final_prompt)
            message = _extract_message_text(result)

        if not message:
            raise RuntimeError("Agent returned an invalid response payload.")

        output: Dict[str, Any] = {"result": message}
        if include_trace and orchestrator_payload:
            output["orchestrator"] = {
                "brief": orchestrator_payload.get("brief"),
                "plan": orchestrator_payload.get("plan"),
                "evaluation": orchestrator_payload.get("evaluation"),
            }
        return output

    except Exception as exc:  # pragma: no cover - ensures runtime safety for unexpected model/tool errors
        if _is_credentials_error(exc):
            return {
                "result": _local_fallback_response(
                user_prompt=user_prompt,
                    channel=channel_label,
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


def invoke_stream(payload: Dict[str, Any], on_delta: Callable[[str], None] | None = None):
    try:
        payload_dict = _validate_payload(payload)
        user_prompt = _ensure_string(payload_dict.get("prompt", ""), "prompt")
        marketing_context = _get_marketing_context(payload_dict)

        raw_channels = marketing_context.get("channels")
        channel = _ensure_string(marketing_context.get("channel"), "channel")
        channels = _normalize_channel_selection(channel, raw_channels)
        if channels:
            channel = channels[0]
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
        thinking_depth = _ensure_string(marketing_context.get("thinking_depth"), "thinking_depth", default="low")
        model_id = _normalize_model_id(model_id)
        thinking_depth = _normalize_thinking_depth(thinking_depth)
        include_trace = bool(marketing_context.get("include_trace", False))
        output_sections = _normalize_output_sections(marketing_context.get("output_sections"))

        if raw_channels is not None and channels:
            invalid_channels = [item for item in channels if item not in VALID_CHANNELS]
            if invalid_channels:
                valid = ", ".join(sorted(VALID_CHANNELS))
                raise ValueError(
                    f"`channels` contains unsupported value(s): {', '.join(invalid_channels)}. Allowed: {valid}."
                )
        elif channel and channel.lower() not in VALID_CHANNELS:
            valid = ", ".join(sorted(VALID_CHANNELS))
            raise ValueError(f"`channel` must be one of: {valid}.")
        if not _is_allowed_model_id(model_id):
            raise ValueError(f"`model_id` is not allowed: {model_id}")

        channel_label = ", ".join(channels) if channels else channel
        has_structured_context = any([channel_label, product, audience, objective])
        if not user_prompt and not has_structured_context:
            raise ValueError("Either `prompt` or at least one marketing field is required.")

    except ValueError as exc:
        return _error_response("VALIDATION_ERROR", str(exc))

    try:
        language_rules = language_instruction(ui_language)
        max_tokens = _max_tokens_for_thinking_depth(thinking_depth)
        if max_tokens == DEFAULT_MAX_TOKENS:
            agent = _get_agent(model_id)
        else:
            agent = _get_agent_with_max_tokens(model_id, max_tokens)
        orchestrator_payload: dict[str, Any] | None = None

        if has_structured_context:
            if ORCHESTRATOR_ENABLED:
                stream_generator = output_sections == ["generator"] and on_delta is not None
                if stream_generator:
                    # Fast stream path: bypass multi-stage orchestration for immediate token streaming.
                    final_prompt = marketing_prompt(
                        user_prompt=user_prompt,
                        channel=channel_label,
                        product=product,
                        audience=audience,
                        objective=objective,
                        brand_voice=brand_voice,
                        extra=extra,
                        language_rules=language_rules,
                    )
                    message = _stream_agent_text(agent, final_prompt, on_delta=on_delta)
                else:
                    orchestrator_payload = _run_marketing_orchestration(
                        agent=agent,
                        user_prompt=user_prompt,
                        channel=channel_label,
                        channels=channels,
                        product=product,
                        audience=audience,
                        objective=objective,
                        brand_voice=brand_voice,
                        extra=extra,
                        language_rules=language_rules,
                        stream_generator=False,
                        on_delta=None,
                    )
                    message = _compose_orchestrator_message(orchestrator_payload, output_sections)
            else:
                final_prompt = marketing_prompt(
                    user_prompt=user_prompt,
                    channel=channel_label,
                    product=product,
                    audience=audience,
                    objective=objective,
                    brand_voice=brand_voice,
                    extra=extra,
                    language_rules=language_rules,
                )
                if on_delta:
                    message = _stream_agent_text(agent, final_prompt, on_delta=on_delta)
                else:
                    result = agent(final_prompt)
                    message = _extract_message_text(result)
        else:
            final_prompt = chat_prompt(
                user_prompt=user_prompt,
                language_rules=language_rules,
                context_block=extra,
            )
            if on_delta:
                message = _stream_agent_text(agent, final_prompt, on_delta=on_delta)
            else:
                result = agent(final_prompt)
                message = _extract_message_text(result)

        if not message:
            raise RuntimeError("Agent returned an invalid response payload.")

        output: Dict[str, Any] = {"result": message}
        if include_trace and orchestrator_payload:
            output["orchestrator"] = {
                "brief": orchestrator_payload.get("brief"),
                "plan": orchestrator_payload.get("plan"),
                "evaluation": orchestrator_payload.get("evaluation"),
            }
        return output

    except Exception as exc:
        if _is_credentials_error(exc):
            fallback = _local_fallback_response(
                user_prompt=user_prompt,
                channel=channel_label,
                product=product,
                audience=audience,
                objective=objective,
                brand_voice=brand_voice,
            )
            if on_delta and fallback:
                on_delta(fallback)
            return {
                "result": fallback,
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
