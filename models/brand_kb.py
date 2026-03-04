from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BrandKB(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: int = Field(ge=1)
    brand_voice: str = Field(default="professional, concise, and friendly")
    positioning: dict[str, Any] = Field(default_factory=dict)
    glossary: list[Any] = Field(default_factory=list)
    forbidden_words: list[str] = Field(default_factory=list)
    required_terms: list[str] = Field(default_factory=list)
    claims_policy: dict[str, Any] = Field(default_factory=dict)
    examples: dict[str, Any] | None = None
    notes: str | None = None
