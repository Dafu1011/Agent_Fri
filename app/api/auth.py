from fastapi import APIRouter, HTTPException, Request
from app.auth import AuthRepository
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    ProfileResponse,
    RegisterRequest,
    ThreadCreateRequest,
    ThreadListResponse,
    ThreadResponse,
)

router = APIRouter(tags=["auth"])


def get_auth_repository(request: Request) -> AuthRepository:
    repository = getattr(request.app.state, "auth_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="Auth store is not available")
    return repository


def get_current_user_id(request: Request) -> str:
    authorization = request.headers.get("authorization")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    user_id = get_auth_repository(request).get_user_id_for_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user_id


@router.post("/auth/register", response_model=AuthResponse)
async def register(payload: RegisterRequest, request: Request) -> AuthResponse:
    repository = get_auth_repository(request)
    try:
        user = repository.create_user(
            username=payload.username,
            password=payload.password,
            display_name=payload.display_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Username already exists") from exc
    token = repository.create_session(user.id)
    return AuthResponse(user_id=user.id, token=token)


@router.post("/auth/login", response_model=AuthResponse)
async def login(payload: LoginRequest, request: Request) -> AuthResponse:
    repository = get_auth_repository(request)
    user = repository.authenticate(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = repository.create_session(user.id)
    return AuthResponse(user_id=user.id, token=token)


@router.post("/threads", response_model=ThreadResponse)
async def create_thread(payload: ThreadCreateRequest, request: Request) -> ThreadResponse:
    user_id = get_current_user_id(request)
    return get_auth_repository(request).create_thread(user_id=user_id, title=payload.title)


@router.get("/threads", response_model=ThreadListResponse)
async def list_threads(request: Request) -> ThreadListResponse:
    user_id = get_current_user_id(request)
    return ThreadListResponse(threads=get_auth_repository(request).list_threads(user_id))


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(request: Request) -> ProfileResponse:
    user_id = get_current_user_id(request)
    auth_repository = get_auth_repository(request)
    stored_profile = auth_repository.get_profile(user_id)
    memories = getattr(request.app.state, "memory_repository", None)
    if memories is None:
        return ProfileResponse(user_id=user_id, **stored_profile)
    facts = memories.list_memories(user_id, limit=20)
    display_name = next(
        (memory.content.removeprefix("我叫") for memory in facts if memory.type == "identity"),
        stored_profile["display_name"],
    )
    summary = "\n".join(memory.content for memory in facts[:5])
    preferences = {"items": [memory.content for memory in facts if memory.type == "preference"]}
    traits = stored_profile["traits"]
    auth_repository.upsert_profile(
        user_id=user_id,
        display_name=display_name,
        summary=summary,
        preferences=preferences,
        traits=traits,
    )
    return ProfileResponse(
        user_id=user_id,
        display_name=display_name,
        summary=summary,
        preferences=preferences,
        traits=traits,
    )
