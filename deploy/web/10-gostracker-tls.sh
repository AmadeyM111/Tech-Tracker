#!/bin/sh
# Выбор TLS-сертификата для nginx (plan §4.12, D-17, FR-63). Запускается entrypoint'ом образа nginx.
# Порядок: 1) сертификат оператора /etc/gostracker/tls/tls.{crt,key} (не перегенерируется);
#          2) уже сгенерированный самоподписанный в /var/lib/gostracker/tls, если пара цела
#             (ключ подходит к сертификату, срок не истёк);
#          3) генерация нового самоподписанного (EC prime256v1, 825 дней).
# nginx читает сертификат по фиксированным путям /run/gostracker-tls/tls.{crt,key} (символьные ссылки).
#
# Скрипт стартует раньше envsubst-шаблонов образа nginx (префикс 10-), поэтому значения
# переменных проверяются здесь, до подстановки в конфигурацию.
set -eu

OPERATOR_CRT=/etc/gostracker/tls/tls.crt
OPERATOR_KEY=/etc/gostracker/tls/tls.key
GENERATED_DIR=/var/lib/gostracker/tls
ACTIVE_DIR=/run/gostracker-tls
TLS_NAME_MAX=64

log() { echo "gostracker-tls: $*"; }
fail() {
    echo "gostracker-tls: ошибка: $*" >&2
    exit 1
}

# --- проверка HTTPS_PORT: целое 1..65535 без ведущих нулей (значение попадает в Location) ---
HTTPS_PORT="${HTTPS_PORT-}"
case "$HTTPS_PORT" in
    '' | *[!0-9]* | 0*)
        fail "HTTPS_PORT должен быть числом от 1 до 65535 (без ведущих нулей)"
        ;;
esac
if [ "${#HTTPS_PORT}" -gt 5 ] || [ "$HTTPS_PORT" -gt 65535 ]; then
    fail "HTTPS_PORT должен быть числом от 1 до 65535"
fi

# Совпадает ли открытый ключ сертификата с открытым ключом закрытого ключа.
# stderr openssl не глушится: причина (нечитаемый файл и т.п.) видна в логе контейнера.
pair_matches() {
    pub_crt=$(openssl x509 -in "$1" -noout -pubkey) || return 1
    pub_key=$(openssl pkey -in "$2" -pubout) || return 1
    [ -n "$pub_crt" ] && [ "$pub_crt" = "$pub_key" ]
}

link_active() {
    mkdir -p "$ACTIVE_DIR"
    ln -sf "$1" "$ACTIVE_DIR/tls.crt"
    ln -sf "$2" "$ACTIVE_DIR/tls.key"
}

# --- 1. сертификат оператора ---
if [ -s "$OPERATOR_CRT" ] && [ -s "$OPERATOR_KEY" ]; then
    # Файлы оператора не меняются и не подменяются. Просроченный сертификат используется как есть
    # (решает оператор); несовпадающая пара - ошибка конфигурации с понятным сообщением.
    if ! pair_matches "$OPERATOR_CRT" "$OPERATOR_KEY"; then
        fail "ключ $OPERATOR_KEY не соответствует сертификату $OPERATOR_CRT (или файлы нечитаемы)"
    fi
    link_active "$OPERATOR_CRT" "$OPERATOR_KEY"
    log "используется сертификат оператора"
    exit 0
fi

if [ -e "$OPERATOR_CRT" ] || [ -e "$OPERATOR_KEY" ]; then
    if [ -s "$OPERATOR_CRT" ]; then
        missing=tls.key
    else
        missing=tls.crt
    fi
    log "предупреждение: в /etc/gostracker/tls нужны оба файла (tls.crt и tls.key), файл $missing" \
        "отсутствует или пуст; сертификат оператора не используется"
fi

# --- проверка TLS_SERVER_NAME (нужна только для генерации); пустое имя - localhost ---
TLS_SERVER_NAME="${TLS_SERVER_NAME:-localhost}"
validate_server_name() {
    case "$TLS_SERVER_NAME" in
        *[!A-Za-z0-9.-]* | .* | -*)
            fail "TLS_SERVER_NAME должен быть именем хоста (буквы, цифры, '.', '-'; не с '.' или '-')"
            ;;
    esac
    if [ "${#TLS_SERVER_NAME}" -gt "$TLS_NAME_MAX" ]; then
        fail "TLS_SERVER_NAME длиннее $TLS_NAME_MAX символов (предел CN сертификата)"
    fi
}

# --- 2-3. сгенерированная пара: проверка под блокировкой, при необходимости генерация ---
umask 077
mkdir -p "$GENERATED_DIR"

# Два контейнера web на одном томе (PID одинаков в контейнерах): публикация пары (ключ, затем
# сертификат) должна идти по одному. Блокировка - flock на самом каталоге тома, без файлов в нём;
# снимается при завершении скрипта (в том числе аварийном).
exec 9<"$GENERATED_DIR"
flock 9

tmp_key=
tmp_crt=
trap 'rm -f "${tmp_key:-}" "${tmp_crt:-}"' EXIT

gen_crt="$GENERATED_DIR/tls.crt"
gen_key="$GENERATED_DIR/tls.key"
need_generate=1
if [ -s "$gen_crt" ] && [ -s "$gen_key" ]; then
    if ! pair_matches "$gen_crt" "$gen_key"; then
        log "сгенерированный ранее ключ не соответствует сертификату: перегенерация"
    elif ! openssl x509 -in "$gen_crt" -noout -checkend 0 >/dev/null; then
        log "срок действия сгенерированного ранее сертификата истёк: перегенерация"
    else
        need_generate=0
        log "используется ранее сгенерированный самоподписанный сертификат"
    fi
elif [ -e "$gen_crt" ] || [ -e "$gen_key" ]; then
    log "в $GENERATED_DIR неполная пара файлов: перегенерация"
fi

if [ "$need_generate" -eq 1 ]; then
    validate_server_name
    # mktemp: уникальные имена в каталоге тома (в отличие от $$), остатки убирает trap.
    tmp_key=$(mktemp "$GENERATED_DIR/.tls.key.XXXXXX")
    tmp_crt=$(mktemp "$GENERATED_DIR/.tls.crt.XXXXXX")
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 825 \
        -subj "/CN=${TLS_SERVER_NAME}" \
        -addext "subjectAltName=DNS:${TLS_SERVER_NAME},DNS:localhost,IP:127.0.0.1" \
        -keyout "$tmp_key" -out "$tmp_crt"
    chmod 0600 "$tmp_key"
    chmod 0644 "$tmp_crt"
    # Сначала ключ, потом сертификат: пара считается готовой, когда сертификат на месте;
    # оборванная публикация даёт несовпадающую пару, которую следующий запуск перегенерирует.
    mv "$tmp_key" "$gen_key"
    mv "$tmp_crt" "$gen_crt"
    tmp_key=
    tmp_crt=
    log "сгенерирован самоподписанный сертификат для ${TLS_SERVER_NAME} (825 дней)"
fi

link_active "$gen_crt" "$gen_key"
