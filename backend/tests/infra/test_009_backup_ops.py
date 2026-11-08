"""B09-T07: статические проверки эксплуатации копий (spec 009 FR-10, NFR-4; plan PB-1)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_009_api_image_has_postgres_16_client() -> None:
    text = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "postgresql-client-16" in text
    assert "bookworm-pgdg" in text
    assert "rm -rf /var/lib/apt/lists/*" in text


def test_009_timer_calls_cli_daily_moscow() -> None:
    service = (ROOT / "deploy/backup/gtrack-backup.service").read_text(encoding="utf-8")
    timer = (ROOT / "deploy/backup/gtrack-backup.timer").read_text(encoding="utf-8")
    assert "gtrack backup" in service and "Type=oneshot" in service
    assert "OnCalendar=*-*-* 02:30:00 Europe/Moscow" in timer
    assert "Persistent=true" in timer


def test_009_backup_override_mounts_host_dir_outside_clone() -> None:
    text = (ROOT / "deploy/backup/compose.backup.yml").read_text(encoding="utf-8")
    assert ":/backups" in text
    assert "/var/backups/" in text


def test_009_readme_points_upgrade_to_one_backup_command() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert (
        "Перед обновлением стека снимите копию: `docker exec <проект>-api-1 gtrack backup`" in text
    )
    assert "Before upgrading the stack take a copy" in text


def test_009_host_script_never_touches_foreign_dirs() -> None:
    text = (ROOT / "deploy/backup/host/gtrack-backup").read_text(encoding="utf-8")
    assert "[0-9]{8}T[0-9]{6}Z" in text, "ротация только по шаблону своих каталогов"
    assert "umask 077" in text


def test_009_drill_protocol_recorded() -> None:
    text = (ROOT / "docs/acceptance/backup-restore-drill.md").read_text(encoding="utf-8")
    assert "Учение 1 — 2026-11-08" in text and "≤ 60 мин" in text
