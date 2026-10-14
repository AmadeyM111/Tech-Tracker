"""Сборка роутеров API версии 1 (префикс ``/api/v1``)."""

from fastapi import APIRouter

from app.api.v1 import admin_users, auth, health, me

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(me.router)
router.include_router(admin_users.router)
