from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3)
    username: str = Field(min_length=1)
    password: str = Field(min_length=6)
    verification_code: str = Field(min_length=6, max_length=6)
    display_name: str | None = None


class LoginRequest(BaseModel):
    identifier: str | None = Field(default=None, min_length=1)
    username: str | None = Field(default=None, min_length=1)
    password: str = Field(min_length=1)


class AuthResponse(BaseModel):
    user_id: str
    token: str


class EmailCodeRequest(BaseModel):
    email: str = Field(min_length=3)
    purpose: str = Field(pattern="^(register|email_change)$")


class EmailCodeResponse(BaseModel):
    cooldown_seconds: int


class ThreadCreateRequest(BaseModel):
    title: str | None = None


class ThreadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str | None
    created_at: str
    updated_at: str


class ThreadListResponse(BaseModel):
    threads: list[ThreadResponse]


class ProfileResponse(BaseModel):
    user_id: str
    username: str | None = None
    email: str | None = None
    display_name: str | None = None
    has_avatar: bool = False
    summary: str = ""
    preferences: dict = Field(default_factory=dict)
    traits: dict = Field(default_factory=dict)


class ProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)


class EmailChangeRequest(BaseModel):
    email: str = Field(min_length=3)
    verification_code: str = Field(min_length=6, max_length=6)
