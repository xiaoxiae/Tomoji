import asyncio
import base64
import io
import logging
import unicodedata
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.config import (
    CORS_ORIGINS,
    DEFAULT_KEEP_ACCESSORIES,
    DEFAULT_KEEP_BACKGROUND,
    DEFAULT_KEEP_CLOTHES,
    DEFAULT_OUTPUT_SIZE,
    DEFAULT_PADDING,
    EMOJI_CATEGORIES,
    EMOJI_LIST,
    RATE_LIMIT_CAPTURE,
    RATE_LIMIT_CAPTURE_IMAGE,
    RATE_LIMIT_CLEAR_ALL,
    RATE_LIMIT_DELETE,
    RATE_LIMIT_DOWNLOAD,
    RATE_LIMIT_EMOJIS,
    RATE_LIMIT_EXPORT,
    RATE_LIMIT_GALLERY,
    RATE_LIMIT_PREVIEW,
    RATE_LIMIT_SESSION_CREATE,
    RATE_LIMIT_SESSION_DELETE,
    RATE_LIMIT_SESSION_VALIDATE,
    RATE_LIMIT_SETTINGS,
)
from backend.services.face_detector import detect_and_crop_face, _ensure_model
from backend.services.font_builder import build_emoji_font
from backend.session import (
    cleanup_expired_sessions,
    create_session,
    delete_session,
    get_session_captures_dir,
    get_session_dir,
    get_session_settings_file,
    get_session_timestamps,
    persist_session,
    require_session,
    update_last_capture_edit,
    update_last_generation,
    validate_session,
)

limiter = Limiter(key_func=get_remote_address)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429, content={"detail": f"Rate limit exceeded: {exc.detail}"}
    )


async def cleanup_task():
    """Background task to clean up expired sessions every hour."""
    while True:
        try:
            removed = cleanup_expired_sessions()
            if removed > 0:
                logger.info(f"Cleaned up {removed} expired sessions")
        except Exception as e:
            logger.error(f"Session cleanup error: {e}")
        await asyncio.sleep(3600)  # 1 hour


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown tasks."""
    _ensure_model()
    task = asyncio.create_task(cleanup_task())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Tomoji API", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def emoji_to_filename(emoji: str) -> str:
    """Convert emoji to hex codepoint filename."""
    return "-".join(f"{ord(c):x}" for c in emoji)


class CaptureRequest(BaseModel):
    image: str  # base64 encoded image
    padding: Optional[float] = Field(default=DEFAULT_PADDING, ge=0.0, le=1.0)
    keep_background: Optional[bool] = DEFAULT_KEEP_BACKGROUND
    keep_clothes: Optional[bool] = DEFAULT_KEEP_CLOTHES
    keep_accessories: Optional[bool] = DEFAULT_KEEP_ACCESSORIES


class SaveCaptureRequest(BaseModel):
    image: str  # base64 encoded processed image (already cropped)


class ExportRequest(BaseModel):
    font_name: Optional[str] = "Tomoji"


class SettingsModel(BaseModel):
    padding: float = Field(default=DEFAULT_PADDING, ge=0.0, le=1.0)
    keep_background: bool = DEFAULT_KEEP_BACKGROUND
    keep_clothes: bool = DEFAULT_KEEP_CLOTHES
    keep_accessories: bool = DEFAULT_KEEP_ACCESSORIES


def load_settings(session_id: str) -> dict:
    """Load settings from YAML file or return defaults."""
    settings_file = get_session_settings_file(session_id)
    if settings_file.exists():
        try:
            with open(settings_file, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load settings for session {session_id}: {e}")
    return {}


def save_settings_to_file(session_id: str, settings: dict) -> None:
    """Save settings to YAML file."""
    persist_session(session_id)
    settings_file = get_session_settings_file(session_id)
    with open(settings_file, "w") as f:
        yaml.safe_dump(settings, f)


def get_custom_emojis_file(session_id: str) -> Path:
    """Get path to custom emojis file for a session."""
    return get_session_dir(session_id) / "custom_emojis.yaml"


def load_custom_emojis(session_id: str) -> list[dict]:
    """Load custom emojis for a session."""
    custom_file = get_custom_emojis_file(session_id)
    if custom_file.exists():
        try:
            with open(custom_file, "r") as f:
                data = yaml.safe_load(f) or {}
                return data.get("emojis", [])
        except Exception as e:
            logger.warning(
                f"Failed to load custom emojis for session {session_id}: {e}"
            )
    return []


def save_custom_emojis(session_id: str, emojis: list[dict]) -> None:
    """Save custom emojis for a session."""
    persist_session(session_id)
    custom_file = get_custom_emojis_file(session_id)
    with open(custom_file, "w") as f:
        yaml.safe_dump({"emojis": emojis}, f)


def add_custom_emoji(session_id: str, emoji: str, name: str = "") -> dict:
    """Add a custom emoji to the session. Returns the emoji info."""
    custom_emojis = load_custom_emojis(session_id)
    codepoint = emoji_to_filename(emoji)

    for e in custom_emojis:
        if e["emoji"] == emoji:
            return e

    emoji_info = {
        "emoji": emoji,
        "codepoint": codepoint,
        "name": name or f"custom {emoji}",
    }
    custom_emojis.append(emoji_info)
    save_custom_emojis(session_id, custom_emojis)
    return emoji_info


def remove_custom_emoji(session_id: str, emoji: str) -> bool:
    """Remove a custom emoji from the session."""
    custom_emojis = load_custom_emojis(session_id)
    original_len = len(custom_emojis)
    custom_emojis = [e for e in custom_emojis if e["emoji"] != emoji]
    if len(custom_emojis) < original_len:
        save_custom_emojis(session_id, custom_emojis)
        return True
    return False


def is_valid_emoji(text: str) -> bool:
    """Check if text is a single valid emoji character."""
    if len(text) != 1:
        return False
    char = text[0]
    # Check if it's in emoji ranges or has emoji presentation
    if unicodedata.category(char) in ("So", "Sk") or ord(char) >= 0x1F300:
        return True
    return False


def resolve_emoji(emoji: str) -> tuple[str, bool]:
    """Resolve emoji from input (emoji char or codepoint).

    Returns (resolved_emoji, is_custom) or raises HTTPException if invalid.
    """
    if emoji in EMOJI_LIST:
        return emoji, False
    # Check if input is a codepoint that matches a standard emoji
    matching = [e for e in EMOJI_LIST if emoji_to_filename(e) == emoji]
    if matching:
        return matching[0], False
    # Check if it's a valid custom emoji
    if is_valid_emoji(emoji):
        return emoji, True
    raise HTTPException(status_code=400, detail="Invalid emoji")


@app.post("/api/session")
@limiter.limit(RATE_LIMIT_SESSION_CREATE)
async def create_new_session(request: Request):
    """Create a new session and return the session ID."""
    session_id = create_session()
    return {"session_id": session_id}


@app.get("/api/session/{session_id}/validate")
@limiter.limit(RATE_LIMIT_SESSION_VALIDATE)
async def validate_session_endpoint(request: Request, session_id: str):
    """Check if a session is valid."""
    is_valid = validate_session(session_id)
    return {"valid": is_valid, "session_id": session_id}


@app.delete("/api/session/{session_id}")
@limiter.limit(RATE_LIMIT_SESSION_DELETE)
async def delete_session_endpoint(request: Request, session_id: str):
    """Delete a session and all its data."""
    existed = delete_session(session_id)
    if not existed:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"success": True, "session_id": session_id}


@app.get("/api/emojis")
@limiter.limit(RATE_LIMIT_EMOJIS)
async def list_emojis(request: Request):
    """List all emojis available for capture, organized by category."""
    categories = []
    for category in EMOJI_CATEGORIES:
        cat_emojis = []
        for e in category["emojis"]:
            cat_emojis.append(
                {
                    "emoji": e["emoji"],
                    "codepoint": emoji_to_filename(e["emoji"]),
                    "name": e["name"],
                }
            )
        categories.append(
            {
                "id": category["id"],
                "name": category["name"],
                "emojis": cat_emojis,
            }
        )
    return {"categories": categories}


@app.get("/api/{session_id}/settings")
@limiter.limit(RATE_LIMIT_SETTINGS)
async def get_settings(request: Request, session_id: str):
    """Get current settings for a session."""
    require_session(session_id)
    stored = load_settings(session_id)
    return SettingsModel(
        padding=stored.get("padding", DEFAULT_PADDING),
        keep_background=stored.get("keep_background", DEFAULT_KEEP_BACKGROUND),
        keep_clothes=stored.get("keep_clothes", DEFAULT_KEEP_CLOTHES),
        keep_accessories=stored.get("keep_accessories", DEFAULT_KEEP_ACCESSORIES),
    )


@app.put("/api/{session_id}/settings")
@limiter.limit(RATE_LIMIT_SETTINGS)
async def update_settings(request: Request, session_id: str, settings: SettingsModel):
    """Update settings for a session."""
    require_session(session_id)
    save_settings_to_file(session_id, settings.model_dump())
    return {"success": True, **settings.model_dump()}


@app.get("/api/{session_id}/gallery")
@limiter.limit(RATE_LIMIT_GALLERY)
async def get_gallery(request: Request, session_id: str):
    """List all captured emojis for a session with inline image data."""
    require_session(session_id)
    captures_dir = get_session_captures_dir(session_id)
    captured = []
    for emoji in EMOJI_LIST:
        filename = emoji_to_filename(emoji)
        capture_path = captures_dir / f"{filename}.png"
        if capture_path.exists():
            image_data = capture_path.read_bytes()
            image_base64 = base64.b64encode(image_data).decode("utf-8")
            captured.append(
                {
                    "emoji": emoji,
                    "codepoint": filename,
                    "image_data": f"data:image/png;base64,{image_base64}",
                }
            )

    custom_emojis = load_custom_emojis(session_id)
    for custom in custom_emojis:
        filename = custom["codepoint"]
        capture_path = captures_dir / f"{filename}.png"
        if capture_path.exists():
            image_data = capture_path.read_bytes()
            image_base64 = base64.b64encode(image_data).decode("utf-8")
            captured.append(
                {
                    "emoji": custom["emoji"],
                    "codepoint": filename,
                    "image_data": f"data:image/png;base64,{image_base64}",
                    "custom": True,
                }
            )

    timestamps = get_session_timestamps(session_id)
    return {
        "captured": captured,
        "total": len(EMOJI_LIST),
        "custom_emojis": custom_emojis,
        "last_capture_edit": timestamps["last_capture_edit"],
        "last_generation": timestamps["last_generation"],
    }


@app.post("/api/{session_id}/capture/{emoji}/preview")
@limiter.limit(RATE_LIMIT_PREVIEW)
async def preview_capture(
    request: Request, session_id: str, emoji: str, body: CaptureRequest
):
    """Upload photo, detect face, and crop - returns base64 result for preview."""
    require_session(session_id)
    emoji, _ = resolve_emoji(emoji)

    try:
        image_data = body.image
        if "," in image_data:
            image_data = image_data.split(",")[1]
        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image data: {str(e)}")

    try:
        cropped = detect_and_crop_face(
            image,
            padding=body.padding,
            output_size=DEFAULT_OUTPUT_SIZE,
            keep_background=body.keep_background,
            keep_clothes=body.keep_clothes,
            keep_accessories=body.keep_accessories,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    buffer = io.BytesIO()
    cropped.save(buffer, format="PNG")
    buffer.seek(0)
    preview_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    return {
        "success": True,
        "emoji": emoji,
        "codepoint": emoji_to_filename(emoji),
        "preview_image": f"data:image/png;base64,{preview_base64}",
    }


@app.post("/api/{session_id}/capture/{emoji}")
@limiter.limit(RATE_LIMIT_CAPTURE)
async def save_capture(
    request: Request, session_id: str, emoji: str, body: SaveCaptureRequest
):
    """Save an already-processed image."""
    require_session(session_id)
    captures_dir = get_session_captures_dir(session_id)
    emoji, is_custom = resolve_emoji(emoji)
    if is_custom:
        add_custom_emoji(session_id, emoji)

    try:
        image_data = body.image
        if "," in image_data:
            image_data = image_data.split(",")[1]
        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image data: {str(e)}")

    filename = emoji_to_filename(emoji)
    persist_session(session_id)
    captures_dir.mkdir(parents=True, exist_ok=True)
    output_path = captures_dir / f"{filename}.png"
    image.save(output_path, "PNG")

    update_last_capture_edit(session_id)

    return {
        "success": True,
        "emoji": emoji,
        "codepoint": filename,
        "capture_url": f"/api/{session_id}/capture/{filename}/image",
    }


@app.get("/api/{session_id}/capture/{codepoint}/image")
@limiter.limit(RATE_LIMIT_CAPTURE_IMAGE)
async def get_capture_image(request: Request, session_id: str, codepoint: str):
    """Get the captured image for an emoji."""
    require_session(session_id)
    captures_dir = get_session_captures_dir(session_id)
    capture_path = captures_dir / f"{codepoint}.png"
    if not capture_path.exists():
        raise HTTPException(status_code=404, detail="Capture not found")
    return FileResponse(capture_path, media_type="image/png")


@app.delete("/api/{session_id}/capture/{emoji}")
@limiter.limit(RATE_LIMIT_DELETE)
async def delete_capture(request: Request, session_id: str, emoji: str):
    """Delete a capture for retake."""
    require_session(session_id)
    captures_dir = get_session_captures_dir(session_id)

    is_custom = False
    if emoji in EMOJI_LIST:
        filename = emoji_to_filename(emoji)
    else:
        matching = [e for e in EMOJI_LIST if emoji_to_filename(e) == emoji]
        if matching:
            filename = emoji
            emoji = matching[0]
        else:
            custom_emojis = load_custom_emojis(session_id)
            custom_match = [
                c
                for c in custom_emojis
                if c["emoji"] == emoji or c["codepoint"] == emoji
            ]
            if custom_match:
                is_custom = True
                filename = custom_match[0]["codepoint"]
                emoji = custom_match[0]["emoji"]
            else:
                raise HTTPException(status_code=400, detail="Invalid emoji")

    capture_path = captures_dir / f"{filename}.png"
    if capture_path.exists():
        capture_path.unlink()
        update_last_capture_edit(session_id)
        if is_custom:
            remove_custom_emoji(session_id, emoji)

    return {"success": True, "emoji": emoji}


@app.delete("/api/{session_id}/captures")
@limiter.limit(RATE_LIMIT_CLEAR_ALL)
async def clear_all_captures(request: Request, session_id: str):
    """Delete all captures for a session."""
    require_session(session_id)
    captures_dir = get_session_captures_dir(session_id)

    deleted_count = 0
    for capture_file in captures_dir.glob("*.png"):
        capture_file.unlink()
        deleted_count += 1

    font_path = captures_dir / "tomoji.woff2"
    if font_path.exists():
        font_path.unlink()

    save_custom_emojis(session_id, [])

    if deleted_count > 0:
        update_last_capture_edit(session_id)

    return {"success": True, "deleted_count": deleted_count}


@app.post("/api/{session_id}/export")
@limiter.limit(RATE_LIMIT_EXPORT)
async def export_font(request: Request, session_id: str, body: ExportRequest):
    """Generate the emoji font from captures."""
    require_session(session_id)
    captures_dir = get_session_captures_dir(session_id)

    captures = {}
    for emoji in EMOJI_LIST:
        filename = emoji_to_filename(emoji)
        capture_path = captures_dir / f"{filename}.png"
        if capture_path.exists():
            captures[emoji] = capture_path

    custom_emojis = load_custom_emojis(session_id)
    for custom in custom_emojis:
        filename = custom["codepoint"]
        capture_path = captures_dir / f"{filename}.png"
        if capture_path.exists():
            captures[custom["emoji"]] = capture_path

    if not captures:
        raise HTTPException(status_code=400, detail="No captures to export")

    try:
        build_emoji_font(captures, body.font_name, output_dir=captures_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Font generation failed: {str(e)}")

    update_last_generation(session_id)
    timestamps = get_session_timestamps(session_id)

    return {
        "success": True,
        "captured_count": len(captures),
        "total_emojis": len(EMOJI_LIST),
        "font_url": f"/api/{session_id}/font.woff2",
        "last_generation": timestamps["last_generation"],
    }


@app.get("/api/{session_id}/font.woff2")
@limiter.limit(RATE_LIMIT_DOWNLOAD)
async def get_font(request: Request, session_id: str):
    """Serve the generated .woff2 font with CDN-like caching."""
    require_session(session_id)
    captures_dir = get_session_captures_dir(session_id)
    font_path = captures_dir / "tomoji.woff2"
    if not font_path.exists():
        raise HTTPException(status_code=404, detail="Font not generated yet")

    stat = font_path.stat()
    etag = f'"{int(stat.st_mtime)}-{stat.st_size}"'

    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match == etag:
        return JSONResponse(
            status_code=304,
            content=None,
            headers={
                "ETag": etag,
                "Cache-Control": "public, max-age=31536000, immutable",
            },
        )

    return FileResponse(
        font_path,
        media_type="font/woff2",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": etag,
        },
    )


@app.get("/api/{session_id}/images.zip")
@limiter.limit(RATE_LIMIT_DOWNLOAD)
async def download_images_zip(
    request: Request, session_id: str, name: Optional[str] = None
):
    """Download all captured images as a ZIP file."""
    require_session(session_id)
    captures_dir = get_session_captures_dir(session_id)

    png_files = list(captures_dir.glob("*.png"))
    if not png_files:
        raise HTTPException(status_code=400, detail="No captures to download")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for png_path in png_files:
            codepoint = png_path.stem
            zf.write(png_path, f"{codepoint}.png")

    zip_buffer.seek(0)

    zip_filename = f"{quote(name, safe='')}.zip" if name else "images.zip"

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_filename}"',
        },
    )


FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"
if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve SPA - return index.html for all non-API routes."""
        file_path = FRONTEND_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIR / "index.html")
