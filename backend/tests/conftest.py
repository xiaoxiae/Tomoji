"""Pytest configuration and shared fixtures for backend tests."""

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def temp_sessions_dir():
    """Create a temporary sessions directory for a test module.

    This fixture creates a temp directory that persists for the entire test module,
    allowing tests to share session data while ensuring complete isolation from
    the production data directory.
    """
    temp_dir = tempfile.mkdtemp(prefix="tomoji_test_sessions_")
    temp_path = Path(temp_dir)
    yield temp_path
    # Cleanup after all tests in module complete
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolate_sessions_dir(temp_sessions_dir, monkeypatch):
    """Automatically isolate all tests from production sessions directory.

    This fixture runs automatically for every test and patches SESSIONS_DIR
    to use the temporary directory, ensuring tests never touch production data.
    """
    # Patch the config module
    monkeypatch.setattr("backend.config.SESSIONS_DIR", temp_sessions_dir)
    # Also patch session module since it imports at module load time
    monkeypatch.setattr("backend.session.SESSIONS_DIR", temp_sessions_dir)


@pytest.fixture
def clean_sessions_dir(temp_sessions_dir):
    """Provide a clean sessions directory for tests that need isolation from other tests.

    Use this fixture when a test needs to start with an empty sessions directory.
    """
    # Clear any existing sessions
    for item in temp_sessions_dir.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    yield temp_sessions_dir
