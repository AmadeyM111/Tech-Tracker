"""Сборка роутеров API версии 1 (префикс ``/api/v1``)."""

from fastapi import APIRouter

from app.api.v1 import admin_users, audit, auth, health, me, projects, tasks, users

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(me.router)
router.include_router(admin_users.router)
router.include_router(audit.router)
router.include_router(users.router)
router.include_router(projects.router)
router.include_router(tasks.router)
