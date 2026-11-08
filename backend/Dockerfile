# Образ API GTrack (plan §4.12, D-19, D-21): без секретов, непривилегированный пользователь.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ALEMBIC_CONFIG=/app/alembic.ini

WORKDIR /app

# Клиент PostgreSQL 16 для `gtrack backup`/`gtrack restore` (spec 009, plan PB-1, NFR-4): major-версия
# совпадает с сервером (клиент 15 из bookworm не дампит сервер 16). Репозиторий PGDG — только на этапе
# сборки; в рантайме внешних обращений нет.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && install -d -m 0755 /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

# Слой зависимостей: меняется только вместе с pyproject.toml (правка исходников его не сбрасывает).
COPY pyproject.toml /app/pyproject.toml
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" \
        > /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

# Исходники, alembic.ini и migrations (лишнее отсекает .dockerignore); установка не editable.
# Следы сборки (build/, *.egg-info) удаляются в том же слое.
COPY . /app
RUN pip install --no-cache-dir --no-deps /app \
    && rm -rf /app/build /app/*.egg-info \
    && chmod 0755 /app/docker-entrypoint.sh \
    && groupadd --gid 10001 gtrack \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin gtrack \
    && install -d -o 10001 -g 10001 -m 0750 /data

USER 10001

# Каталог данных (секреты и т.п.) создан и принадлежит 10001 до объявления тома.
VOLUME /data
EXPOSE 8000

# bootstrap ждёт БД до 60 с, поэтому --start-period покрывает это окно.
HEALTHCHECK --interval=10s --timeout=5s --start-period=75s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
