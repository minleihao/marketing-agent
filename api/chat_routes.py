from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from flask import Blueprint, jsonify, request

from agent.agent import MarketingAgent
from agent.safety_checks import check_claims, check_forbidden_words, check_glossary
from storage.kb_store import get_kb
from storage.log_store import save_generation_log


chat_routes = Blueprint("chat_routes", __name__, url_prefix="/api")
agent = MarketingAgent()


@chat_routes.post("/chat")
def chat_route():
    body = request.get_json(force=True, silent=True) or {}
    prompt = str(body.get("prompt", "")).strip()
    tool_args = body.get("tool_args") or {}
    kb_id = str(body.get("kb_id", "")).strip()

    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    if not kb_id:
        return jsonify({"error": "kb_id is required"}), 400

    kb = get_kb(kb_id)
    if not kb:
        return jsonify({"error": "KB not found"}), 404

    request_id = str(uuid4())
    try:
        output = agent.generate_marketing_content(prompt, tool_args, kb)
    except Exception as exc:
        return jsonify({"error": f"Bedrock call failed: {exc}"}), 500

    output_after_glossary, glossary_warnings = check_glossary(output, kb)
    forbidden_violations = check_forbidden_words(output_after_glossary, kb)
    claim_warnings = check_claims(output_after_glossary, kb)
    violations = glossary_warnings + forbidden_violations + claim_warnings

    save_generation_log(
        {
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt": prompt,
            "kb_id": kb.id,
            "kb_version": kb.version,
            "model": agent.model_id,
            "output": output_after_glossary,
            "violations": violations,
        }
    )

    return jsonify(
        {
            "request_id": request_id,
            "output": output_after_glossary,
            "violations": violations,
            "model": agent.model_id,
        }
    )
