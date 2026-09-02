from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=6)
    display_name: str | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class AuthResponse(BaseModel):
    user_id: str
    token: str


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
    display_name: str | None = None
    summary: str = ""
    preferences: dict = Field(default_factory=dict)
    traits: dict = Field(default_factory=dict)
