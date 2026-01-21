# Tomoji

Generate emoji fonts from your face.

## Run

### Docker

```bash
docker build -t tomoji .
docker run -p 8000:8000 -v tomoji-data:/app/data tomoji
```

### Locally

```bash
uv run uvicorn backend.main:app --reload --port 8000
```

```bash
cd frontend
npm install
npm run dev
```
