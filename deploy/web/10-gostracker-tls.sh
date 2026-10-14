#!/bin/sh
# Выбор TLS-сертификата для nginx (plan §4.12, D-17, FR-63). Запускается entrypoint'ом образа nginx.
# Порядок: 1) сертификат оператора /etc/gostracker/tls/tls.{crt,key};
#          2) уже сгенерированный самоподписанный в /var/lib/gostracker/tls;
#          3) генерация нового самоподписанного (EC prime256v1, 825 дней).
# nginx читает сертификат по фиксированным путям /run/gostracker-tls/tls.{crt,key} (символьные ссылки).
set -eu

OPERATOR_CRT=/etc/gostracker/tls/tls.crt
OPERATOR_KEY=/etc/gostracker/tls/tls.key
GENERATED_DIR=/var/lib/gostracker/tls
ACTIVE_DIR=/run/gostracker-tls

log() { echo "gostracker-tls: $*"; }

if [ -s "$OPERATOR_CRT" ] && [ -s "$OPERATOR_KEY" ]; then
    crt="$OPERATOR_CRT"
    key="$OPERATOR_KEY"
    log "используется сертификат оператора"
elif [ -s "$GENERATED_DIR/tls.crt" ] && [ -s "$GENERATED_DIR/tls.key" ]; then
    crt="$GENERATED_DIR/tls.crt"
    key="$GENERATED_DIR/tls.key"
    log "используется ранее сгенерированный самоподписанный сертификат"
else
    # Пустое имя - не ошибка: сертификат выдаётся на localhost.
    TLS_SERVER_NAME="${TLS_SERVER_NAME:-localhost}"
    case "$TLS_SERVER_NAME" in
        *[!A-Za-z0-9.-]* | .* | -*)
            log "ошибка: TLS_SERVER_NAME должен быть именем хоста (буквы, цифры, '.', '-')" >&2
            exit 1
            ;;
    esac
    umask 077
    mkdir -p "$GENERATED_DIR"
    tmp_key="$GENERATED_DIR/.tls.key.$$"
    tmp_crt="$GENERATED_DIR/.tls.crt.$$"
    trap 'rm -f "$tmp_key" "$tmp_crt"' EXIT
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 825 \
        -subj "/CN=${TLS_SERVER_NAME}" \
        -addext "subjectAltName=DNS:${TLS_SERVER_NAME},DNS:localhost,IP:127.0.0.1" \
        -keyout "$tmp_key" -out "$tmp_crt" 2>/dev/null
    chmod 0600 "$tmp_key"
    chmod 0644 "$tmp_crt"
    # Сначала ключ, потом сертификат: пара считается готовой только когда есть оба файла.
    mv "$tmp_key" "$GENERATED_DIR/tls.key"
    mv "$tmp_crt" "$GENERATED_DIR/tls.crt"
    crt="$GENERATED_DIR/tls.crt"
    key="$GENERATED_DIR/tls.key"
    log "сгенерирован самоподписанный сертификат для ${TLS_SERVER_NAME} (825 дней)"
fi

mkdir -p "$ACTIVE_DIR"
ln -sf "$crt" "$ACTIVE_DIR/tls.crt"
ln -sf "$key" "$ACTIVE_DIR/tls.key"
