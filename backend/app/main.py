"""Точка входа API."""

from fastapi import FastAPI

app = FastAPI(title="Tracker API", version="0.0.1")


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    """Проверка живости сервиса."""
    return {"status": "ok"}
