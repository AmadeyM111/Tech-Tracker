"""Проверка живости (FR-7: эндпоинт публичный, без аутентификации)."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Проверка живости сервиса."""
    return {"status": "ok"}
