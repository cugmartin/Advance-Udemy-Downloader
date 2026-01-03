import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .auth import TokenManager
from .config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    BASE_DIR,
    DEFAULT_BEARER_TOKEN,
    DEFAULT_OUTPUT_DIR,
    HISTORY_FILE,
    HISTORY_LIMIT,
    KEYFILE_PATH,
    MAIN_SCRIPT,
    TOKEN_TTL_SECONDS,
)
from .history import HistoryStore
from .keyfile_manager import KeyEntry, KeyfileManager
from .tasks import TaskManager
from .udemy_api import UdemyInspectionError, inspect_course


logger = logging.getLogger("webapp.server")
app = FastAPI(title="Udemy Downloader Web Console")

templates = Jinja2Templates(directory=str(BASE_DIR / "webapp" / "templates"))
static_dir = BASE_DIR / "webapp" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

token_manager = TokenManager(TOKEN_TTL_SECONDS)
history_store = HistoryStore(HISTORY_FILE, HISTORY_LIMIT)
task_manager = TaskManager(history_store, BASE_DIR)
key_manager = KeyfileManager(KEYFILE_PATH)

security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: str


class KeyEntryPayload(BaseModel):
    kid: str = Field(..., description="Widevine KID (hex)")
    key: str = Field(..., description="Decryption key (hex)")


class PrecheckRequest(BaseModel):
    course_url: str
    bearer_token: str


class DownloadRequest(BaseModel):
    course_url: str
    bearer_token: str
    output_dir: Optional[str] = None
    lang: Optional[str] = Field(default=None, description="Caption language")
    quality: Optional[int] = None
    concurrent_downloads: Optional[int] = Field(default=None, ge=1, le=30)
    download_assets: bool = False
    download_captions: bool = True
    download_quizzes: bool = False
    skip_lectures: bool = False
    keep_vtt: bool = False
    skip_hls: bool = False
    use_h265: bool = False
    use_nvenc: bool = False
    use_continuous_lecture_numbers: bool = False
    chapter_filter: Optional[str] = None
    key_entries: List[KeyEntryPayload] = Field(default_factory=list)
    auto_zip: bool = False


def _mask_token(token: str) -> str:
    if not token:
        return "(empty)"
    if len(token) <= 8:
        return token[:2] + "***"
    return f"{token[:4]}...{token[-4:]}"


def build_command(payload: DownloadRequest) -> List[str]:
    cmd = [sys.executable, str(MAIN_SCRIPT), "-c", payload.course_url, "-b", payload.bearer_token]
    output_dir = payload.output_dir or str(DEFAULT_OUTPUT_DIR)
    cmd.extend(["--out", output_dir])

    if payload.lang:
        cmd.extend(["--lang", payload.lang])
    if payload.quality:
        cmd.extend(["--quality", str(payload.quality)])
    if payload.concurrent_downloads:
        cmd.extend(["--concurrent-downloads", str(payload.concurrent_downloads)])
    if payload.chapter_filter:
        cmd.extend(["--chapter", payload.chapter_filter])

    flag_map = {
        "download_assets": "--download-assets",
        "download_captions": "--download-captions",
        "download_quizzes": "--download-quizzes",
        "skip_lectures": "--skip-lectures",
        "keep_vtt": "--keep-vtt",
        "skip_hls": "--skip-hls",
        "use_h265": "--use-h265",
        "use_nvenc": "--use-nvenc",
        "use_continuous_lecture_numbers": "--continue-lecture-numbers",
    }
    for field_name, flag in flag_map.items():
        if getattr(payload, field_name):
            cmd.append(flag)

    if payload.auto_zip:
        cmd.append("--auto-zip")

    return cmd


def get_token_from_request(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
):
    token_value = request.query_params.get("token")
    if not token_value and credentials:
        token_value = credentials.credentials
    if not token_value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    session = token_manager.validate(token_value)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return session


@app.on_event("startup")
async def configure_manager():
    loop = asyncio.get_running_loop()
    task_manager.set_loop(loop)


@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "default_bearer": DEFAULT_BEARER_TOKEN or ""},
    )


@app.post("/api/login", response_model=LoginResponse)
async def login(payload: LoginRequest):
    if payload.username != ADMIN_USERNAME or payload.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    session = token_manager.issue_token(payload.username)
    return LoginResponse(token=session.token, expires_at=session.expires_at.isoformat())


@app.get("/api/history")
async def get_history(_: str = Depends(get_token_from_request)):
    return history_store.list_items()


@app.get("/api/tasks")
async def list_tasks(_: str = Depends(get_token_from_request)):
    tasks = task_manager.list_tasks()
    return [
        {
            "id": task.id,
            "course_url": task.course_url,
            "status": task.status,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        }
        for task in tasks
    ]


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str, _: str = Depends(get_token_from_request)):
    try:
        task = task_manager.get_task(task_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return {
        "id": task.id,
        "course_url": task.course_url,
        "status": task.status,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


@app.get("/api/tasks/{task_id}/logs")
async def stream_logs(task_id: str, request: Request, session=Depends(get_token_from_request)):
    try:
        task = task_manager.get_task(task_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    queue = task.subscribe()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                line = await queue.get()
                if line is None:
                    yield "event: end\ndata: stream-closed\n\n"
                    break
                payload = line.replace("\r", "").replace("\n", " ")
                yield f"data: {payload}\n\n"
        finally:
            task.unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/precheck")
async def precheck(payload: PrecheckRequest, _: str = Depends(get_token_from_request)):
    logger.info("Precheck start course=%s token=%s", payload.course_url, _mask_token(payload.bearer_token))
    try:
        data = inspect_course(payload.course_url, payload.bearer_token)
    except UdemyInspectionError as exc:
        logger.warning("Precheck failed course=%s error=%s", payload.course_url, exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    logger.info("Precheck success course=%s is_drm=%s", payload.course_url, data.get("is_drm"))
    return data


@app.post("/api/download")
async def start_download(payload: DownloadRequest, _: str = Depends(get_token_from_request)):
    try:
        inspection = inspect_course(payload.course_url, payload.bearer_token)
    except UdemyInspectionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if inspection.get("is_drm") and not payload.key_entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="此课程包含 DRM 视频，请先提供 keyfile.json 的 KID/KEY 后再试。",
        )

    if payload.key_entries:
        key_entries = [KeyEntry(kid=item.kid, key=item.key) for item in payload.key_entries]
        key_manager.upsert_keys(key_entries)

    command = build_command(payload)
    task = task_manager.create_task(
        payload.course_url,
        command,
        is_drm=inspection.get("is_drm"),
    )
    task_manager.start_task(task)

    return {"task_id": task.id, "status": task.status}
