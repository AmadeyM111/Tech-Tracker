"""A11-T02/T03: вложения по HTTP (spec 011 AC-1…AC-9)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import pytest
from sqlalchemy import select, update

from app.domain.attachments.models import Attachment
from app.domain.tasks.models import Task
from tests import attachments_support as fx
from tests.conftest import ApiEnv
from tests.factories import make_project, make_project_member, make_task, make_user, make_workspace

MAX = 10 * 1024 * 1024


@dataclass
class World:
    env: ApiEnv
    ba: Any
    member: Any
    stranger: Any
    project: Any
    task: Any  # автор и исполнитель — member
    tokens: dict[str, str]


async def _world(env: ApiEnv) -> World:
    async with env.sessionmaker() as s:
        ws = await make_workspace(s)
        ba = await make_user(s, role="business_admin", workspace=ws)
        member = await make_user(s, role="user", workspace=ws)
        stranger = await make_user(s, role="business_admin", workspace=ws)
        project = await make_project(s, workspace_id=ws.id, owner_id=ba.id)
        await make_project_member(s, project_id=project.id, user_id=member.id, workspace_id=ws.id)
        task = await make_task(
            s,
            project_id=project.id,
            workspace_id=ws.id,
            created_by=member.id,
            assignee_id=member.id,
        )
        await s.commit()
    tokens = {
        "ba": await env.login_ok(ba),
        "member": await env.login_ok(member),
        "stranger": await env.login_ok(stranger),
    }
    return World(env, ba, member, stranger, project, task, tokens)


def _headers(env: ApiEnv, token: str, name: str) -> dict[str, str]:
    return env.auth(
        token, **{"Content-Type": "application/octet-stream", "X-File-Name": quote(name)}
    )


async def _upload(w: World, who: str, name: str, data: bytes, task_id: Any = None) -> Any:
    return await w.env.client.post(
        f"/api/v1/tasks/{task_id or w.task.id}/attachments",
        content=data,
        headers=_headers(w.env, w.tokens[who], name),
    )


async def test_011_ac1_size_boundaries(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    exact = fx.PDF + b"0" * (MAX - len(fx.PDF))
    ok = await _upload(w, "member", "ровно.pdf", exact)
    assert ok.status_code == 201, ok.text
    assert ok.json()["size_bytes"] == MAX
    over = await _upload(w, "member", "больше.pdf", exact + b"0")
    assert over.status_code == 413 and over.json()["code"] == "attachment_too_large"
    empty = await _upload(w, "member", "пусто.pdf", b"")
    assert empty.status_code == 422 and empty.json()["code"] == "attachment_empty"


@pytest.mark.parametrize(
    ("name", "data", "status"),
    [
        ("скрин.png", fx.PNG, 201),
        ("смета.xlsx", fx.ooxml("xlsx"), 201),
        ("1251.csv", fx.TXT_1251, 201),
        ("logo.svg", b"<svg/>", 422),
        ("page.html", b"<html></html>", 422),
        ("macro.docx", fx.ooxml("docx", macro=True), 422),
        ("fake.pdf", fx.PNG, 422),
    ],
)
async def test_011_ac2_types_over_http(
    api_env: ApiEnv, name: str, data: bytes, status: int
) -> None:
    w = await _world(api_env)
    response = await _upload(w, "member", name, data)
    assert response.status_code == status, response.text
    if status == 422:
        assert response.json()["code"] == "attachment_type_not_allowed"


async def test_011_ac3_permissions(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    ta = await api_env.new_user(role="tech_admin")
    ta_token = await api_env.login_ok(ta)
    r = await api_env.client.post(
        f"/api/v1/tasks/{w.task.id}/attachments",
        content=fx.PDF,
        headers=_headers(api_env, ta_token, "a.pdf"),
    )
    assert r.status_code == 403
    assert (await _upload(w, "stranger", "a.pdf", fx.PDF)).status_code == 403
    missing = "00000000-0000-4000-8000-000000000000"
    assert (await _upload(w, "member", "a.pdf", fx.PDF, task_id=missing)).status_code == 404
    await api_env.execute(
        update(Task).where(Task.id == w.task.id).values(deleted_at=api_env.clock.now())
    )
    assert (await _upload(w, "member", "a.pdf", fx.PDF)).status_code == 404
    anon = await api_env.client.post(
        f"/api/v1/tasks/{w.task.id}/attachments", content=fx.PDF, headers={"X-File-Name": "a.pdf"}
    )
    assert anon.status_code == 401


async def test_011_ac4_limit_per_task(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    api_env.app.state.settings.attachments_per_task = 2
    for i in range(2):
        assert (await _upload(w, "member", f"{i}.pdf", fx.PDF)).status_code == 201
    third = await _upload(w, "member", "3.pdf", fx.PDF)
    assert third.status_code == 409 and third.json()["code"] == "too_many_attachments"


async def test_011_ac5_download_headers(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    png = (await _upload(w, "member", "скрин.png", fx.PNG)).json()
    pdf = (await _upload(w, "member", 'отчёт "итог".pdf', fx.PDF)).json()
    auth = api_env.auth(w.tokens["ba"])
    r_png = await api_env.client.get(f"/api/v1/attachments/{png['id']}/content", headers=auth)
    r_pdf = await api_env.client.get(f"/api/v1/attachments/{pdf['id']}/content", headers=auth)
    assert r_png.status_code == 200 and r_png.content == fx.PNG
    assert r_png.headers["content-disposition"].startswith("inline")
    assert r_pdf.headers["content-disposition"].startswith("attachment")
    assert quote('отчёт "итог".pdf') in r_pdf.headers["content-disposition"]
    for r in (r_png, r_pdf):
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["content-security-policy"].startswith("sandbox")
    assert r_pdf.headers["content-type"] == "application/pdf"


async def test_011_ac6_name_never_in_path(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    r = await _upload(w, "member", "../../etc/passwd.pdf", fx.PDF)
    assert r.status_code == 201 and r.json()["name"] == "passwd.pdf"
    async with api_env.sessionmaker() as s:
        row = (
            await s.execute(select(Attachment).where(Attachment.id == r.json()["id"]))
        ).scalar_one()
    stored = api_env.settings.attachments_dir / row.storage_key[:2] / row.storage_key
    assert stored.read_bytes() == fx.PDF
    assert "passwd" not in str(stored)


async def test_011_ac7_delete_rules_and_soft_delete(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    by_ba = (await _upload(w, "ba", "ba.pdf", fx.PDF)).json()
    by_member = (await _upload(w, "member", "m.pdf", fx.PDF)).json()
    # участник — автор и исполнитель задачи: полная правка своей задачи → может удалить чужое
    assert by_ba["can_delete"] is True
    assert (
        await api_env.client.delete(
            f"/api/v1/attachments/{by_ba['id']}", headers=api_env.auth(w.tokens["member"])
        )
    ).status_code == 204
    # пользователь без полной правки задачи не удаляет чужое
    async with api_env.sessionmaker() as s:
        other = await make_task(
            s, project_id=w.project.id, workspace_id=w.ba.workspace_id, created_by=w.ba.id
        )
        await s.commit()
    foreign = (await _upload(w, "ba", "f.pdf", fx.PDF, task_id=other.id)).json()
    denied = await api_env.client.delete(
        f"/api/v1/attachments/{foreign['id']}", headers=api_env.auth(w.tokens["member"])
    )
    assert denied.status_code == 403
    # БА-участник удаляет любое
    assert (
        await api_env.client.delete(
            f"/api/v1/attachments/{by_member['id']}", headers=api_env.auth(w.tokens["ba"])
        )
    ).status_code == 204
    gone = await api_env.client.get(
        f"/api/v1/attachments/{by_member['id']}/content", headers=api_env.auth(w.tokens["ba"])
    )
    assert gone.status_code == 404
    listed = await api_env.client.get(
        f"/api/v1/tasks/{w.task.id}/attachments", headers=api_env.auth(w.tokens["ba"])
    )
    assert listed.json()["items"] == []


async def test_011_ac8_feed_shows_file_name(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    await _upload(w, "member", "протокол.pdf", fx.PDF)
    feed = await api_env.client.get(
        f"/api/v1/projects/{w.project.id}/activity", headers=api_env.auth(w.tokens["ba"])
    )
    assert feed.status_code == 200, feed.text
    rows = [i for i in feed.json()["items"] if i["action"] == "attachment.created"]
    assert len(rows) == 1 and rows[0]["entity"]["title"] == "протокол.pdf"


async def test_011_ac9_disk_full_blocks_upload_not_tasks(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    api_env.app.state.settings.attachments_min_free_mb = 10**12
    r = await _upload(w, "member", "a.pdf", fx.PDF)
    assert r.status_code == 507 and r.json()["code"] == "storage_full"
    created = await api_env.client.post(
        f"/api/v1/projects/{w.project.id}/tasks",
        json={
            "title": "Работа идёт",
            "description": "Описание",
            "due_date": "2026-12-01",
            "assignee_id": str(w.member.id),
        },
        headers=api_env.auth(w.tokens["ba"]),
    )
    assert created.status_code == 201, created.text


async def test_011_list_shows_author_and_rights(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    await _upload(w, "ba", "ba.pdf", fx.PDF)
    items = await api_env.client.get(
        f"/api/v1/tasks/{w.task.id}/attachments", headers=api_env.auth(w.tokens["stranger"])
    )
    assert items.status_code == 403
    mine = (
        await api_env.client.get(
            f"/api/v1/tasks/{w.task.id}/attachments", headers=api_env.auth(w.tokens["member"])
        )
    ).json()["items"]
    assert [(i["name"], i["author"]["login"], i["kind"]) for i in mine] == [
        ("ba.pdf", w.ba.login, "pdf")
    ]


async def test_011_permissions_checked_before_size(api_env: ApiEnv) -> None:
    """Не участник получает 403, а не 413, даже на слишком большой файл (ревью 011, п. 8)."""
    w = await _world(api_env)
    big = fx.PDF + b"0" * (MAX + 1)
    assert (await _upload(w, "stranger", "big.pdf", big)).status_code == 403


async def test_011_name_header_is_required_and_decoded(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    missing = await api_env.client.post(
        f"/api/v1/tasks/{w.task.id}/attachments",
        content=fx.PDF,
        headers=api_env.auth(w.tokens["member"]),
    )
    assert missing.status_code == 422
    ok = await _upload(w, "member", "Отчёт № 5.pdf", fx.PDF)
    assert ok.json()["name"] == "Отчёт № 5.pdf"


async def test_011_cp1251_text_is_served_with_its_charset(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    item = (await _upload(w, "member", "1251.txt", fx.TXT_1251)).json()
    assert item["content_type"] == "text/plain; charset=windows-1251"
    utf = (await _upload(w, "member", "utf.csv", fx.CSV)).json()
    assert utf["content_type"] == "text/csv; charset=utf-8"


async def test_011_ac4_parallel_uploads_respect_limit(committed_api_env: ApiEnv) -> None:
    """Параллельные загрузки не обходят лимит (ревью 011, п. 1): блокировка задачи."""
    import asyncio

    w = await _world(committed_api_env)
    committed_api_env.app.state.settings.attachments_per_task = 2
    results = await asyncio.gather(*(_upload(w, "member", f"{i}.pdf", fx.PDF) for i in range(6)))
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 201, 409, 409, 409, 409]
