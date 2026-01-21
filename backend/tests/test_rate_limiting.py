"""Tests for API rate limiting.

These tests start a real uvicorn server on port 8001 to test rate limiting behavior.
Each test class tests a different endpoint to avoid rate limit state conflicts.
"""

import multiprocessing
import time

# Use spawn method instead of fork to avoid issues with multi-threaded pytest
try:
    multiprocessing.set_start_method("spawn")
except RuntimeError:
    pass  # Already set

import httpx
import pytest
import uvicorn

from backend.config import (
    RATE_LIMIT_SESSION_CREATE,
    RATE_LIMIT_EXPORT,
)
from backend.main import app


TEST_PORT = 8001
TEST_BASE_URL = f"http://127.0.0.1:{TEST_PORT}"


def _parse_rate_limit(limit_str: str) -> int:
    """Parse rate limit string like '50/minute' to get the count."""
    return int(limit_str.split("/")[0])


def run_server():
    """Run the uvicorn server (called in subprocess)."""
    uvicorn.run(app, host="127.0.0.1", port=TEST_PORT, log_level="warning")


@pytest.fixture(scope="module")
def server():
    """Start a test server on port 8001 for the test module."""
    proc = multiprocessing.Process(target=run_server, daemon=True)
    proc.start()

    # Wait for server to be ready
    for _ in range(50):
        try:
            with httpx.Client() as client:
                client.get(f"{TEST_BASE_URL}/api/emojis", timeout=0.5)
            break
        except (httpx.ConnectError, httpx.ReadTimeout):
            time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail("Test server failed to start")

    yield proc

    proc.terminate()
    proc.join(timeout=2)


@pytest.fixture(scope="module")
def created_sessions(server):
    """Track created sessions for cleanup."""
    sessions = []
    yield sessions
    # Cleanup all created sessions
    with httpx.Client(base_url=TEST_BASE_URL, timeout=10.0) as client:
        for session_id in sessions:
            client.delete(f"/api/session/{session_id}")


@pytest.fixture
def client(server):
    """Create an HTTP client for the test server."""
    with httpx.Client(base_url=TEST_BASE_URL, timeout=10.0) as client:
        yield client


@pytest.fixture(scope="module")
def test_session(server, created_sessions):
    """Create a session for tests that need one (before rate limits are exhausted)."""
    with httpx.Client(base_url=TEST_BASE_URL, timeout=10.0) as client:
        response = client.post("/api/session")
        session_id = response.json()["session_id"]
        created_sessions.append(session_id)
        return session_id


class TestSessionCreationRateLimit:
    """Test rate limiting on session creation endpoint."""

    def test_session_creation_exceeds_limit(self, client, test_session, created_sessions):
        """Should block after exceeding rate limit."""
        # test_session fixture already used 1 slot
        limit = _parse_rate_limit(RATE_LIMIT_SESSION_CREATE)
        remaining = limit - 1

        # Use up the remaining limit
        for i in range(remaining):
            response = client.post("/api/session")
            assert response.status_code == 200, f"Request {i+1} should succeed"
            session_id = response.json()["session_id"]
            created_sessions.append(session_id)

        # Next request should be rate limited
        response = client.post("/api/session")
        assert response.status_code == 429
        assert "Rate limit exceeded" in response.json()["detail"]


class TestExportRateLimit:
    """Test rate limiting on export endpoint."""

    def test_export_rate_limit(self, client, test_session):
        """Should block export after exceeding rate limit."""
        limit = _parse_rate_limit(RATE_LIMIT_EXPORT)

        # Try to export up to the limit (will fail with "No captures" but that's fine for rate limit testing)
        for i in range(limit):
            response = client.post(
                f"/api/{test_session}/export",
                json={"font_name": "Test"}
            )
            # Either 400 (no captures) or 200 is fine, just not 429 yet
            assert response.status_code in [200, 400], f"Request {i+1} should not be rate limited"

        # Next request should be rate limited
        response = client.post(
            f"/api/{test_session}/export",
            json={"font_name": "Test"}
        )
        assert response.status_code == 429
        assert "Rate limit exceeded" in response.json()["detail"]
