# Конфигурация nginx образа web

- `default.conf.template` — поставляемый вариант: порт 80 (переадресация) и 443 (TLS, сертификат из
  `deploy/tls` или самоподписанный).
- `behind-proxy.conf.template` — вариант за обратным прокси (прод пилота: Caddy терминирует TLS,
  web публикуется на `127.0.0.1:8083`). Отличия: нет TLS-сервера; `set_real_ip_from 172.20.0.1` и
  `real_ip_header X-Forwarded-For` (реальный IP клиента от Caddy); `X-Forwarded-Proto https`.

Оба файла правятся вместе: новый `location` (например `/mcp`) добавляется в оба. Тест
`backend/tests/infra/test_nginx_variants.py` проверяет общие блоки.

## Прод: перейти с /etc/task-tracker/nginx.conf на файл из репозитория (шаги для оператора)

Сейчас `/etc/task-tracker/compose.override.yml` монтирует `/etc/task-tracker/nginx.conf`. Репозиторий
на сервере — `/opt/task-tracker`, поэтому после `git pull` правки до nginx не доходят. Переход:

1. Убедиться, что серверный файл совпадает с репозиторным: `diff /etc/task-tracker/nginx.conf
   /opt/task-tracker/deploy/web/behind-proxy.conf.template` (расхождение только в комментарии
   первых строк допустимо).
2. Копия override: `cp /etc/task-tracker/compose.override.yml /etc/task-tracker/compose.override.yml.bak-$(date +%Y%m%d)`.
3. В `compose.override.yml` заменить путь тома на
   `/opt/task-tracker/deploy/web/behind-proxy.conf.template:/etc/nginx/templates/default.conf.template:ro`.
4. Применить: `docker compose -p task-tracker -f docker-compose.yml -f /etc/task-tracker/compose.override.yml up -d --no-deps web`
   (перезапускается только web).
5. Проверка: `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8083/healthz` → 200; сайт,
   `/api/v1/health` → 200; `POST /mcp` без токена → 401; `docker exec task-tracker-web-1 nginx -T | grep client_max_body_size` → 12m.
6. Откат: вернуть `.bak` override и повторить шаг 4. Старый `/etc/task-tracker/nginx.conf` не удалять.
