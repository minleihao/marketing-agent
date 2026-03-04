from __future__ import annotations

import json
import os
from typing import Any

import boto3

from agent.prompt_builder import build_prompt
from models.brand_kb import BrandKB


class MarketingAgent:
    def __init__(self, model_id: str | None = None, region: str | None = None) -> None:
        self.model_id = model_id or os.getenv("BEDROCK_MODEL", "us.amazon.nova-micro-v1:0")
        self.region = region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-2"
        self.client = boto3.client("bedrock-runtime", region_name=self.region)

    def generate_marketing_content(self, prompt: str, tool_args: dict[str, Any], kb: BrandKB) -> str:
        final_prompt = build_prompt(prompt, tool_args, kb)
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": final_prompt}],
                }
            ],
            "inferenceConfig": {
                "maxTokens": 1200,
                "temperature": 0.5,
                "topP": 0.9,
            },
        }

        resp = self.client.invoke_model(
            modelId=self.model_id,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )

        payload = json.loads(resp["body"].read())
        return self._extract_text(payload)

    def _extract_text(self, payload: dict[str, Any]) -> str:
        # Nova/Converse style
        output = payload.get("output", {})
        message = output.get("message", {})
        content = message.get("content", [])
        for item in content:
            text = item.get("text") if isinstance(item, dict) else None
            if text:
                return text

        # Generic fallback
        text = payload.get("completion") or payload.get("outputText")
        if isinstance(text, str) and text.strip():
            return text

        return json.dumps(payload, ensure_ascii=False)
