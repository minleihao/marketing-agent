from __future__ import annotations

from models.brand_kb import BrandKB


def build_prompt(user_prompt: str, tool_args: dict, kb: BrandKB) -> str:
    return f"""
You are a marketing agent. Follow the brand knowledge base strictly.

[Brand Voice]
{kb.brand_voice}

[Positioning]
{kb.positioning}

[Glossary]
{kb.glossary}

[Forbidden Words]
{kb.forbidden_words}

[Claims Policy]
{kb.claims_policy}

[Task Instruction]
- Channel: {tool_args.get('channel', 'unspecified')}
- Product: {tool_args.get('product', 'unspecified')}
- Audience: {tool_args.get('audience', 'unspecified')}
- Objective: {tool_args.get('objective', 'unspecified')}
- Extra: {tool_args.get('extra_requirements', 'none')}

User request:
{user_prompt}
""".strip()
