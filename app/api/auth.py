from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

from app.auth import AuthRepository, EmailCodeSender
from app.config import settings
from app.schemas.auth import (
    AuthResponse,
    EmailChangeRequest,
    EmailCodeRequest,
    EmailCodeResponse,
    LoginRequest,
    ProfileUpdateRequest,
    ProfileResponse,
    ThreadCreateRequest,
    ThreadListResponse,
    ThreadPinRequest,
    ThreadResponse,
    ThreadUpdateRequest,
)

router = APIRouter(tags=["auth"])

AVATAR_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_AVATAR_BYTES = 2 * 1024 * 1024


def get_auth_repository(request: Request) -> AuthRepository:
    repository = getattr(request.app.state, "auth_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="Auth store is not available")
    return repository


def get_email_code_sender(request: Request) -> EmailCodeSender:
    sender = getattr(request.app.state, "email_code_sender", None)
    if sender is None:
        sender = EmailCodeSender()
        request.app.state.email_code_sender = sender
    return sender


async def save_avatar_upload(user_id: str, avatar: UploadFile) -> tuple[Path, str]:
    mime_type = avatar.content_type or "application/octet-stream"
    extension = AVATAR_MIME_EXTENSIONS.get(mime_type)
    if extension is None:
        raise HTTPException(status_code=400, detail="Avatar must be JPEG, PNG, or WebP")

    content = await avatar.read(MAX_AVATAR_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Avatar file is empty")
    if len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail="Avatar exceeds 2 MB limit")

    try:
        image = Image.open(BytesIO(content))
        image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise HTTPException(status_code=400, detail="Avatar is not a valid image") from exc

    directory = settings.storage_path / "avatars" / user_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"avatar{extension}"
    path.write_bytes(content)
    return path, mime_type


def get_current_user_id(request: Request) -> str:
    authorization = request.headers.get("authorization")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    user_id = get_auth_repository(request).get_user_id_for_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user_id


@router.post("/auth/email-code", response_model=EmailCodeResponse)
async def request_email_code(payload: EmailCodeRequest, request: Request) -> EmailCodeResponse:
    repository = get_auth_repository(request)
    try:
        code = repository.issue_email_verification_code(payload.email, payload.purpose)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail="Verification code requested too recently") from exc
    get_email_code_sender(request).send_verification_code(payload.email, code, payload.purpose)
    return EmailCodeResponse(cooldown_seconds=settings.auth_email_code_cooldown_seconds)


@router.post("/auth/register", response_model=AuthResponse)
async def register(
    request: Request,
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    verification_code: str = Form(...),
    display_name: str | None = Form(default=None),
    avatar: UploadFile | None = File(default=None),
) -> AuthResponse:
    repository = get_auth_repository(request)
    if not repository.consume_email_verification_code(email, verification_code, "register"):
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")
    try:
        user = repository.create_user(
            username=username,
            password=password,
            display_name=display_name,
            email=email,
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Username or email already exists") from exc
    if avatar is not None and avatar.filename:
        path, mime_type = await save_avatar_upload(user.id, avatar)
        repository.set_user_avatar(user.id, path, mime_type)
    token = repository.create_session(user.id)
    return AuthResponse(user_id=user.id, token=token)


@router.post("/auth/login", response_model=AuthResponse)
async def login(payload: LoginRequest, request: Request) -> AuthResponse:
    repository = get_auth_repository(request)
    identifier = payload.identifier or payload.username
    if not identifier:
        raise HTTPException(status_code=422, detail="Identifier is required")
    user = repository.authenticate(identifier, payload.password)
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


@router.patch("/threads/{thread_id}", response_model=ThreadResponse)
async def rename_thread(thread_id: str, payload: ThreadUpdateRequest, request: Request) -> ThreadResponse:
    user_id = get_current_user_id(request)
    thread = get_auth_repository(request).rename_thread(user_id, thread_id, payload.title)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


@router.patch("/threads/{thread_id}/pin", response_model=ThreadResponse)
async def set_thread_pin(thread_id: str, payload: ThreadPinRequest, request: Request) -> ThreadResponse:
    user_id = get_current_user_id(request)
    thread = get_auth_repository(request).set_thread_pinned(user_id, thread_id, payload.pinned)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


@router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(thread_id: str, request: Request) -> Response:
    user_id = get_current_user_id(request)
    deleted = get_auth_repository(request).delete_thread(user_id, thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Thread not found")
    return Response(status_code=204)


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
        username=stored_profile["username"],
        email=stored_profile["email"],
        display_name=display_name,
        has_avatar=stored_profile["has_avatar"],
        summary=summary,
        preferences=preferences,
        traits=traits,
    )


@router.patch("/profile", response_model=ProfileResponse)
async def update_profile(payload: ProfileUpdateRequest, request: Request) -> ProfileResponse:
    user_id = get_current_user_id(request)
    auth_repository = get_auth_repository(request)
    stored_profile = auth_repository.get_profile(user_id)
    auth_repository.upsert_profile(
        user_id=user_id,
        display_name=payload.display_name,
        summary=stored_profile["summary"],
        preferences=stored_profile["preferences"],
        traits=stored_profile["traits"],
    )
    return ProfileResponse(
        user_id=user_id,
        username=stored_profile["username"],
        email=stored_profile["email"],
        display_name=payload.display_name,
        has_avatar=stored_profile["has_avatar"],
        summary=stored_profile["summary"],
        preferences=stored_profile["preferences"],
        traits=stored_profile["traits"],
    )


@router.patch("/profile/email", response_model=ProfileResponse)
async def update_profile_email(payload: EmailChangeRequest, request: Request) -> ProfileResponse:
    user_id = get_current_user_id(request)
    auth_repository = get_auth_repository(request)
    if not auth_repository.consume_email_verification_code(
        payload.email,
        payload.verification_code,
        "email_change",
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")
    try:
        auth_repository.update_user_email(user_id, payload.email)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Email already exists") from exc
    stored_profile = auth_repository.get_profile(user_id)
    return ProfileResponse(user_id=user_id, **stored_profile)


@router.post("/profile/avatar", response_model=ProfileResponse)
async def update_profile_avatar(request: Request, avatar: UploadFile = File(...)) -> ProfileResponse:
    user_id = get_current_user_id(request)
    auth_repository = get_auth_repository(request)
    path, mime_type = await save_avatar_upload(user_id, avatar)
    auth_repository.set_user_avatar(user_id, path, mime_type)
    stored_profile = auth_repository.get_profile(user_id)
    return ProfileResponse(user_id=user_id, **stored_profile)


@router.get("/profile/avatar")
async def get_profile_avatar(request: Request) -> FileResponse:
    user_id = get_current_user_id(request)
    avatar = get_auth_repository(request).get_user_avatar(user_id)
    if avatar is None:
        raise HTTPException(status_code=404, detail="Avatar not found")
    path, mime_type = avatar
    return FileResponse(path, media_type=mime_type)
