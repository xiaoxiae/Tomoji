"""Tests for session management functionality."""

import time
from datetime import UTC, datetime, timedelta

import pytest
import yaml

from backend.config import SESSION_EXPIRY_DAYS
from backend.session import (
    SESSION_ID_CHARS,
    SESSION_ID_LENGTH,
    cleanup_expired_sessions,
    create_session,
    delete_session,
    generate_session_id,
    get_session_captures_dir,
    get_session_dir,
    get_session_metadata_file,
    get_session_settings_file,
    get_session_timestamps,
    is_session_expired,
    is_session_persisted,
    is_valid_session_id_format,
    persist_session,
    require_session,
    update_last_capture_edit,
    update_last_generation,
    update_session_activity,
    validate_session,
)


class TestSessionIdFormat:
    """Tests for session ID format validation."""

    def test_valid_session_id(self):
        """Valid 8-char lowercase alphanumeric IDs should pass."""
        assert is_valid_session_id_format("abc12345") is True
        assert is_valid_session_id_format("00000000") is True
        assert is_valid_session_id_format("zzzzzzzz") is True
        assert is_valid_session_id_format("a1b2c3d4") is True

    def test_invalid_length(self):
        """IDs with wrong length should fail."""
        assert is_valid_session_id_format("") is False
        assert is_valid_session_id_format("abc1234") is False  # 7 chars
        assert is_valid_session_id_format("abc123456") is False  # 9 chars

    def test_invalid_characters(self):
        """IDs with invalid characters should fail."""
        assert is_valid_session_id_format("ABC12345") is False  # uppercase
        assert is_valid_session_id_format("abc-1234") is False  # dash
        assert is_valid_session_id_format("abc_1234") is False  # underscore
        assert is_valid_session_id_format("abc 1234") is False  # space
        assert is_valid_session_id_format("abc!@#$%") is False  # special chars


class TestGenerateSessionId:
    """Tests for session ID generation."""

    def test_generates_correct_length(self):
        """Generated ID should be 8 characters."""
        session_id = generate_session_id()
        assert len(session_id) == SESSION_ID_LENGTH

    def test_uses_valid_characters(self):
        """Generated ID should only use lowercase alphanumeric."""
        for _ in range(100):  # Generate many to ensure consistency
            session_id = generate_session_id()
            assert all(c in SESSION_ID_CHARS for c in session_id)

    def test_generates_unique_ids(self):
        """Generated IDs should be unique (probabilistically)."""
        ids = {generate_session_id() for _ in range(1000)}
        assert len(ids) == 1000  # All should be unique


class TestSessionPathHelpers:
    """Tests for session path helper functions."""

    def test_get_session_dir(self, tmp_path, monkeypatch):
        """Should return correct session directory path."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        path = get_session_dir("abc12345")
        assert path == tmp_path / "abc12345"

    def test_get_session_captures_dir(self, tmp_path, monkeypatch):
        """Should return correct captures directory path."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        path = get_session_captures_dir("abc12345")
        assert path == tmp_path / "abc12345" / "captures"

    def test_get_session_settings_file(self, tmp_path, monkeypatch):
        """Should return correct settings file path."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        path = get_session_settings_file("abc12345")
        assert path == tmp_path / "abc12345" / "settings.yaml"

    def test_get_session_metadata_file(self, tmp_path, monkeypatch):
        """Should return correct metadata file path."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        path = get_session_metadata_file("abc12345")
        assert path == tmp_path / "abc12345" / "session.yaml"


class TestCreateSession:
    """Tests for session creation."""

    def test_creates_valid_session_id(self, tmp_path, monkeypatch):
        """Created session ID should be valid."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        session_id = create_session()
        assert is_valid_session_id_format(session_id)

    def test_does_not_create_files(self, tmp_path, monkeypatch):
        """Session creation should not create any files."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        session_id = create_session()
        session_dir = tmp_path / session_id
        assert not session_dir.exists()

    def test_avoids_collision_with_existing(self, tmp_path, monkeypatch):
        """Should generate new ID if collision occurs."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)

        # Create a directory with a predictable name
        existing_id = "test1234"
        (tmp_path / existing_id).mkdir()

        # Mock generate_session_id to return existing ID first, then unique
        call_count = [0]
        original_generate = generate_session_id

        def mock_generate():
            call_count[0] += 1
            if call_count[0] == 1:
                return existing_id
            return original_generate()

        monkeypatch.setattr("backend.session.generate_session_id", mock_generate)

        session_id = create_session()
        assert session_id != existing_id
        assert call_count[0] >= 2


class TestValidateSession:
    """Tests for session validation."""

    def test_validates_format_only(self):
        """Validation should only check format, not existence."""
        assert validate_session("abc12345") is True
        assert validate_session("invalid!") is False


class TestIsSessionPersisted:
    """Tests for checking if session has data on disk."""

    def test_returns_false_for_nonexistent(self, tmp_path, monkeypatch):
        """Should return False for non-persisted session."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        assert is_session_persisted("abc12345") is False

    def test_returns_true_for_existing(self, tmp_path, monkeypatch):
        """Should return True for persisted session."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        (tmp_path / "abc12345").mkdir()
        assert is_session_persisted("abc12345") is True


class TestIsSessionExpired:
    """Tests for session expiry checking."""

    def test_non_persisted_not_expired(self, tmp_path, monkeypatch):
        """Non-persisted sessions should not be considered expired."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        assert is_session_expired("abc12345") is False

    def test_recent_session_not_expired(self, tmp_path, monkeypatch):
        """Session with recent activity should not be expired."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        session_dir = tmp_path / "abc12345"
        session_dir.mkdir()

        metadata = {
            "created_at": datetime.now(UTC).isoformat(),
            "last_activity": datetime.now(UTC).isoformat(),
        }
        with open(session_dir / "session.yaml", "w") as f:
            yaml.safe_dump(metadata, f)

        assert is_session_expired("abc12345") is False

    def test_old_session_is_expired(self, tmp_path, monkeypatch):
        """Session with old activity should be expired."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        session_dir = tmp_path / "abc12345"
        session_dir.mkdir()

        old_time = datetime.now(UTC) - timedelta(days=SESSION_EXPIRY_DAYS + 1)
        metadata = {
            "created_at": old_time.isoformat(),
            "last_activity": old_time.isoformat(),
        }
        with open(session_dir / "session.yaml", "w") as f:
            yaml.safe_dump(metadata, f)

        assert is_session_expired("abc12345") is True

    def test_no_activity_timestamp_is_expired(self, tmp_path, monkeypatch):
        """Session without last_activity should be considered expired."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        session_dir = tmp_path / "abc12345"
        session_dir.mkdir()

        metadata = {"created_at": datetime.now(UTC).isoformat()}
        with open(session_dir / "session.yaml", "w") as f:
            yaml.safe_dump(metadata, f)

        assert is_session_expired("abc12345") is True

    def test_corrupted_metadata_is_expired(self, tmp_path, monkeypatch):
        """Session with corrupted metadata should be considered expired."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        session_dir = tmp_path / "abc12345"
        session_dir.mkdir()

        with open(session_dir / "session.yaml", "w") as f:
            f.write("invalid: yaml: content: {{{{")

        assert is_session_expired("abc12345") is True


class TestPersistSession:
    """Tests for session persistence."""

    def test_creates_directory_and_metadata(self, tmp_path, monkeypatch):
        """Should create session directory and metadata file."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        persist_session("abc12345")

        session_dir = tmp_path / "abc12345"
        assert session_dir.exists()
        assert (session_dir / "session.yaml").exists()

    def test_metadata_has_timestamps(self, tmp_path, monkeypatch):
        """Metadata should include created_at and last_activity."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        persist_session("abc12345")

        with open(tmp_path / "abc12345" / "session.yaml") as f:
            metadata = yaml.safe_load(f)

        assert "created_at" in metadata
        assert "last_activity" in metadata

    def test_idempotent(self, tmp_path, monkeypatch):
        """Multiple persist calls should not overwrite metadata."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        persist_session("abc12345")

        with open(tmp_path / "abc12345" / "session.yaml") as f:
            original = yaml.safe_load(f)

        time.sleep(0.01)  # Small delay to ensure different timestamp
        persist_session("abc12345")

        with open(tmp_path / "abc12345" / "session.yaml") as f:
            after = yaml.safe_load(f)

        assert original["created_at"] == after["created_at"]


class TestUpdateSessionActivity:
    """Tests for updating session activity timestamp."""

    def test_updates_last_activity(self, tmp_path, monkeypatch):
        """Should update the last_activity timestamp."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        persist_session("abc12345")

        with open(tmp_path / "abc12345" / "session.yaml") as f:
            before = yaml.safe_load(f)

        time.sleep(0.01)
        update_session_activity("abc12345")

        with open(tmp_path / "abc12345" / "session.yaml") as f:
            after = yaml.safe_load(f)

        assert after["last_activity"] > before["last_activity"]

    def test_no_op_for_non_persisted(self, tmp_path, monkeypatch):
        """Should do nothing for non-persisted session."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        # Should not raise
        update_session_activity("nonexistent")


class TestRequireSession:
    """Tests for session requirement validation."""

    def test_raises_for_invalid_format(self, tmp_path, monkeypatch):
        """Should raise HTTPException for invalid session ID format."""
        from fastapi import HTTPException

        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        with pytest.raises(HTTPException) as exc_info:
            require_session("invalid!")

        assert exc_info.value.status_code == 404

    def test_accepts_valid_format(self, tmp_path, monkeypatch):
        """Should not raise for valid session ID format."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        # Should not raise - validation only checks format
        require_session("abc12345")


class TestDeleteSession:
    """Tests for session deletion."""

    def test_deletes_existing_session(self, tmp_path, monkeypatch):
        """Should delete session directory and return True."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        persist_session("abc12345")
        (tmp_path / "abc12345" / "captures").mkdir()
        (tmp_path / "abc12345" / "captures" / "test.png").touch()

        result = delete_session("abc12345")

        assert result is True
        assert not (tmp_path / "abc12345").exists()

    def test_returns_false_for_nonexistent(self, tmp_path, monkeypatch):
        """Should return False for non-existent session."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        result = delete_session("nonexist")
        assert result is False


class TestCleanupExpiredSessions:
    """Tests for expired session cleanup."""

    def test_removes_expired_sessions(self, tmp_path, monkeypatch):
        """Should remove sessions older than expiry threshold."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)

        # Create an expired session
        old_session = tmp_path / "expired1"
        old_session.mkdir()
        old_time = datetime.now(UTC) - timedelta(days=SESSION_EXPIRY_DAYS + 1)
        with open(old_session / "session.yaml", "w") as f:
            yaml.safe_dump({"last_activity": old_time.isoformat()}, f)

        # Create a fresh session
        new_session = tmp_path / "fresh123"
        new_session.mkdir()
        with open(new_session / "session.yaml", "w") as f:
            yaml.safe_dump({"last_activity": datetime.now(UTC).isoformat()}, f)

        count = cleanup_expired_sessions()

        assert count == 1
        assert not old_session.exists()
        assert new_session.exists()

    def test_removes_sessions_without_metadata(self, tmp_path, monkeypatch):
        """Should remove sessions without metadata file."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)

        # Create session without metadata
        no_metadata = tmp_path / "nometada"
        no_metadata.mkdir()

        count = cleanup_expired_sessions()

        assert count == 1
        assert not no_metadata.exists()

    def test_handles_empty_sessions_dir(self, tmp_path, monkeypatch):
        """Should handle empty or non-existent sessions directory."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path / "nonexistent")
        count = cleanup_expired_sessions()
        assert count == 0


class TestTimestampUpdates:
    """Tests for timestamp update functions."""

    def test_update_last_capture_edit(self, tmp_path, monkeypatch):
        """Should update last_capture_edit timestamp."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        persist_session("abc12345")

        update_last_capture_edit("abc12345")

        with open(tmp_path / "abc12345" / "session.yaml") as f:
            metadata = yaml.safe_load(f)

        assert "last_capture_edit" in metadata

    def test_update_last_generation(self, tmp_path, monkeypatch):
        """Should update last_generation timestamp."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        persist_session("abc12345")

        update_last_generation("abc12345")

        with open(tmp_path / "abc12345" / "session.yaml") as f:
            metadata = yaml.safe_load(f)

        assert "last_generation" in metadata

    def test_get_session_timestamps(self, tmp_path, monkeypatch):
        """Should return both timestamps."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)
        persist_session("abc12345")
        update_last_capture_edit("abc12345")
        update_last_generation("abc12345")

        timestamps = get_session_timestamps("abc12345")

        assert timestamps["last_capture_edit"] is not None
        assert timestamps["last_generation"] is not None

    def test_get_timestamps_for_nonexistent(self, tmp_path, monkeypatch):
        """Should return None values for non-existent session."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)

        timestamps = get_session_timestamps("nonexist")

        assert timestamps["last_capture_edit"] is None
        assert timestamps["last_generation"] is None


class TestEphemeralSessions:
    """Tests verifying ephemeral sessions don't create files on disk.

    Ephemeral sessions exist only as valid IDs until data is explicitly persisted.
    This ensures we don't fill disk with empty session directories.
    """

    def test_create_session_is_ephemeral(self, tmp_path, monkeypatch):
        """create_session() should not create any files or directories."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)

        session_id = create_session()

        # No files should exist
        assert not (tmp_path / session_id).exists()
        assert len(list(tmp_path.iterdir())) == 0

    def test_validate_session_does_not_persist(self, tmp_path, monkeypatch):
        """validate_session() should not create any files."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)

        session_id = create_session()
        result = validate_session(session_id)

        assert result is True
        assert not (tmp_path / session_id).exists()

    def test_is_session_persisted_false_for_ephemeral(self, tmp_path, monkeypatch):
        """is_session_persisted() should return False for ephemeral session."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)

        session_id = create_session()

        assert is_session_persisted(session_id) is False

    def test_require_session_does_not_persist(self, tmp_path, monkeypatch):
        """require_session() should not create files for valid session."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)

        session_id = create_session()
        require_session(session_id)  # Should not raise

        # Session should still be ephemeral
        assert not (tmp_path / session_id).exists()

    def test_update_activity_no_op_for_ephemeral(self, tmp_path, monkeypatch):
        """update_session_activity() should be no-op for ephemeral session."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)

        session_id = create_session()
        update_session_activity(session_id)

        # Should not create any files
        assert not (tmp_path / session_id).exists()

    def test_get_timestamps_works_for_ephemeral(self, tmp_path, monkeypatch):
        """get_session_timestamps() should return None values for ephemeral session."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)

        session_id = create_session()
        timestamps = get_session_timestamps(session_id)

        assert timestamps["last_capture_edit"] is None
        assert timestamps["last_generation"] is None
        assert not (tmp_path / session_id).exists()

    def test_timestamp_updates_no_op_for_ephemeral(self, tmp_path, monkeypatch):
        """Timestamp updates should be no-op for ephemeral session."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)

        session_id = create_session()

        # These should not create files
        update_last_capture_edit(session_id)
        update_last_generation(session_id)

        assert not (tmp_path / session_id).exists()

    def test_delete_returns_false_for_ephemeral(self, tmp_path, monkeypatch):
        """delete_session() should return False for ephemeral session."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)

        session_id = create_session()
        result = delete_session(session_id)

        assert result is False

    def test_persist_converts_ephemeral_to_persisted(self, tmp_path, monkeypatch):
        """persist_session() should create files for ephemeral session."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)

        session_id = create_session()
        assert not (tmp_path / session_id).exists()

        persist_session(session_id)

        assert (tmp_path / session_id).exists()
        assert (tmp_path / session_id / "session.yaml").exists()
        assert is_session_persisted(session_id) is True

    def test_cleanup_ignores_ephemeral_sessions(self, tmp_path, monkeypatch):
        """cleanup_expired_sessions() should not affect ephemeral sessions."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)

        session_id = create_session()

        # Cleanup should not fail or create anything
        count = cleanup_expired_sessions()

        assert count == 0
        assert not (tmp_path / session_id).exists()

    def test_multiple_ephemeral_sessions(self, tmp_path, monkeypatch):
        """Multiple ephemeral sessions should not create any files."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)

        session_ids = [create_session() for _ in range(10)]

        # All should be valid
        for sid in session_ids:
            assert validate_session(sid) is True

        # No files should exist
        assert len(list(tmp_path.iterdir())) == 0

    def test_ephemeral_session_survives_validation_calls(self, tmp_path, monkeypatch):
        """Repeated operations on ephemeral session should not persist it."""
        monkeypatch.setattr("backend.session.SESSIONS_DIR", tmp_path)

        session_id = create_session()

        # Multiple operations
        for _ in range(5):
            validate_session(session_id)
            require_session(session_id)
            get_session_timestamps(session_id)
            update_session_activity(session_id)

        # Still ephemeral
        assert not (tmp_path / session_id).exists()
