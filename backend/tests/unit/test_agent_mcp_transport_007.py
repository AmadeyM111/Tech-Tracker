"""R7-T17: HTTP-транспорт инструментов MCP (007: NFR-3, NFR-6, FR-37, FR-38; plan §4.9, PD-15).

Локальный ``http.server`` на 127.0.0.1 в потоке; БД не нужна. Ключ собирается из байтов в
рантайме и не печатается (булевы значения вычисляются до ``assert``).
"""

from __future__ import annotations

import base64
import inspect
import json
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from app import agent_mcp
from app.agent_mcp import ApiResponse, TransportError, UrllibTransport

KEY = "gtk_" + base64.urlsafe_b64encode(bytes(range(40, 72))).decode("ascii").rstrip("=")


def _leaks(text: str) -> bool:
    return KEY in text or any(KEY[i : i + 8] in text for i in range(len(KEY) - 7))


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.reply: tuple[int, dict[str, str], bytes] = (200, {}, b"{}")


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "http_proxy",
        "HTTP_PROXY",
        "https_proxy",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


@pytest.fixture
def server() -> Iterator[tuple[str, _Recorder]]:
    rec = _Recorder()

    class Handler(BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            rec.requests.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": raw,
                }
            )
            status, headers, payload = rec.reply
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PATCH = do_DELETE = _handle  # noqa: N815

        def log_message(self, *args: object) -> None:
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", rec
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_get_sends_bearer_and_query(server: tuple[str, _Recorder]) -> None:
    """NFR-6: Authorization: Bearer <ключ>, query в строке запроса, тело не отправляется."""
    url, rec = server
    rec.reply = (200, {"Content-Type": "application/json"}, json.dumps({"items": [1]}).encode())
    resp = UrllibTransport(url, KEY).request(
        "GET", "/api/v1/projects", query={"page": "2", "page_size": "10"}
    )
    assert isinstance(resp, ApiResponse)
    assert resp.status == 200 and resp.body == {"items": [1]} and resp.retry_after is None
    req = rec.requests[0]
    assert req["method"] == "GET"
    path, _, qs = req["path"].partition("?")
    assert path == "/api/v1/projects"
    assert sorted(qs.split("&")) == ["page=2", "page_size=10"]
    assert req["headers"]["authorization"] == "Bearer " + KEY
    assert req["body"] == b""


def test_post_sends_json_body(server: tuple[str, _Recorder]) -> None:
    url, rec = server
    rec.reply = (201, {"Content-Type": "application/json"}, b'{"id": "abc"}')
    resp = UrllibTransport(url, KEY).request(
        "POST", "/api/v1/tasks/x/comments", body={"body": "Привет", "n": 1}
    )
    assert resp.status == 201 and resp.body == {"id": "abc"}
    req = rec.requests[0]
    assert req["method"] == "POST" and req["path"] == "/api/v1/tasks/x/comments"
    assert req["headers"]["content-type"].startswith("application/json")
    assert json.loads(req["body"].decode("utf-8")) == {"body": "Привет", "n": 1}
    assert req["headers"]["authorization"] == "Bearer " + KEY


def test_patch_method_is_used(server: tuple[str, _Recorder]) -> None:
    url, rec = server
    UrllibTransport(url, KEY).request("PATCH", "/api/v1/tasks/x", body={"status": "done"})
    assert rec.requests[0]["method"] == "PATCH"
    assert json.loads(rec.requests[0]["body"]) == {"status": "done"}


def test_4xx_is_returned_with_parsed_body(server: tuple[str, _Recorder]) -> None:
    """FR-37: 4xx не исключение; тело {detail, code} разобрано."""
    url, rec = server
    payload = {
        "detail": [{"loc": ["body", "x"], "msg": "m", "type": "t"}],
        "code": "validation_error",
    }
    rec.reply = (422, {"Content-Type": "application/json"}, json.dumps(payload).encode())
    resp = UrllibTransport(url, KEY).request("POST", "/api/v1/x", body={})
    assert resp.status == 422 and resp.body == payload and resp.retry_after is None


def test_401_and_404_are_returned(server: tuple[str, _Recorder]) -> None:
    url, rec = server
    rec.reply = (401, {}, b'{"detail": "no", "code": "not_authenticated"}')
    assert UrllibTransport(url, KEY).request("GET", "/api/v1/me").status == 401
    rec.reply = (404, {}, b'{"detail": "no", "code": "not_found"}')
    assert UrllibTransport(url, KEY).request("GET", "/api/v1/me").body == {
        "detail": "no",
        "code": "not_found",
    }


@pytest.mark.parametrize("status", [429, 503])
def test_retry_after_header_is_parsed(server: tuple[str, _Recorder], status: int) -> None:
    """FR-37: Retry-After из HTTPError-ответа -> целое число секунд."""
    url, rec = server
    rec.reply = (status, {"Retry-After": "23"}, b'{"detail": "later", "code": "too_many_requests"}')
    resp = UrllibTransport(url, KEY).request("GET", "/api/v1/me")
    assert resp.status == status and resp.retry_after == 23


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirect_is_not_followed(server: tuple[str, _Recorder], status: int) -> None:
    """PD-15: 3xx -> redirect_not_allowed; второй запрос (с ключом) не отправляется."""
    url, rec = server
    rec.reply = (status, {"Location": url + "/elsewhere"}, b"")
    with pytest.raises(TransportError) as info:
        UrllibTransport(url, KEY).request("GET", "/api/v1/me")
    assert info.value.code == "redirect_not_allowed"
    assert len(rec.requests) == 1
    assert not _leaks(str(info.value)), "секрет в тексте ошибки"


def test_connection_refused_is_connection_error() -> None:
    """Закрытый порт -> TransportError(connection_error) без ключа в тексте."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(TransportError) as info:
        UrllibTransport(f"http://127.0.0.1:{port}", KEY, timeout=3.0).request("GET", "/api/v1/me")
    assert info.value.code == "connection_error"
    assert not _leaks(str(info.value) + info.value.detail), "секрет в тексте ошибки"


def test_non_json_success_body_is_invalid_response(server: tuple[str, _Recorder]) -> None:
    url, rec = server
    rec.reply = (200, {"Content-Type": "text/html"}, b"<html>not json</html>")
    with pytest.raises(TransportError) as info:
        UrllibTransport(url, KEY).request("GET", "/api/v1/me")
    assert info.value.code == "invalid_response"


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://example.org",
        "http://example.org:8000",
        "http://192.168.1.5",
        "http://127.0.0.1:8000/api",
        "http://127.0.0.1:8000/",
        "https://example.org/prefix",
        "ftp://127.0.0.1",
        "example.org",
        "",
    ],
)
def test_bad_base_url_raises_value_error_without_key(bad_url: str) -> None:
    """PD-15: http:// только loopback; только origin (без пути); ключа в тексте ошибки нет."""
    with pytest.raises(ValueError) as info:
        UrllibTransport(bad_url, KEY)
    assert not _leaks(str(info.value)), "секрет в тексте ошибки"


@pytest.mark.parametrize(
    "good_url",
    [
        "https://example.org",
        "https://tracker.local:8443",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
    ],
)
def test_good_base_url_is_accepted(good_url: str) -> None:
    UrllibTransport(good_url, KEY)


def test_signature_has_cafile_and_default_timeout() -> None:
    """PD-15: cafile (GOSTRACKER_CA_FILE) и таймаут по умолчанию 30 с."""
    params = inspect.signature(UrllibTransport.__init__).parameters
    assert params["timeout"].default == 30.0
    assert params["cafile"].default is None


def test_transport_repr_does_not_leak_key() -> None:
    t = UrllibTransport("https://example.org", KEY)
    assert not _leaks(repr(t) + str(t)), "секрет в repr"


def test_transport_error_has_code_and_detail() -> None:
    err = TransportError("connection_error", "детали")
    assert err.code == "connection_error" and err.detail == "детали"
    assert isinstance(err, Exception)
    assert agent_mcp.ApiResponse(200, {}, None).retry_after is None
