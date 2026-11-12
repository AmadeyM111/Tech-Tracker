# Резервные копии GTrack (spec 009)

Копия — один файл `gtrack-backup-<UTC>.tar` (0600): `db.dump` (`pg_dump -Fc`), `appdata.tar`
(каталог данных без `exports/`), `manifest.json` (ревизия схемы, sha256). Команда сама проверяет
копию и оставляет `BACKUP_KEEP` (14) последних. Шифрования нет, копии лежат на том же сервере
(до решения ИБ) — команда предупреждает `same_device=1`.

## Установка (systemd)

```bash
sudo install -d -o 10001 -g 10001 -m 0700 /var/backups/gtrack-app
# api с каталогом копий
docker compose -f docker-compose.yml -f deploy/backup/compose.backup.yml up -d --wait api
# имя контейнера api (docker ps)
sudo install -d -m 0755 /etc/gtrack
echo 'GTRACK_API_CONTAINER=<проект>-api-1' | sudo tee /etc/gtrack/backup.env
sudo install -m 0644 deploy/backup/gtrack-backup.service deploy/backup/gtrack-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now gtrack-backup.timer
sudo systemctl start gtrack-backup.service && journalctl -u gtrack-backup -n 20
```

На NixOS `/etc/systemd/system` только для чтения: юниты кладутся в
`/usr/local/lib/systemd/system`, а включение — симлинком в `timers.target.wants` там же (или
описываются в `configuration.nix`).

Cron вместо systemd: `30 23 * * * docker exec <проект>-api-1 gtrack backup` (23:30 UTC = 02:30 МСК).

## Откат релиза и пути юнитов

Пути юнитов: `/etc/systemd/system/` (NixOS — `/usr/local/lib/systemd/system/` или
`configuration.nix`); окружение — `/etc/gtrack/backup.env`. Откат кода и схемы (миграции
`0011`–`0013` только добавляют таблицы) описан в корневом `README.md`, раздел «R2: вложения,
копии, напоминания, откат».

## Состояние

- ТА видит плашку на экранах администрирования, если копий нет, последняя старше 26 ч
  (`BACKUP_STALE_HOURS`) или последний запуск упал; API — `GET /api/v1/admin/system/backup`.
- `gtrack bootstrap` предупреждает перед миграцией, если копии нет или она старше 24 ч.

## Восстановление на чистом стенде

```bash
docker compose -p <новый> up -d --wait db
docker compose -p <новый> -f docker-compose.yml -f deploy/backup/compose.backup.yml \
  run --rm --no-deps --entrypoint gtrack api restore /backups/gtrack-backup-<UTC>.tar --yes
docker compose -p <новый> up -d --wait            # bootstrap применит миграции
```

`gtrack restore` работает только с пустой БД и пустым каталогом данных (иначе код 2) и сначала
проверяет sha256. Порядок: данные распаковываются во временный каталог внутри `DATA_DIR`,
затем `pg_restore` (одна транзакция), затем данные переносятся на место; сбой до переноса
оставляет обе цели пустыми, и команду можно повторить.

Восстановление поверх работающей системы — `scripts/restore.sh -p <проект> -b <файл.tar>`: скрипт
принимает файл `gtrack-backup-<UTC>.tar` (проверяет состав и сверяет sha256 с `manifest.json`)
или каталог старого формата (`db.dump`, `appdata.tar`, `SHA256SUMS`). Без скрипта вручную:
`tar -xf gtrack-backup-<UTC>.tar`, сверить `sha256sum db.dump appdata.tar` с `manifest.json`,
остановить api, пересоздать БД, `pg_restore --no-owner --no-privileges --exit-on-error -d <БД> db.dump`,
распаковать `appdata.tar` в пустой каталог данных, запустить api (миграции применятся при старте).

## Временный вариант без CLI (`host/`)

`host/gtrack-backup` — скрипт хоста (pg_dump через `docker exec` в контейнер db, каталоги
`/var/backups/gtrack/<UTC>/`, 14 копий). С 2026-11-08 работает на сервере пилота до выкатки
spec 009; после выкатки заменяется таймером выше (spec 009, Q-4). Протокол учения —
`docs/acceptance/backup-restore-drill.md`.

## Напоминания о сроках (spec 012)

`gtrack-notify-due.service` и `.timer` ставятся так же, как `gtrack-backup` (тот же
`/etc/gtrack/backup.env`); запуск — ежедневно в 09:00 МСК. Cron: `0 6 * * * docker exec <проект>-api-1 gtrack notify-due`.
