# Образ web GOSTracker (plan §4.12, D-17, D-20): статика SPA и TLS-прокси nginx.
# Контекст сборки - корень репозитория; в него попадает только то, что разрешает
# корневой .dockerignore (frontend/ и deploy/web/). Ключей и сертификатов в образе нет.

# --- этап 1: сборка фронтенда ------------------------------------------------------------
FROM node:22-alpine AS frontend-build
WORKDIR /src/frontend

# Слой зависимостей: сбрасывается только правкой package.json, package-lock.json или .npmrc
# (.npmrc: ignore-scripts, engine-strict).
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# --- этап 2: nginx ---------------------------------------------------------------------
FROM nginx:stable-alpine

# Каталоги /etc/gostracker/tls и /var/lib/gostracker/tls создаются при монтировании томов
# и скриптом выбора сертификата; в образе их нет.
RUN apk add --no-cache openssl

# HTTPS_PORT нужен шаблону (Location редиректа 80 -> 443); значение по умолчанию - стандартный порт.
# envsubst подставляет только эту переменную: переменные nginx ($host, $uri, ...) не затрагиваются.
ENV HTTPS_PORT=443 \
    NGINX_ENVSUBST_FILTER='^HTTPS_PORT$'

COPY --from=frontend-build /src/frontend/dist /usr/share/nginx/html
COPY deploy/web/default.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=0755 deploy/web/10-gostracker-tls.sh /docker-entrypoint.d/10-gostracker-tls.sh

EXPOSE 80 443
