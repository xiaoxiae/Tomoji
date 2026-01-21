import logging
import random
import shutil
import string
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from fastapi import HTTPException

from backend.config import SESSION_EXPIRY_DAYS, SESSIONS_DIR

logger = logging.getLogger(__name__)

SESSION_ID_LENGTH = 8
SESSION_ID_CHARS = string.ascii_lowercase + string.digits


def is_valid_session_id_format(session_id: str) -> bool:
    """Check if session ID has valid format (8 lowercase alphanumeric chars)."""
    if len(session_id) != SESSION_ID_LENGTH:
        return False
    return all(c in SESSION_ID_CHARS for c in session_id)


def generate_session_id() -> str:
    """Generate an 8-character alphanumeric session ID."""
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choices(chars, k=8))


def get_session_dir(session_id: str) -> Path:
    """Get the directory for a session."""
    return SESSIONS_DIR / session_id


def get_session_captures_dir(session_id: str) -> Path:
    """Get the captures directory for a session."""
    return get_session_dir(session_id) / "captures"


def get_session_settings_file(session_id: str) -> Path:
    """Get the settings file path for a session."""
    return get_session_dir(session_id) / "settings.yaml"


def get_session_metadata_file(session_id: str) -> Path:
    """Get the session metadata file path."""
    return get_session_dir(session_id) / "session.yaml"


def create_session() -> str:
    """Generate a new session ID. No files created until data is persisted."""
    session_id = generate_session_id()

    # Ensure unique session ID (avoid collision with existing persisted sessions)
    while get_session_dir(session_id).exists():
        session_id = generate_session_id()

    return session_id


def validate_session(session_id: str) -> bool:
    """Check if a session ID has valid format. Sessions are valid if format is correct."""
    return is_valid_session_id_format(session_id)


def is_session_persisted(session_id: str) -> bool:
    """Check if a session has persisted data on disk."""
    return get_session_dir(session_id).exists()


def is_session_expired(session_id: str) -> bool:
    """Check if a persisted session is expired based on last_activity."""
    metadata_file = get_session_metadata_file(session_id)
    if not metadata_file.exists():
        return False  # Non-persisted sessions can't expire

    try:
        with open(metadata_file, "r") as f:
            metadata = yaml.safe_load(f) or {}

        last_activity = metadata.get("last_activity")
        if not last_activity:
            return True  # No activity timestamp = consider expired

        last_activity_dt = datetime.fromisoformat(last_activity)
        expiry_threshold = datetime.now(UTC) - timedelta(days=SESSION_EXPIRY_DAYS)

        return last_activity_dt <= expiry_threshold
    except Exception:
        return True  # Error reading = consider expired


def update_session_activity(session_id: str) -> None:
    """Update the last_activity timestamp for a session."""
    metadata_file = get_session_metadata_file(session_id)

    if not metadata_file.exists():
        return

    try:
        with open(metadata_file, "r") as f:
            metadata = yaml.safe_load(f) or {}

        metadata["last_activity"] = datetime.now(UTC).isoformat()

        with open(metadata_file, "w") as f:
            yaml.safe_dump(metadata, f)
    except Exception as e:
        logger.warning(f"Failed to update session activity for {session_id}: {e}")


def require_session(session_id: str) -> None:
    """Validate session format and raise HTTP 404 if invalid."""
    if not validate_session(session_id):
        raise HTTPException(status_code=404, detail="Invalid session ID format")
    update_session_activity(session_id)


def persist_session(session_id: str) -> None:
    """Ensure session directory and metadata file exist. Call before writing any data."""
    session_dir = get_session_dir(session_id)
    metadata_file = get_session_metadata_file(session_id)

    if not session_dir.exists():
        session_dir.mkdir(parents=True, exist_ok=True)

    if not metadata_file.exists():
        now = datetime.now(UTC).isoformat()
        metadata = {
            "created_at": now,
            "last_activity": now,
        }
        with open(metadata_file, "w") as f:
            yaml.safe_dump(metadata, f)


def cleanup_expired_sessions() -> int:
    """Remove sessions older than SESSION_EXPIRY_DAYS. Returns count of removed sessions."""
    if not SESSIONS_DIR.exists():
        return 0

    removed_count = 0
    expiry_threshold = datetime.now(UTC) - timedelta(days=SESSION_EXPIRY_DAYS)

    for session_dir in SESSIONS_DIR.iterdir():
        if not session_dir.is_dir():
            continue

        metadata_file = session_dir / "session.yaml"
        should_remove = False

        if not metadata_file.exists():
            # No metadata, remove the session
            should_remove = True
        else:
            try:
                with open(metadata_file, "r") as f:
                    metadata = yaml.safe_load(f) or {}

                last_activity = metadata.get("last_activity")
                if not last_activity:
                    should_remove = True
                else:
                    last_activity_dt = datetime.fromisoformat(last_activity)
                    if last_activity_dt <= expiry_threshold:
                        should_remove = True
            except Exception as e:
                logger.warning(
                    f"Failed to read session metadata for {session_dir.name}, marking for removal: {e}"
                )
                should_remove = True

        if should_remove:
            _remove_session_dir(session_dir)
            removed_count += 1

    return removed_count


def _remove_session_dir(session_dir: Path) -> None:
    """Recursively remove a session directory."""
    try:
        shutil.rmtree(session_dir)
    except Exception as e:
        logger.warning(f"Failed to remove session directory {session_dir}: {e}")


def delete_session(session_id: str) -> bool:
    """Delete a session and all its data. Returns True if session existed."""
    session_dir = get_session_dir(session_id)
    if not session_dir.exists():
        return False
    _remove_session_dir(session_dir)
    return True


def _update_session_timestamp(session_id: str, key: str) -> None:
    """Update a timestamp field in session metadata."""
    metadata_file = get_session_metadata_file(session_id)

    if not metadata_file.exists():
        return

    try:
        with open(metadata_file, "r") as f:
            metadata = yaml.safe_load(f) or {}

        metadata[key] = datetime.now(UTC).isoformat()

        with open(metadata_file, "w") as f:
            yaml.safe_dump(metadata, f)
    except Exception as e:
        logger.warning(f"Failed to update {key} for {session_id}: {e}")


def update_last_capture_edit(session_id: str) -> None:
    """Update the last_capture_edit timestamp for a session."""
    _update_session_timestamp(session_id, "last_capture_edit")


def update_last_generation(session_id: str) -> None:
    """Update the last_generation timestamp for a session."""
    _update_session_timestamp(session_id, "last_generation")


def get_session_timestamps(session_id: str) -> dict:
    """Get the last_capture_edit and last_generation timestamps for a session."""
    metadata_file = get_session_metadata_file(session_id)

    if not metadata_file.exists():
        return {"last_capture_edit": None, "last_generation": None}

    try:
        with open(metadata_file, "r") as f:
            metadata = yaml.safe_load(f) or {}

        return {
            "last_capture_edit": metadata.get("last_capture_edit"),
            "last_generation": metadata.get("last_generation"),
        }
    except Exception:
        return {"last_capture_edit": None, "last_generation": None}
