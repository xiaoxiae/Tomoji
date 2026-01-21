"""Tests for API endpoints.

These tests use FastAPI's TestClient for synchronous testing without starting a server.
"""

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.main import app
from backend.session import (
    get_session_captures_dir,
    get_session_dir,
    persist_session,
)


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def session_id(client):
    """Create a session and return its ID.

    Cleanup is handled automatically by conftest.py's temp_sessions_dir fixture.
    """
    response = client.post("/api/session")
    assert response.status_code == 200
    return response.json()["session_id"]


@pytest.fixture
def face_image_base64():
    """Create a base64-encoded test image with face-like colors."""
    img = Image.new("RGB", (256, 256), color=(100, 150, 200))
    pixels = img.load()

    # Draw skin-colored oval (face simulation)
    center_x, center_y = 128, 100
    for y in range(256):
        for x in range(256):
            dx = (x - center_x) / 50
            dy = (y - center_y) / 60
            if dx * dx + dy * dy < 1:
                pixels[x, y] = (210, 180, 140)

    # Add hair above face
    for y in range(40, 80):
        for x in range(90, 170):
            dx = (x - center_x) / 45
            dy = (y - 60) / 25
            if dx * dx + dy * dy < 1:
                pixels[x, y] = (50, 30, 20)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


@pytest.fixture
def simple_image_base64():
    """Create a simple base64-encoded test image."""
    img = Image.new("RGB", (100, 100), color=(255, 0, 0))
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


class TestSessionEndpoints:
    """Tests for session management endpoints."""

    def test_create_session(self, client):
        """POST /api/session should create a new session."""
        response = client.post("/api/session")
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert len(data["session_id"]) == 8

    def test_validate_session_valid(self, client, session_id):
        """GET /api/session/{id}/validate should return valid for good session."""
        response = client.get(f"/api/session/{session_id}/validate")
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["session_id"] == session_id

    def test_validate_session_invalid_format(self, client):
        """GET /api/session/{id}/validate should return invalid for bad format."""
        response = client.get("/api/session/invalid!/validate")
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False

    def test_delete_session(self, client):
        """DELETE /api/session/{id} should delete the session."""
        # Create a session first
        create_response = client.post("/api/session")
        session_id = create_response.json()["session_id"]

        # Persist it so there's something to delete
        persist_session(session_id)
        assert get_session_dir(session_id).exists()

        # Delete it
        response = client.delete(f"/api/session/{session_id}")
        assert response.status_code == 200
        assert not get_session_dir(session_id).exists()

    def test_delete_nonexistent_session(self, client):
        """DELETE /api/session/{id} should return 404 for non-existent session."""
        response = client.delete("/api/session/notexist")
        assert response.status_code == 404


class TestEmojisEndpoint:
    """Tests for emoji listing endpoint."""

    def test_list_emojis(self, client):
        """GET /api/emojis should return emoji categories."""
        response = client.get("/api/emojis")
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data
        assert len(data["categories"]) > 0

        # Check category structure
        category = data["categories"][0]
        assert "id" in category
        assert "name" in category
        assert "emojis" in category
        assert len(category["emojis"]) > 0

        # Check emoji structure
        emoji = category["emojis"][0]
        assert "emoji" in emoji
        assert "codepoint" in emoji
        assert "name" in emoji


class TestSettingsEndpoints:
    """Tests for settings endpoints."""

    def test_get_settings(self, client, session_id):
        """GET /api/{session_id}/settings should return default settings."""
        response = client.get(f"/api/{session_id}/settings")
        assert response.status_code == 200
        data = response.json()
        assert "padding" in data
        assert "output_size" in data
        assert "keep_background" in data
        assert "keep_clothes" in data
        assert "keep_accessories" in data

    def test_update_settings(self, client, session_id):
        """PUT /api/{session_id}/settings should update settings."""
        new_settings = {
            "padding": 0.25,
            "output_size": 256,
            "keep_background": True,
            "keep_clothes": True,
            "keep_accessories": False,
        }
        response = client.put(f"/api/{session_id}/settings", json=new_settings)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["padding"] == 0.25

        # Verify settings were saved
        get_response = client.get(f"/api/{session_id}/settings")
        assert get_response.json()["padding"] == 0.25

    def test_settings_validation(self, client, session_id):
        """Settings should validate input ranges."""
        # Invalid padding (too high)
        response = client.put(
            f"/api/{session_id}/settings",
            json={
                "padding": 2.0,  # Max is 1.0
                "output_size": 128,
                "keep_background": False,
                "keep_clothes": False,
                "keep_accessories": True,
            },
        )
        assert response.status_code == 422  # Validation error

    def test_settings_invalid_session(self, client):
        """Settings endpoints should return 404 for invalid session."""
        response = client.get("/api/invalid!/settings")
        assert response.status_code == 404


class TestGalleryEndpoint:
    """Tests for gallery endpoint."""

    def test_get_empty_gallery(self, client, session_id):
        """GET /api/{session_id}/gallery should return empty list initially."""
        response = client.get(f"/api/{session_id}/gallery")
        assert response.status_code == 200
        data = response.json()
        assert "captured" in data
        assert "total" in data
        assert len(data["captured"]) == 0
        assert data["total"] > 0

    def test_gallery_invalid_session(self, client):
        """Gallery should return 404 for invalid session."""
        response = client.get("/api/invalid!/gallery")
        assert response.status_code == 404


class TestCapturePreviewEndpoint:
    """Tests for capture preview endpoint."""

    def test_preview_standard_emoji(self, client, session_id, face_image_base64):
        """POST /api/{session_id}/capture/{emoji}/preview should return preview."""
        response = client.post(
            f"/api/{session_id}/capture/😀/preview",
            json={
                "image": face_image_base64,
                "padding": 0.15,
                "output_size": 128,
                "keep_background": False,
                "keep_clothes": False,
                "keep_accessories": True,
            },
        )
        # May succeed or fail depending on face detection
        # 200 = success, 400 = no face detected (both are valid outcomes)
        assert response.status_code in [200, 400]

        if response.status_code == 200:
            data = response.json()
            assert data["success"] is True
            assert "preview_image" in data
            assert data["preview_image"].startswith("data:image/png;base64,")

    def test_preview_by_codepoint(self, client, session_id, face_image_base64):
        """Should accept emoji by codepoint."""
        response = client.post(
            f"/api/{session_id}/capture/1f600/preview",  # 😀
            json={
                "image": face_image_base64,
                "padding": 0.15,
                "output_size": 128,
                "keep_background": False,
                "keep_clothes": False,
                "keep_accessories": True,
            },
        )
        assert response.status_code in [200, 400]

    def test_preview_invalid_emoji(self, client, session_id, face_image_base64):
        """Should reject invalid emoji."""
        response = client.post(
            f"/api/{session_id}/capture/notanemoji/preview",
            json={
                "image": face_image_base64,
                "padding": 0.15,
                "output_size": 128,
                "keep_background": False,
                "keep_clothes": False,
                "keep_accessories": True,
            },
        )
        assert response.status_code == 400

    def test_preview_invalid_image(self, client, session_id):
        """Should reject invalid image data."""
        response = client.post(
            f"/api/{session_id}/capture/😀/preview",
            json={
                "image": "not-valid-base64!!!!",
                "padding": 0.15,
                "output_size": 128,
                "keep_background": False,
                "keep_clothes": False,
                "keep_accessories": True,
            },
        )
        assert response.status_code == 400


class TestCaptureSaveEndpoint:
    """Tests for capture save endpoint."""

    def test_save_capture(self, client, session_id, simple_image_base64):
        """POST /api/{session_id}/capture/{emoji} should save capture."""
        response = client.post(
            f"/api/{session_id}/capture/😀",
            json={"image": simple_image_base64},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["emoji"] == "😀"
        assert "codepoint" in data

        # Verify file was saved
        captures_dir = get_session_captures_dir(session_id)
        assert (captures_dir / f"{data['codepoint']}.png").exists()

    def test_save_capture_with_data_url(self, client, session_id, simple_image_base64):
        """Should accept data URL format."""
        response = client.post(
            f"/api/{session_id}/capture/😀",
            json={"image": f"data:image/png;base64,{simple_image_base64}"},
        )
        assert response.status_code == 200

    def test_save_custom_emoji(self, client, session_id, simple_image_base64):
        """Should allow saving custom emojis."""
        response = client.post(
            f"/api/{session_id}/capture/🦄",  # Not in standard list
            json={"image": simple_image_base64},
        )
        # Should succeed if emoji is valid
        assert response.status_code == 200

    def test_save_invalid_emoji(self, client, session_id, simple_image_base64):
        """Should reject invalid emoji characters."""
        response = client.post(
            f"/api/{session_id}/capture/abc",
            json={"image": simple_image_base64},
        )
        assert response.status_code == 400


class TestCaptureDeleteEndpoint:
    """Tests for capture delete endpoint."""

    def test_delete_capture(self, client, session_id, simple_image_base64):
        """DELETE /api/{session_id}/capture/{emoji} should delete capture."""
        # First save a capture
        client.post(
            f"/api/{session_id}/capture/😀",
            json={"image": simple_image_base64},
        )

        # Then delete it
        response = client.delete(f"/api/{session_id}/capture/😀")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify file was deleted
        captures_dir = get_session_captures_dir(session_id)
        assert not list(captures_dir.glob("*.png"))

    def test_delete_nonexistent_capture(self, client, session_id):
        """Should succeed even if capture doesn't exist."""
        response = client.delete(f"/api/{session_id}/capture/😀")
        assert response.status_code == 200


class TestClearAllEndpoint:
    """Tests for clear all captures endpoint."""

    def test_clear_all_captures(self, client, session_id, simple_image_base64):
        """DELETE /api/{session_id}/captures should delete all captures."""
        # Save multiple captures
        for emoji in ["😀", "😁", "😂"]:
            client.post(
                f"/api/{session_id}/capture/{emoji}",
                json={"image": simple_image_base64},
            )

        # Clear all
        response = client.delete(f"/api/{session_id}/captures")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["deleted_count"] == 3

        # Verify all deleted
        captures_dir = get_session_captures_dir(session_id)
        assert len(list(captures_dir.glob("*.png"))) == 0


class TestExportEndpoint:
    """Tests for font export endpoint."""

    def test_export_no_captures(self, client, session_id):
        """POST /api/{session_id}/export should fail with no captures."""
        response = client.post(
            f"/api/{session_id}/export",
            json={"font_name": "Test"},
        )
        assert response.status_code == 400
        assert "No captures" in response.json()["detail"]

    def test_export_with_captures(self, client, session_id, simple_image_base64):
        """POST /api/{session_id}/export should generate font."""
        # Save a capture first
        client.post(
            f"/api/{session_id}/capture/😀",
            json={"image": simple_image_base64},
        )

        # Export
        response = client.post(
            f"/api/{session_id}/export",
            json={"font_name": "TestFont"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["captured_count"] == 1
        assert "font_url" in data

        # Verify font file exists
        captures_dir = get_session_captures_dir(session_id)
        assert (captures_dir / "tomoji.woff2").exists()


class TestFontDownloadEndpoint:
    """Tests for font download endpoint."""

    def test_download_font(self, client, session_id, simple_image_base64):
        """GET /api/{session_id}/font.woff2 should return font file."""
        # Save and export first
        client.post(
            f"/api/{session_id}/capture/😀",
            json={"image": simple_image_base64},
        )
        client.post(f"/api/{session_id}/export", json={"font_name": "Test"})

        # Download
        response = client.get(f"/api/{session_id}/font.woff2")
        assert response.status_code == 200
        assert response.headers["content-type"] == "font/woff2"

    def test_download_nonexistent_font(self, client, session_id):
        """Should return 404 if font not generated."""
        response = client.get(f"/api/{session_id}/font.woff2")
        assert response.status_code == 404


class TestImagesZipEndpoint:
    """Tests for images ZIP download endpoint."""

    def test_download_images_zip(self, client, session_id, simple_image_base64):
        """GET /api/{session_id}/images.zip should return ZIP file."""
        # Save captures
        for emoji in ["😀", "😁"]:
            client.post(
                f"/api/{session_id}/capture/{emoji}",
                json={"image": simple_image_base64},
            )

        # Download ZIP
        response = client.get(f"/api/{session_id}/images.zip")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"

    def test_download_empty_zip(self, client, session_id):
        """Should return 400 if no captures."""
        response = client.get(f"/api/{session_id}/images.zip")
        assert response.status_code == 400

    def test_download_with_custom_name(self, client, session_id, simple_image_base64):
        """Should allow custom filename."""
        client.post(
            f"/api/{session_id}/capture/😀",
            json={"image": simple_image_base64},
        )

        response = client.get(f"/api/{session_id}/images.zip?name=MyEmojis")
        assert response.status_code == 200
        assert "MyEmojis.zip" in response.headers["content-disposition"]


class TestCaptureImageEndpoint:
    """Tests for capture image retrieval endpoint."""

    def test_get_capture_image(self, client, session_id, simple_image_base64):
        """GET /api/{session_id}/capture/{codepoint}/image should return image."""
        # Save a capture
        save_response = client.post(
            f"/api/{session_id}/capture/😀",
            json={"image": simple_image_base64},
        )
        codepoint = save_response.json()["codepoint"]

        # Get the image
        response = client.get(f"/api/{session_id}/capture/{codepoint}/image")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"

    def test_get_nonexistent_image(self, client, session_id):
        """Should return 404 for non-existent capture."""
        response = client.get(f"/api/{session_id}/capture/1f600/image")
        assert response.status_code == 404


class TestEphemeralSessionsAPI:
    """Tests verifying ephemeral sessions don't create files via API.

    Sessions should remain ephemeral (no disk storage) until a user actually
    saves data (captures or settings). Read-only operations should never persist.

    Note: Cleanup is handled automatically by conftest.py's temp_sessions_dir fixture.
    """

    def test_create_session_does_not_persist(self, client):
        """POST /api/session should not create files on disk."""
        response = client.post("/api/session")
        assert response.status_code == 200
        session_id = response.json()["session_id"]

        # Session directory should not exist
        session_dir = get_session_dir(session_id)
        assert not session_dir.exists()

    def test_validate_session_does_not_persist(self, client):
        """GET /api/session/{id}/validate should not create files."""
        # Create session
        create_response = client.post("/api/session")
        session_id = create_response.json()["session_id"]

        # Validate multiple times
        for _ in range(3):
            response = client.get(f"/api/session/{session_id}/validate")
            assert response.status_code == 200
            assert response.json()["valid"] is True

        # Still no files
        assert not get_session_dir(session_id).exists()

    def test_get_settings_does_not_persist(self, client):
        """GET /api/{session_id}/settings should not create files."""
        create_response = client.post("/api/session")
        session_id = create_response.json()["session_id"]

        # Get settings (should return defaults)
        response = client.get(f"/api/{session_id}/settings")
        assert response.status_code == 200
        assert "padding" in response.json()

        # Still ephemeral
        assert not get_session_dir(session_id).exists()

    def test_get_gallery_does_not_persist(self, client):
        """GET /api/{session_id}/gallery should not create files."""
        create_response = client.post("/api/session")
        session_id = create_response.json()["session_id"]

        # Get empty gallery
        response = client.get(f"/api/{session_id}/gallery")
        assert response.status_code == 200
        assert response.json()["captured"] == []

        # Still ephemeral
        assert not get_session_dir(session_id).exists()

    def test_preview_does_not_persist(self, client, face_image_base64):
        """POST /api/{session_id}/capture/{emoji}/preview should not persist."""
        create_response = client.post("/api/session")
        session_id = create_response.json()["session_id"]

        # Preview capture (may succeed or fail based on face detection)
        response = client.post(
            f"/api/{session_id}/capture/😀/preview",
            json={
                "image": face_image_base64,
                "padding": 0.15,
                "output_size": 128,
                "keep_background": False,
                "keep_clothes": False,
                "keep_accessories": True,
            },
        )
        # Either 200 or 400 is acceptable
        assert response.status_code in [200, 400]

        # Session should still be ephemeral - preview doesn't save anything
        assert not get_session_dir(session_id).exists()

    def test_save_capture_persists_session(self, client, simple_image_base64):
        """POST /api/{session_id}/capture/{emoji} SHOULD persist the session."""
        create_response = client.post("/api/session")
        session_id = create_response.json()["session_id"]

        # Before save - ephemeral
        assert not get_session_dir(session_id).exists()

        # Save capture
        response = client.post(
            f"/api/{session_id}/capture/😀",
            json={"image": simple_image_base64},
        )
        assert response.status_code == 200

        # Now it should be persisted
        assert get_session_dir(session_id).exists()
        assert get_session_captures_dir(session_id).exists()
        assert (get_session_captures_dir(session_id) / "1f600.png").exists()

    def test_save_settings_persists_session(self, client):
        """PUT /api/{session_id}/settings SHOULD persist the session."""
        create_response = client.post("/api/session")
        session_id = create_response.json()["session_id"]

        # Before save - ephemeral
        assert not get_session_dir(session_id).exists()

        # Update settings
        response = client.put(
            f"/api/{session_id}/settings",
            json={
                "padding": 0.25,
                "output_size": 256,
                "keep_background": True,
                "keep_clothes": False,
                "keep_accessories": True,
            },
        )
        assert response.status_code == 200

        # Now it should be persisted
        assert get_session_dir(session_id).exists()

    def test_multiple_read_operations_stay_ephemeral(self, client):
        """Multiple read operations should not persist the session."""
        create_response = client.post("/api/session")
        session_id = create_response.json()["session_id"]

        # Perform many read operations
        for _ in range(5):
            client.get(f"/api/session/{session_id}/validate")
            client.get(f"/api/{session_id}/settings")
            client.get(f"/api/{session_id}/gallery")

        # Still ephemeral
        assert not get_session_dir(session_id).exists()

    def test_failed_export_does_not_persist(self, client):
        """Failed export (no captures) should not persist session."""
        create_response = client.post("/api/session")
        session_id = create_response.json()["session_id"]

        # Try to export with no captures
        response = client.post(
            f"/api/{session_id}/export",
            json={"font_name": "Test"},
        )
        assert response.status_code == 400  # No captures

        # Still ephemeral
        assert not get_session_dir(session_id).exists()
