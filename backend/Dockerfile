# Образ API GOSTracker (plan §4.12, D-19, D-21): без секретов, непривилегированный пользователь.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ALEMBIC_CONFIG=/app/alembic.ini

WORKDIR /app

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
    && groupadd --gid 10001 gostracker \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin gostracker \
    && install -d -o 10001 -g 10001 -m 0750 /data

USER 10001

# Каталог данных (секреты и т.п.) создан и принадлежит 10001 до объявления тома.
VOLUME /data
EXPOSE 8000

# bootstrap ждёт БД до 60 с, поэтому --start-period покрывает это окно.
HEALTHCHECK --interval=10s --timeout=5s --start-period=75s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
