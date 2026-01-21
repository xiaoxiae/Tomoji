# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Tomoji is a web application that creates personalized emoji fonts from face photos. Users capture their face expressions for ~35 standard face emojis, and the app generates a WOFF2 color bitmap font using CBDT/CBLC tables.

## Commands

### Development

```bash
# Backend (from project root)
uv run uvicorn backend.main:app --reload --port 8000

# Frontend (from frontend/)
npm run dev
```

### Testing

```bash
# Run all tests
uv run pytest

# Run single test file
uv run pytest backend/tests/test_rate_limiting.py

# Run specific test
uv run pytest backend/tests/test_rate_limiting.py::TestSessionCreationRateLimit::test_session_creation_within_limit
```

### Build

```bash
# Frontend build
cd frontend && npm run build
```

## Architecture

### Backend (Python/FastAPI)

- `backend/main.py` - FastAPI application with all API endpoints
- `backend/config.py` - Configuration constants, emoji list, rate limits
- `backend/session.py` - Session management (8-char IDs, 7-day expiry, YAML metadata)
- `backend/services/face_detector.py` - MediaPipe-based face segmentation and cropping
- `backend/services/font_builder.py` - CBDT/CBLC color bitmap font generation with fontTools

**Key flows:**
1. Face capture: Upload image -> MediaPipe segments face/hair/accessories -> crop with padding -> return as transparent PNG
2. Font export: Collect captured PNGs -> embed as 127px bitmaps in CBDT table -> output WOFF2

### Frontend (SolidJS/TypeScript)

- `frontend/src/App.tsx` - Main app with session context and view routing
- `frontend/src/lib/api.ts` - API client with typed endpoints
- `frontend/src/components/` - Gallery, CaptureModal, ExportView, SessionRedirect

Session IDs are stored in cookies and included in URL paths (e.g., `/{sessionId}/gallery`).

### Data Storage

Sessions stored in `data/sessions/{session_id}/`:
- `captures/` - PNG files named by emoji codepoint (e.g., `1f600.png`)
- `settings.yaml` - Per-session capture settings
- `session.yaml` - Session metadata (created_at, last_activity)

## API Structure

All session-scoped endpoints use `/{session_id}/` prefix. Rate limiting via slowapi. Endpoints:
- `POST /api/session` - Create session
- `GET /api/session/{id}/validate` - Validate session
- `GET /api/emojis` - List available emojis (global)
- `GET /api/{session_id}/gallery` - List captured emojis
- `POST /api/{session_id}/capture/{emoji}/preview` - Process image, return preview
- `POST /api/{session_id}/capture/{emoji}` - Save processed capture
- `POST /api/{session_id}/export` - Generate font
- `GET /api/{session_id}/export/download` - Download WOFF2
