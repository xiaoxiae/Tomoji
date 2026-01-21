# Build frontend
FROM node:20-slim AS frontend
WORKDIR /app/frontend

ARG VITE_UMAMI_URL
ARG VITE_UMAMI_WEBSITE_ID
ARG VITE_UMAMI_DOMAINS

COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Runtime
FROM python:3.12-slim
WORKDIR /app

# System deps for opencv/mediapipe + uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Python deps
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# App code
COPY backend/ ./backend/
COPY --from=frontend /app/frontend/dist ./frontend/dist

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
