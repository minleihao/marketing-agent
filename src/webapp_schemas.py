from typing import Any

from pydantic import BaseModel, Field


class RegisterInput(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    join_group_ids: list[int] = Field(default_factory=list)


class LoginInput(BaseModel):
    username: str
    password: str


class ConversationCreateInput(BaseModel):
    title: str | None = None
    task_mode: str | None = None
    thinking_depth: str | None = None
    ui_language: str | None = None
    visibility: str | None = "private"
    share_group_id: int | None = None


class MessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    ui_language: str | None = None
    output_sections: list[str] | None = None
    channel: str | None = None
    channels: list[str] | None = None
    product: str | None = None
    audience: str | None = None
    objective: str | None = None
    brand_voice: str | None = None
    extra_requirements: str | None = None


class AdminCreateUserInput(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    is_admin: bool = False


class AdminResetPasswordInput(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class AccountPasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class BrandKBInput(BaseModel):
    kb_key: str = Field(min_length=1, max_length=80)
    kb_name: str | None = Field(default=None, max_length=120)
    brand_voice: str | None = Field(default=None, max_length=500)
    visibility: str | None = "private"
    share_group_id: int | None = None
    positioning: Any = Field(default_factory=dict)
    glossary: Any = Field(default_factory=list)
    forbidden_words: Any = Field(default_factory=list)
    required_terms: Any = Field(default_factory=list)
    claims_policy: Any = Field(default_factory=dict)
    examples: Any | None = None
    notes: str | None = Field(default=None, max_length=4000)


class ConversationKBInput(BaseModel):
    kb_key: str | None = Field(default=None, max_length=80)
    kb_version: int | None = Field(default=None, ge=1)


class ConversationModeInput(BaseModel):
    task_mode: str


class ConversationModelInput(BaseModel):
    model_id: str = Field(min_length=3, max_length=128)


class ConversationThinkingDepthInput(BaseModel):
    thinking_depth: str


class ConversationVisibilityInput(BaseModel):
    visibility: str
    share_group_id: int | None = None


class ConversationTitleInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class GroupCreateInput(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    group_type: str


class GroupInviteInput(BaseModel):
    username: str = Field(min_length=3, max_length=32)


class GroupTransferAdminInput(BaseModel):
    new_admin_user_id: int


class BrandKBUpdateInput(BaseModel):
    kb_name: str | None = Field(default=None, max_length=120)
    brand_voice: str | None = Field(default=None, max_length=500)
    visibility: str | None = None
    share_group_id: int | None = None
    positioning: Any = Field(default_factory=dict)
    glossary: Any = Field(default_factory=list)
    forbidden_words: Any = Field(default_factory=list)
    required_terms: Any = Field(default_factory=list)
    claims_policy: Any = Field(default_factory=dict)
    examples: Any | None = None
    notes: str | None = Field(default=None, max_length=4000)


class AdminStatusInput(BaseModel):
    is_active: bool
