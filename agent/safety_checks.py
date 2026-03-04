from __future__ import annotations

import re

from models.brand_kb import BrandKB


def check_forbidden_words(text: str, kb: BrandKB) -> list[str]:
    violations: list[str] = []
    lower_text = text.lower()
    for word in kb.forbidden_words:
        if word.lower() in lower_text:
            violations.append(f"Forbidden word detected: {word}")
    return violations


def check_glossary(text: str, kb: BrandKB) -> tuple[str, list[str]]:
    updated = text
    warnings: list[str] = []

    for item in kb.glossary:
        if isinstance(item, dict):
            avoid = str(item.get("avoid", "")).strip()
            preferred = str(item.get("preferred", "")).strip()
            if avoid and preferred and avoid.lower() in updated.lower():
                updated = re.sub(re.escape(avoid), preferred, updated, flags=re.IGNORECASE)
                warnings.append(f"Replaced '{avoid}' with '{preferred}'")

    return updated, warnings


def check_claims(text: str, kb: BrandKB) -> list[str]:
    warnings: list[str] = []
    strict_mode = bool(kb.claims_policy.get("strict", False))
    require_source = bool(kb.claims_policy.get("require_source", False))

    risky_patterns = [
        r"\b(always|never|guaranteed|100%|best in the world|cure)\b",
        r"\b(proven to|scientifically proven|clinically proven)\b",
    ]

    for pattern in risky_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            warnings.append("Potential risky claim detected.")
            break

    if strict_mode and warnings:
        warnings.append("Strict claims policy enabled: review required.")

    if require_source and re.search(r"\b(proven|study|research|data shows)\b", text, flags=re.IGNORECASE):
        warnings.append("Claims policy requires source citation.")

    return warnings
