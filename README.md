# GOSTracker - единый трекер для ведения воронки клиентов, проектов и задач сотрудников

GOSTracker is a self-hosted tracker for client pipelines, projects and employee tasks.

Документация на двух языках / Documentation in two languages:
[Русский](#быстрый-старт) | [English](#quick-start)

## Быстрый старт

Состояние: MVP-демо таск-трекера (R1, решение владельца продукта -
`docs/adr/0012-mvp-task-tracker-first.md`): вход, роли, управление учётными записями, журнал
аудита, проекты, задачи с подзадачами, комментарии, канбан-доска и демо-данные. Что входит и что
отложено - в разделе «Состав MVP-демо и что отложено» ниже; подробный план -
`specs/001-pilot-r1/plan.md`.

Нужны Docker с плагином Compose v2 и свободные порты 80 и 443 (как их сменить - ниже).

```bash
git clone <URL репозитория> gostracker && cd gostracker
# все следующие команды выполняйте в каталоге клона
cp .env.example .env
docker compose up -d --build --wait
docker compose exec api cat /data/secrets/initial-admin-password.txt
```

Откройте `https://localhost/` (или имя/адрес вашего сервера). Войдите под логином из файла
(по умолчанию `admin`) и паролем из файла; система потребует сменить пароль сразу после входа.
После смены пароля файл с первоначальным паролем удаляется автоматически.

Первый запуск занимает несколько минут: собираются образы `api` и `web`. Если `docker compose up`
запускали без `-d`, команду с паролем выполните в другом терминале.

Команды `docker compose ...` выполняются в каталоге клона: имя проекта Compose по умолчанию - имя
этого каталога. Если стек запущен под другим именем (`COMPOSE_PROJECT_NAME` или ключ `-p`),
добавляйте то же имя ко всем командам: `docker compose -p <имя> exec api ...`.

### Состав MVP-демо и что отложено

R1 - прототип таск-трекера (MVP): приёмка R1 проходит по этому составу, остальное принято
владельцем продукта в следующую версию (`docs/adr/0012-mvp-task-tracker-first.md`).

Входит в MVP-демо:

- вход, роли, учётные записи и журнал аудита (этап R1.0);
- проекты: создание, правка названия и описания, участники, передача владения, мягкое удаление;
- задачи: название, описание, исполнитель, срок, приоритет, статус; подзадачи одного уровня и
  прогресс по ним;
- комментарии: простой текст, HTML вырезается, без упоминаний;
- личный список «Мои задачи» и список задач проекта с фильтрами по исполнителю и статусу;
- канбан-доска с перетаскиванием, ручным порядком карточек и клавиатурной заменой
  перетаскивания;
- опрос сервера (не реже раза в 15 с) на доске, в списках задач и в карточке задачи;
- демо-данные одной командой (см. ниже).

Отложено (не входит в MVP, вернётся в следующей версии):

- CRM: клиенты, контакты, сделки, воронка - отложено;
- метки - отложены;
- вложения (файлы к задачам) - отложены;
- упоминания и уведомления - отложены;
- корзина, восстановление и окончательное удаление: в MVP нет, отложены; удаление мягкое, а
  удалённое не видно и отвечает 404;
- поиск, лента активности проекта, архив проекта - отложены;
- фильтры по сроку и общий список задач по всем проектам (FR-27a) - отложены;
- экспорт и импорт - отложены;
- резервная копия БД - отложена: прототип показывают, работу в нём не ведут;
- замеры производительности и автоматические e2e-тесты браузера - отложены.

### Демо-данные и пароли демо-пользователей

На свежей установке (после `docker compose up -d --build --wait`) загрузите демо-данные одной
командой и прочитайте пароли:

```bash
docker compose exec api gostracker demo-data
docker compose exec api cat /data/secrets/demo-passwords.txt
```

- Команда создаёт 12 учётных записей (`demo.ta`, `demo.mixed`, `demo.ba1`…`demo.ba3`,
  `demo.user1`…`demo.user7`), 2 проекта («Внедрение трекера» и «Подготовка пилота»), 30 задач
  (из них 6 подзадач) и около 20 комментариев; сделок нет. Выполняется одной транзакцией;
  `--seed` задаёт seed генератора (по умолчанию 1).
- Пароли пишутся в `/data/secrets/demo-passwords.txt` внутри контейнера `api` (том `appdata`,
  права 0600): по строке `login=...` и `password=...` через табуляцию. В stdout, stderr и логи
  пароли не попадают, команда печатает только путь к файлу и счётчики. При первом входе каждый
  демо-пользователь обязан сменить пароль.
- Повторный запуск отказывает (код 2, данные не меняются), если в базе уже есть проекты, задачи
  или пользователи сверх первого технического администратора.
- **Если файл паролей потерян** (или том `appdata` пересоздан), пароль читать больше негде:
  войдите первым техническим администратором и для каждого демо-пользователя выполните
  `reset-password` (`POST /api/v1/admin/users/{id}/reset-password`; в интерфейсе - «Сбросить
  пароль» на странице «Учётные записи») либо переустановите стек с удалением тома:
  `docker compose down -v` и новый `up` (все данные, включая БД, будут потеряны; только для
  тестового проекта).
- **Предупреждение `ENV=production`.** В поставляемом стеке `ENV=production` задан по умолчанию,
  поэтому `demo-data` всегда печатает в stderr предупреждение (код возврата не меняется).
  Смысл: учётные записи `demo.*` общеизвестны. Перед реальной работой в такой установке
  заблокируйте все `demo.*` («Заблокировать» на странице «Учётные записи»): удаления учётных
  записей нет. Для показа заказчику используйте отдельную установку.

### Сценарий демо (UF-2…UF-6)

Чек-лист для ручной проверки и показа - `docs/acceptance/mvp-demo.md`. Сценарий UF-2…UF-6:

- UF-2: технический администратор входит, заводит учётную запись, назначает роль,
  блокирует и разблокирует пользователя;
- UF-3: бизнес-администратор (например, `demo.ba1`) создаёт проект, добавляет участников, ставит
  задачи со сроками и исполнителями; исполнитель видит их в списке «Мои задачи»;
- UF-4: исполнитель делит задачу на подзадачи и закрывает их, прогресс родителя растёт;
- UF-5: участник перетаскивает карточку на доске в другую колонку, второй участник после опроса
  (до 15 с) видит новый статус;
- UF-6: участник фильтрует список задач проекта по исполнителю и статусу, открывает карточку и
  оставляет комментарий;
- права бизнес-администратора (D-54): `demo.ba2` - участник, но не владелец проекта «Внедрение
  трекера» (владелец - `demo.ba1`) - открывает чужую задачу, и правка и удаление ему
  недоступны (элементов нет или 403 с русским сообщением); после передачи владения (получатель -
  участник с ролью «Бизнес-администратор» или «Смешанная роль») они доступны. Это осознанное
  правило. Перенос карточки на доске без прав (403) воспроизводится так: `demo.userN` переносит
  карточку, где он и не исполнитель, и не автор.

### Где взять пароль первого технического администратора

Пароль не задаётся в `.env`: он генерируется при первом запуске и записывается в файл
`/data/secrets/initial-admin-password.txt` внутри контейнера `api` (том `appdata`, права 0600).
В логи и в стандартный вывод пароль не попадает. Прочитать файл можно командой
`docker compose exec api cat /data/secrets/initial-admin-password.txt`; формат -
две строки `login=...` и `password=...`. Логин первого администратора задаёт
`INITIAL_ADMIN_LOGIN` в `.env` (по умолчанию `admin`); он читается без обрезки, поэтому значение
не должно содержать пробелов и перевода строки по краям - иначе `api` не запустится.

### Самоподписанный сертификат и подключение своего

По умолчанию `web` при первом запуске создаёт самоподписанный сертификат (EC prime256v1,
825 дней) и хранит его в томе `tls-generated`; при перезапусках он не меняется. Браузер покажет
предупреждение о недоверенном сертификате: для пилота на своём сервере подтвердите исключение.

Чтобы подключить свой сертификат, положите в каталог `deploy/tls` два файла: `tls.crt`
(сертификат, при необходимости с цепочкой) и `tls.key` (закрытый ключ без пароля), затем
выполните `docker compose restart web`. Каталог монтируется только на чтение; файлы из него не
попадают в git и в образы (подробности - `deploy/tls/README.md`). Если положен только один из
двух файлов, в логе `web` будет предупреждение, а использоваться будет самоподписанный сертификат.
Если пара `tls.crt`/`tls.key` не совпадает (ключ не от этого сертификата), `web` не запускается:
выход с кодом 1 и понятной причиной в логе. Сертификат оператора не перевыпускается: просроченный
используется как есть, следить за сроком - задача оператора.

Особенности самоподписанного сертификата:

- имя берётся из `TLS_SERVER_NAME` (`.env`, по умолчанию `localhost`); в сертификат также входят
  `localhost` и `127.0.0.1`. После смены `TLS_SERVER_NAME` ранее сгенерированный сертификат не
  перевыпускается: выполните `docker compose down` (без `-v`), затем
  `docker volume rm <проект>_tls-generated` (`docker volume ls` покажет имя; имя проекта по
  умолчанию - имя каталога; после `stop` том занят контейнером), затем `docker compose up -d`.
  Значение `TLS_SERVER_NAME` - не длиннее 64 символов, только `[A-Za-z0-9.-]`, не начинается с
  `.` или `-`;
- если в `TLS_SERVER_NAME` указан IP-адрес, он попадёт в SAN как запись типа DNS, а не IP;
  браузер предупредит о несоответствии имени - используйте имя хоста (`127.0.0.1` в SAN
  записан как IP - это нормально);
- битую пару или сгенерированный сертификат с истёкшим сроком (825 дней; сертификат, созданный в
  октябре 2026, истекает около января 2029) `web` перевыпускает сам при перезапуске.

### Порты

Порты публикует только `web`: `HTTP_PORT` (по умолчанию 80, только переадресация на HTTPS)
и `HTTPS_PORT` (по умолчанию 443). Чтобы сменить порты, задайте в `.env` оба значения -
например `HTTP_PORT=8080` и `HTTPS_PORT=8443` - и выполните `docker compose up -d`. Порты `db`
и `api` наружу не публикуются. Если порт HTTPS нестандартный, адрес в браузере -
`https://<сервер>:8443/`, переадресация с HTTP учитывает этот порт.

Cookie сессии всегда с флагом `Secure` (в поставляемой конфигурации значение зафиксировано в
`docker-compose.yml`), поэтому вход работает только по HTTPS.

### Настройки `.env`

`.env.example` содержит значения по умолчанию; `.env` в git не попадает.

- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` - БД. `POSTGRES_PASSWORD`
  подставляется в `DATABASE_URL` без URL-кодирования: `@` ломает подключение, `%XX`
  декодируется в другой символ, `$` подставляется самим compose. Используйте
  только буквы и цифры.
  Смена пароля после первой инициализации БД не меняет пароль внутри БД (том `pgdata`
  уже создан); пароль внутри БД меняется отдельно (`ALTER USER`).
- `HTTP_PORT`, `HTTPS_PORT`, `TLS_SERVER_NAME` - см. выше.
- `INITIAL_ADMIN_LOGIN` - логин первого администратора, только при первом запуске.
- `ARGON2_TIME_COST`, `ARGON2_MEMORY_COST_KIB`, `ARGON2_PARALLELISM` - параметры хеширования
  паролей (по умолчанию 3, 131072 КиБ, 2).
- `SECRET_KEY` в `.env.example` нет и из `.env` в `api` не пробрасывается: ключ создаётся один
  раз и хранится в `/data/secrets/secret_key` (том `appdata`, 32 байта, режим 0600). Если
  `SECRET_KEY` всё же задан в окружении `api` (например, в своём compose-файле), значение короче
  32 байт - ошибка запуска `api`; заглушка `change-me` (без учёта регистра и пробелов по краям)
  игнорируется с предупреждением, используется ключ из `/data/secrets/secret_key`. Сохраняйте
  том `appdata` при обновлении: по этому ключу вычисляются идентификаторы сессий.

### Учётные записи не удаляются

Удаления учётных записей в интерфейсе и API нет и не предусмотрено: пользователя можно
заблокировать (и сбросить пароль, завершить сессии, сменить или снять роль), но не удалить.

### Предупреждения оператору

- **Откат миграций.** `downgrade 0002` (откат ревизии 0002, то есть `alembic downgrade 0001`
  и ниже) молча удаляет таблицу журнала событий (аудита) вместе со всеми записями, даже если она
  не пуста. Журнал - append-only: триггеры БД запрещают `UPDATE`, `DELETE` и `TRUNCATE`, но не
  защищают от отката миграции и от суперпользователя БД. Перед откатом сделайте копию БД.
- **Нагрузка на память.** Хеширование паролей Argon2id использует 128 МиБ на одну операцию
  (`ARGON2_MEMORY_COST_KIB=131072`). Параллельные хеши выполняются в пуле потоков
  `min(32, CPU + 4)`, поэтому при одновременных входах и сменах паролей пиковое потребление
  памяти `api` на стенде 3 vCPU составляет около 900 МиБ. Планируйте память с запасом;
  уменьшение `ARGON2_MEMORY_COST_KIB` ослабляет защиту паролей.
- **Запуск API.** Команда `gostracker` (bootstrap, openapi, hash-bench, maintenance, demo-data) API не
  запускает. Запускайте `api` командой `uvicorn app.main:app` (как в образе), не
  программным `uvicorn.run(app)`: при таком запуске `dictConfig` uvicorn
  вернёт обработчики без фильтра секретов, и значения паролей и токенов могут попасть в лог.
- **Доверие к прокси.** Образ запускает uvicorn с `--proxy-headers --forwarded-allow-ips='*'`.
  Это допустимо, пока порт `api` (8000) не публикуется. Если публикуете порт, сузьте
  `--forwarded-allow-ips` до адреса прокси.
- **Журнал доступа nginx.** access-log контейнера `web` пишет полный запрос, включая строку
  query. Не передавайте секреты в URL. Журнал самого `api` пишет путь без query.
- **Таймауты.** У `db` заданы `lock_timeout=30s` и `idle_in_transaction_session_timeout=60s`:
  при ожидании блокировки дольше 30 с или при взаимоблокировке запрос получает ответ 503 с кодом
  `service_busy` и заголовком `Retry-After: 5` (повторите через 5 с; интерфейс показывает
  «Сервис занят, повторите действие через несколько секунд»), зависшая транзакция закрывается
  через 60 с. Если 503 не прекращаются,
  перезапустите `api` (`docker compose restart api`): его соединения с БД закрываются, открытые
  транзакции откатываются. Прокси `web` ждёт ответ `api` до 60 с. Не обновляйте стек во время
  резервного копирования.
- **Битый JSON.** Синтаксически некорректное тело запроса к API получает ответ 400
  (`bad_request`) до проверки входа и прав; раньше приходил 422. Если JSON валиден, а поля
  неверны, порядок прежний: 401/403, затем 422.
- **Блокировки при старте.** Миграции и первый запуск (bootstrap) выполняют `SET lock_timeout = 0`
  и ждут блокировку бессрочно. Если блокировка зависла, `api` не станет healthy;
  примерно через 100 с он получит статус unhealthy, а `docker compose up` завершится ошибкой
  `dependency failed to start: container …-api-1 is unhealthy`. Завершите блокирующий сеанс в
  БД - `api` продолжит запуск сам; затем повторите `docker compose up -d`.
- **Перезапуск.** У `db`, `api` и `web` задано `restart: unless-stopped`: после перезагрузки
  хоста и демона Docker стек поднимается сам. Контейнер, остановленный вручную (`docker stop`,
  `docker kill`), сам не поднимается; контейнер со статусом unhealthy Docker не перезапускает.
- **Состояние `web`.** Адрес `/healthz` отвечает сам nginx (200, `ok`), в том числе снаружи, и не
  зависит от `api`: `web` остаётся healthy при упавшем `api`, на `/api` тогда приходит HTML-ответ
  502. Проверка живости `api` (`/api/v1/health`) БД не проверяет.
- **TLS_SERVER_NAME.** Значение проверяется только на допустимые символы; синтаксически неверные
  имена (`a..b`, `a-`) проходят проверку - сертификат для них бесполезен.
- **Удаление томов.** `docker compose down -v` удаляет тома, в том числе БД (`pgdata`) и
  `appdata`: том содержит `secret_key`, файл пароля первого администратора
  (`initial-admin-password.txt`) и файл паролей демо-пользователей (`demo-passwords.txt`);
  вложений пока нет. Используйте `-v` только для тестового проекта (см. ниже).

### Регулярное обслуживание

В MVP команда `gostracker maintenance` удаляет только истёкшие сессии пользователей (простой
или абсолютный срок). Корзины в MVP нет (она отложена), поэтому чистить больше нечего. Без
регулярного запуска истёкшие сессии остаются в БД: на работу это не влияет, но таблица растёт.
Запускайте команду раз в сутки, например из `crontab` пользователя, у которого есть доступ к
Docker:

```
17 3 * * * cd /path/to/gostracker && { date -u; docker compose exec -T api gostracker maintenance; } >> /var/log/gostracker-maintenance.log 2>&1
```

- `/path/to/gostracker` - замените на каталог клона репозитория (из него Compose берёт
  `docker-compose.yml`, `.env` и имя проекта). Если стек запущен под другим именем
  (`COMPOSE_PROJECT_NAME` или `-p`), укажите его: `docker compose -p <имя> exec -T api ...`.
- `date -u` пишет в журнал время запуска в UTC перед результатом команды.
- Ключ `-T` отключает TTY, без него `cron` не сможет выполнить `docker compose exec`.

- Для проверки перед первым запуском: `docker compose exec -T api gostracker maintenance --dry-run`
  только считает, что было бы очищено, и ничего не меняет.
- Вывод - ровно восемь строк `ключ=значение` (`dry_run`, `sessions_expired`, `projects_purged`,
  `tasks_purged`, `comments_purged`, `attachments_purged`, `files_removed`,
  `orphan_files_removed`); в MVP значимо только `sessions_expired`, остальные счётчики равны 0.
  При ошибке команда пишет сообщение в stderr и завершается с кодом 1.
- Команда безопасна при работающем API: обработка идёт короткими пакетами, строки, занятые
  запросами пользователей, пропускаются; повторный запуск ничего не ломает.
- Фонового планировщика в R1 нет: сервиса compose для обслуживания нет, `api` его сам не
  запускает. Запуск по расписанию остаётся за оператором.

## Разработка

Dev-конфигурация `deploy/compose.dev.yml` подключается только явно и публикует порт БД
`127.0.0.1:5432`; файлов `docker-compose.override.yml` в репозитории нет намеренно.

```bash
# БД для разработки и тестов
docker compose -p gostracker-dev -f docker-compose.yml -f deploy/compose.dev.yml up -d db

# окружение Python 3.12
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e "backend[dev]"

# настройки разработки из deploy/dev.env.example (приложение файл .env не читает)
set -a; . deploy/dev.env.example; set +a

gostracker bootstrap                                  # миграции, ключ, первый администратор
uvicorn app.main:app --reload --app-dir backend       # API на :8000, /docs - Swagger
cd frontend && npm ci && npm run dev                  # фронтенд на :5173, прокси /api -> :8000
```

В dev-режиме пароль первого администратора лежит в `.data/secrets/initial-admin-password.txt`
(`DATA_DIR=./.data` из `deploy/dev.env.example`).

### Node.js

Фронтенду нужен Node.js `^22.12 || ^24 || >=26` (поле `engines` в `frontend/package.json`;
образ сборки - `node:22-alpine`). Менеджеры версий вроде `proto` подставляют shim `node`,
который может запускать старую версию: проверьте `node --version` и при необходимости
установите нужную (`proto install node 24`) либо поставьте её первой в `PATH`.
Подробнее - `frontend/README.md`.

### Тесты и проверки

```bash
export TEST_DATABASE_URL=postgresql+asyncpg://tracker:tracker@localhost:5432/tracker_test
pytest -q backend/tests          # backend; инфраструктурные тесты стека пропускаются
bash scripts/check.sh            # линтер, типы, alembic check, pytest, проверки фронтенда
```

`TEST_DATABASE_URL` по умолчанию указывает на `tracker_test` на `localhost:5432`; имя БД обязано
оканчиваться на `_test`. Автоматически базу создаёт только pytest; шаг `alembic check` в
`scripts/check.sh` идёт раньше pytest и требует уже существующую тестовую БД - создайте её один раз
(`createdb tracker_test` или `CREATE DATABASE tracker_test`). Два теста миграций проверяют имя БД
`tracker_test` жёстко, поэтому используйте именно это имя. Рабочую БД `tracker` тесты не трогают.

Тесты работающего стека (`infra_stack`) требуют **свежий** отдельный проект, чтобы не задеть ваш
стек; порядок строго такой:

```bash
HTTP_PORT=18080 HTTPS_PORT=18443 docker compose -p gostracker-infratest up -d --build --wait
GT_INFRA_STACK=1 GT_INFRA_PROJECT=gostracker-infratest HTTP_PORT=18080 HTTPS_PORT=18443 \
  pytest -q -m infra_stack backend/tests/infra
docker compose -p gostracker-infratest down -v
```

Перед повторным прогоном обязательно выполните `down -v` для проекта `gostracker-infratest`:
на «использованном» стеке тесты первого запуска падают с сообщением «нужен свежий стек».

### Прочее

- Модель данных (R1.0 и MVP) - `docs/data-model.md`.
- Контракт API - `docs/api/openapi.json` (генерируется `scripts/gen-api.sh`).
- Состояние проекта - `docs/STATE.md`, правила для агентов - `AGENTS.md`.

## Quick start

State: the MVP demo of the task tracker (R1, a product owner decision -
`docs/adr/0012-mvp-task-tracker-first.md`): login, roles, account management, audit log,
projects, tasks with subtasks, comments, a kanban board and demo data. What is included and what
is deferred is listed in "What the MVP demo includes and what is deferred" below; the detailed
plan is `specs/001-pilot-r1/plan.md`.

You need Docker with the Compose v2 plugin and free ports 80 and 443 (see below how to change
them).

```bash
git clone <repository URL> gostracker && cd gostracker
# run all the following commands in the clone directory
cp .env.example .env
docker compose up -d --build --wait
docker compose exec api cat /data/secrets/initial-admin-password.txt
```

Open `https://localhost/` (or the name/address of your server). Log in with the login and the
password from that file (the login is `admin` by default); you must change the password right
after the first login. The file with the initial password is removed automatically once the
password is changed.

The first start takes a few minutes: the `api` and `web` images are built. If you ran
`docker compose up` without `-d`, run the password command in another terminal.

Run the `docker compose ...` commands in the clone directory: the default Compose project name
is the name of that directory. If the stack runs under another name (`COMPOSE_PROJECT_NAME` or
the `-p` option), add the same name to every command: `docker compose -p <name> exec api ...`.

### What the MVP demo includes and what is deferred

R1 is a task tracker prototype (MVP): the R1 acceptance covers exactly this scope; the rest was
moved to the next version by the product owner (`docs/adr/0012-mvp-task-tracker-first.md`).

Included in the MVP demo:

- login, roles, accounts and the audit log (stage R1.0);
- projects: create, edit name and description, members, ownership transfer, soft delete;
- tasks: title, description, assignee, due date, priority, status; one-level subtasks and their
  progress;
- comments: plain text, HTML is stripped, no mentions;
- the personal "My tasks" list and the project task list with assignee and status filters;
- a kanban board with drag and drop, manual card order and a keyboard replacement for dragging;
- server polling (at least every 15 s) on the board, task lists and the task card;
- demo data with one command (see below).

Deferred (not part of the MVP, planned for the next version):

- CRM: clients, contacts, deals, pipeline - deferred;
- labels - deferred;
- attachments (files on tasks) - deferred;
- mentions and notifications - deferred;
- trash, restore and permanent delete: not in the MVP, deferred; deletion is soft, and a deleted
  item is hidden and answers 404;
- search, the project activity feed, project archive - deferred;
- due-date filters and a cross-project task list (FR-27a) - deferred;
- export and import - deferred;
- database backup - deferred: the prototype is shown, not used for real work;
- performance measurements and automated browser e2e tests - deferred.

### Demo data and demo user passwords

On a fresh installation (after `docker compose up -d --build --wait`) load the demo data with
one command and read the passwords:

```bash
docker compose exec api gostracker demo-data
docker compose exec api cat /data/secrets/demo-passwords.txt
```

- The command creates 12 accounts (`demo.ta`, `demo.mixed`, `demo.ba1`…`demo.ba3`,
  `demo.user1`…`demo.user7`), 2 projects ("Внедрение трекера" and "Подготовка пилота"), 30
  tasks (6 of them subtasks) and about 20 comments; there are no deals. It runs in a single
  transaction; `--seed` sets the generator seed (1 by default).
- The passwords are written to `/data/secrets/demo-passwords.txt` inside the `api` container
  (the `appdata` volume, mode 0600): one `login=...` and `password=...` pair per line, separated
  by a tab. They never appear in stdout, stderr or logs; the command prints only the file path
  and counters. Every demo user must change the password at the first login.
- A repeated run is refused (exit code 2, data unchanged) if the database already has projects,
  tasks or users besides the first technical administrator.
- **If the password file is lost** (or the `appdata` volume was recreated), there is nowhere to
  read the passwords from: log in as the first technical administrator and run `reset-password`
  for every demo user (`POST /api/v1/admin/users/{id}/reset-password`; in the UI it is "Сбросить
  пароль" on the accounts page), or reinstall the stack removing the volume: `docker compose
  down -v` and a new `up` (all data including the database is lost; for a test project only).
- **The `ENV=production` warning.** The shipped stack has `ENV=production` by default, so
  `demo-data` always prints a warning to stderr (the exit code is not affected). Meaning: the
  `demo.*` accounts are publicly known. Before real work in such an installation, block every
  `demo.*` account ("Заблокировать" on the accounts page): accounts cannot be deleted. Use a
  separate installation for customer demos.

### Demo scenario (UF-2…UF-6)

The checklist for manual verification and for the demo is `docs/acceptance/mvp-demo.md`. The
scenario UF-2…UF-6:

- UF-2: the technical administrator logs in, creates an account, assigns a role, blocks and
  unblocks a user;
- UF-3: a business administrator (for example `demo.ba1`) creates a project, adds members and
  sets tasks with due dates and assignees; an assignee sees them in "My tasks";
- UF-4: an assignee splits a task into subtasks and closes them, the parent progress grows;
- UF-5: a member drags a card on the board to another column, a second member sees the new status
  after polling (within 15 s);
- UF-6: a member filters the project task list by assignee and status, opens a card and leaves a
  comment;
- business administrator rights (D-54): `demo.ba2` - a member but not the owner of the project
  "Внедрение трекера" (the owner is `demo.ba1`) - opens someone else's task, and editing and
  deleting are unavailable (no controls, or 403 with a Russian message); after ownership is
  transferred (the recipient is a member with the business administrator or mixed role) they
  become available. This is a deliberate rule. A board move without rights (403) is reproduced
  like this: `demo.userN` moves a card where he is neither the assignee nor the author.

### Where to find the first technical administrator password

The password is not set in `.env`: it is generated on the first start and written to
`/data/secrets/initial-admin-password.txt` inside the `api` container (the `appdata` volume,
mode 0600). It never appears in logs or standard output. Read it with
`docker compose exec api cat /data/secrets/initial-admin-password.txt`; the file has two lines,
`login=...` and `password=...`. The login of the first administrator is `INITIAL_ADMIN_LOGIN`
in `.env` (`admin` by default); it is read without trimming, so the value must not contain
leading or trailing spaces or a newline - otherwise `api` fails to start.

### Self-signed certificate and using your own

By default `web` generates a self-signed certificate on the first start (EC prime256v1,
825 days) and keeps it in the `tls-generated` volume; it does not change on restarts. The
browser shows a warning about an untrusted certificate: for a pilot on your own server, accept
the exception.

To use your own certificate, put two files into the `deploy/tls` directory: `tls.crt` (the
certificate, with the intermediate chain if needed) and `tls.key` (the private key without a
passphrase), then run `docker compose restart web`. The directory is mounted read-only; its
files are not committed to git and are not baked into images (details - `deploy/tls/README.md`).
If only one of the two files is present, `web` logs a warning and keeps using the self-signed
certificate. If the `tls.crt`/`tls.key` pair does not match (the key is not for this
certificate), `web` fails to start: it exits with code 1 and a clear reason in the log. The
operator certificate is never reissued: an expired one is used as is, watching the expiry date is
up to the operator.

Notes on the self-signed certificate:

- the name comes from `TLS_SERVER_NAME` (`.env`, `localhost` by default); `localhost` and
  `127.0.0.1` are included as well. After you change `TLS_SERVER_NAME` the previously generated
  certificate is not reissued: run `docker compose down` (without `-v`), then
  `docker volume rm <project>_tls-generated` (`docker volume ls` shows the name; the default
  project name is the directory name; after `stop` the volume is still held by the container),
  then `docker compose up -d`. The `TLS_SERVER_NAME` value is at most 64 characters, only
  `[A-Za-z0-9.-]`, and does not start with `.` or `-`;
- if `TLS_SERVER_NAME` is an IP address, it lands in the SAN as a DNS entry, not as an IP; the
  browser warns about a name mismatch - use a host name (`127.0.0.1` is written to the SAN as an
  IP - that is fine);
- a broken pair or a generated certificate past its 825 days (one created in October 2026
  expires around January 2029) is regenerated by `web` on restart.

### Ports

Only `web` publishes ports: `HTTP_PORT` (80 by default, it only redirects to HTTPS) and
`HTTPS_PORT` (443 by default). To change them, set both values in `.env` - for example
`HTTP_PORT=8080` and `HTTPS_PORT=8443` - and run `docker compose up -d`. The `db` and `api`
ports are not published. With a non-standard HTTPS port the address in the browser is
`https://<server>:8443/`; the HTTP redirect takes this port into account.

The session cookie always carries the `Secure` flag (the shipped configuration hardcodes it in
`docker-compose.yml`), so login works over HTTPS only.

### `.env` settings

`.env.example` holds the defaults; `.env` is not committed to git.

- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` - the database. `POSTGRES_PASSWORD` is
  substituted into `DATABASE_URL` without URL-encoding: `@` breaks the connection, `%XX`
  is decoded into another character, `$` is substituted by compose itself. Use only
  letters and digits. Changing the password after the database was first initialized does not change the
  password inside the database (the `pgdata` volume already exists); change it separately
  (`ALTER USER`).
- `HTTP_PORT`, `HTTPS_PORT`, `TLS_SERVER_NAME` - see above.
- `INITIAL_ADMIN_LOGIN` - the login of the first administrator, used on the first start only.
- `ARGON2_TIME_COST`, `ARGON2_MEMORY_COST_KIB`, `ARGON2_PARALLELISM` - password hashing
  parameters (defaults 3, 131072 KiB, 2).
- `SECRET_KEY` is not in `.env.example` and is not passed from `.env` to `api`: the key is
  created once and stored in `/data/secrets/secret_key` (the `appdata` volume, 32 bytes, mode
  0600). If `SECRET_KEY` is set in the `api` environment anyway (for example in your own compose
  file), a value shorter than 32 bytes is a startup error of `api`; the `change-me` placeholder
  (case-insensitive, surrounding spaces ignored) is ignored with a warning, and the key from
  `/data/secrets/secret_key` is used. Keep the `appdata` volume when upgrading: session identifiers are derived from this
  key.

### Accounts cannot be deleted

There is no UI and no API endpoint for deleting accounts, and none is planned: a user can be
blocked (and have the password reset, sessions revoked, role changed or removed) but accounts
cannot be deleted.

### Operator warnings

- **Migration downgrade.** `downgrade 0002` (reverting revision 0002, i.e. `alembic downgrade
  0001` and below) silently drops the event log (audit journal) table together with all its
  rows, even when it is not empty. The log is append-only: database triggers forbid `UPDATE`,
  `DELETE` and `TRUNCATE`, but they do not protect against a migration downgrade or a database
  superuser. Back up the database before downgrading.
- **Memory.** Argon2id password hashing uses 128 MiB per operation
  (`ARGON2_MEMORY_COST_KIB=131072`). Concurrent hashes run in a thread pool of
  `min(32, CPU + 4)`, so with simultaneous logins and password changes the peak memory of `api`
  on a 3 vCPU host is about 900 MiB. Plan memory with a margin; lowering
  `ARGON2_MEMORY_COST_KIB` weakens password protection.
- **Starting the API.** The `gostracker` command (bootstrap, openapi, hash-bench, maintenance, demo-data) does
  not start the API. Run `api` with `uvicorn app.main:app` (as the image does), not
  programmatically with `uvicorn.run(app)`: that way uvicorn's
  `dictConfig` restores handlers without the secrets filter, and passwords or tokens may leak
  into the log.
- **Proxy trust.** The image starts uvicorn with `--proxy-headers --forwarded-allow-ips='*'`.
  This is acceptable while the `api` port (8000) is not published. If you publish the port,
  narrow `--forwarded-allow-ips` to the proxy address.
- **nginx access log.** The access log of the `web` container records the full request,
  including the query string. Do not pass secrets in URLs. The `api` own log keeps the path
  without the query.
- **Timeouts.** `db` runs with `lock_timeout=30s` and `idle_in_transaction_session_timeout=60s`:
  a request that waits for a lock longer than 30 s, or hits a deadlock, gets a 503 response
  with the code `service_busy` and the `Retry-After: 5` header (retry in 5 s; the UI shows
  "Сервис занят, повторите действие через несколько секунд"), and a stuck transaction is closed
  after 60 s. If 503 does not go away, restart `api` (`docker compose restart api`): its database
  connections are closed and open transactions are rolled back. The `web` proxy waits for `api`
  up to 60 s. Do not upgrade the stack during a backup.
- **Malformed JSON.** A syntactically invalid request body gets 400 (`bad_request`) before the
  login and permission checks; it used to be 422. If the JSON is valid but the fields are
  wrong, the order is unchanged: 401/403, then 422.
- **Locks at startup.** Migrations and the first-run bootstrap execute `SET lock_timeout = 0`
  and wait for a lock indefinitely. If a lock is stuck, `api` does not become healthy;
  after about 100 s it gets the unhealthy status and `docker compose up` fails with
  `dependency failed to start: container …-api-1 is unhealthy`. Terminate the blocking session
  in the database - `api` then continues to start by itself; afterwards repeat
  `docker compose up -d`.
- **Restart policy.** `db`, `api` and `web` use `restart: unless-stopped`: after a host or
  Docker daemon reboot the stack comes back by itself. A container stopped manually
  (`docker stop`, `docker kill`) does not come back by itself; Docker does not restart a
  container that is unhealthy.
- **`web` state.** The `/healthz` address is answered by nginx itself (200, `ok`), also from
  outside, and does not depend on `api`: `web` stays healthy while `api` is down, and `/api`
  then returns an HTML 502. The `api` health check (`/api/v1/health`) does not probe the
  database.
- **TLS_SERVER_NAME.** The value is checked for allowed characters only; syntactically invalid
  names (`a..b`, `a-`) pass the check - a certificate for them is useless.
- **Removing volumes.** `docker compose down -v` removes the volumes, including the database
  (`pgdata`) and `appdata`: that volume contains `secret_key`, the first administrator password
  file (`initial-admin-password.txt`) and the demo users password file (`demo-passwords.txt`);
  there are no attachments yet. Use `-v` for the test project only (see below).

### Regular maintenance

In the MVP the `gostracker maintenance` command deletes only expired user sessions (idle or
absolute timeout). There is no trash in the MVP (it is deferred), so there is nothing else to
clean up. Without regular runs expired sessions stay in the database: work is not affected,
but the table grows. Run the command once a day, for example from the `crontab` of a user
who has access to Docker:

```
17 3 * * * cd /path/to/gostracker && { date -u; docker compose exec -T api gostracker maintenance; } >> /var/log/gostracker-maintenance.log 2>&1
```

- `/path/to/gostracker` - replace it with the clone directory of the repository (Compose takes
  `docker-compose.yml`, `.env` and the project name from it). If the stack runs under another
  name (`COMPOSE_PROJECT_NAME` or `-p`), give it: `docker compose -p <name> exec -T api ...`.
- `date -u` writes the start time in UTC to the log before the command output.
- The `-T` flag disables the TTY; without it `cron` cannot run `docker compose exec`.

- To check before the first run: `docker compose exec -T api gostracker maintenance --dry-run`
  only counts what would be cleaned up and changes nothing.
- The output is exactly eight `key=value` lines (`dry_run`, `sessions_expired`,
  `projects_purged`, `tasks_purged`, `comments_purged`, `attachments_purged`, `files_removed`,
  `orphan_files_removed`); in the MVP only `sessions_expired` is meaningful, the other counters
  are 0. On failure the command writes a message to stderr and exits with code 1.
- The command is safe while the API is running: it works in short batches, rows held by user
  requests are skipped, and a repeated run breaks nothing.
- There is no background scheduler in R1 and no compose service for maintenance; `api` does
  not start it by itself. Scheduled runs are up to the operator.

## Development

The dev configuration `deploy/compose.dev.yml` is attached explicitly only and publishes the
database port `127.0.0.1:5432`; the repository intentionally has no `docker-compose.override.yml`.

```bash
# database for development and tests
docker compose -p gostracker-dev -f docker-compose.yml -f deploy/compose.dev.yml up -d db

# Python 3.12 environment
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e "backend[dev]"

# development settings from deploy/dev.env.example (the app does not read .env)
set -a; . deploy/dev.env.example; set +a

gostracker bootstrap                                  # migrations, key, first administrator
uvicorn app.main:app --reload --app-dir backend       # API on :8000, /docs - Swagger
cd frontend && npm ci && npm run dev                  # frontend on :5173, /api -> :8000 proxy
```

In dev mode the first administrator password is in `.data/secrets/initial-admin-password.txt`
(`DATA_DIR=./.data` from `deploy/dev.env.example`).

### Node.js

The frontend needs Node.js `^22.12 || ^24 || >=26` (the `engines` field in
`frontend/package.json`; the build image is `node:22-alpine`). Version managers such as `proto`
install a `node` shim that may run an older version: check `node --version` and, if needed,
install the right one (`proto install node 24`) or put it first in `PATH`. More in
`frontend/README.md`.

### Tests and checks

```bash
export TEST_DATABASE_URL=postgresql+asyncpg://tracker:tracker@localhost:5432/tracker_test
pytest -q backend/tests          # backend; the running-stack infra tests are skipped
bash scripts/check.sh            # linter, types, alembic check, pytest, frontend checks
```

`TEST_DATABASE_URL` defaults to `tracker_test` on `localhost:5432`; the database name must end
with `_test`. Only pytest creates the database automatically; the `alembic check` step in
`scripts/check.sh` runs before pytest and needs an already existing test database - create it
once (`createdb tracker_test` or `CREATE DATABASE tracker_test`). Two migration tests check the
database name `tracker_test` strictly, so use exactly that name. The working `tracker` database
is not touched by tests.

Running-stack tests (`infra_stack`) need a **fresh**, separate project so that your own stack
stays untouched; the order is strict:

```bash
HTTP_PORT=18080 HTTPS_PORT=18443 docker compose -p gostracker-infratest up -d --build --wait
GT_INFRA_STACK=1 GT_INFRA_PROJECT=gostracker-infratest HTTP_PORT=18080 HTTPS_PORT=18443 \
  pytest -q -m infra_stack backend/tests/infra
docker compose -p gostracker-infratest down -v
```

Always run `down -v` for the `gostracker-infratest` project before a rerun: on a "used" stack
the first-run tests fail with the "fresh stack needed" message.

### More

- Data model (R1.0 and MVP) - `docs/data-model.md`.
- API contract - `docs/api/openapi.json` (generated by `scripts/gen-api.sh`).
- Project state - `docs/STATE.md`, rules for agents - `AGENTS.md`.
