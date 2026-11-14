"""Сборка роутеров API версии 1 (префикс ``/api/v1``)."""

from fastapi import APIRouter

from app.api.v1 import (
    admin_system,
    admin_users,
    attachments,
    audit,
    auth,
    boards,
    comments,
    health,
    me,
    me_oauth,
    notifications,
    oauth,
    overview,
    password_reset,
    projects,
    registration,
    tasks,
    tokens,
    unassigned_accounts,
    users,
)

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(me.router)
router.include_router(me_oauth.router)
router.include_router(oauth.router)
router.include_router(notifications.router)
router.include_router(overview.router)
router.include_router(tokens.router)
router.include_router(password_reset.router)
router.include_router(registration.router)
router.include_router(admin_users.router)
router.include_router(admin_system.router)
router.include_router(audit.router)
router.include_router(unassigned_accounts.router)
router.include_router(users.router)
router.include_router(projects.router)
router.include_router(tasks.router)
router.include_router(boards.router)
router.include_router(comments.router)
router.include_router(attachments.router)
