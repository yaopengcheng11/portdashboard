"""http_probe — Decide whether a port serves actual web content.

Split out of app.py to break up a 59-line function (cognitive 46) into
focused helpers. Pure networking with no side effects — safe to call
in any context.

Public surface:
    check_http_port(port, timeout=1.5) -> bool
"""

from __future__ import annotations

import socket
from typing import Tuple

# HTTP request sent to each port to elicit a real response.
_HTTP_REQUEST = (
    b"GET / HTTP/1.1\r\n"
    b"Host: localhost\r\n"
    b"Accept: text/html,application/json,*/*\r\n"
    b"Connection: close\r\n"
    b"\r\n"
)

# Cap response size so a runaway server can't pin us.
_MAX_RESPONSE_BYTES = 65536
_RECV_CHUNK = 8192
_BODY_PREVIEW_BYTES = 2048

# Content-Types we treat as "real web content".
_WEB_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "application/json",
    "application/xml",
    "application/javascript",
)


def check_http_port(port: int, timeout: float = 1.5) -> bool:
    """Return True iff ``port`` serves actual web content (not just a raw TCP listener).

    Sends a minimal HTTP/1.1 GET, parses the response, and accepts the
    port only when the status code is <400 AND the body is recognizably
    web (text/html, text/plain, JSON/XML/JS, or a "<html" / "<!doctype"
    marker in the body).
    """
    sock = None
    try:
        sock = _open_connection(port, timeout)
        response = _send_request_and_read(sock, timeout)
        return _response_is_web_content(response)
    except Exception:
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def _open_connection(port: int, timeout: float) -> socket.socket:
    """Open a TCP socket to 127.0.0.1:port and arm the read timeout."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(("127.0.0.1", port))
    return sock


def _send_request_and_read(sock: socket.socket, timeout: float) -> bytes:
    """Send the GET request and read the response up to a hard byte cap."""
    sock.sendall(_HTTP_REQUEST)
    response = b""
    while True:
        try:
            chunk = sock.recv(_RECV_CHUNK)
        except socket.timeout:
            break
        if not chunk:
            break
        response += chunk
        if len(response) > _MAX_RESPONSE_BYTES:
            break
    return response


def _response_is_web_content(response: bytes) -> bool:
    """Decide whether a raw HTTP response represents real web content."""
    if not response.startswith(b"HTTP/"):
        return False
    header_end = response.find(b"\r\n\r\n")
    if header_end == -1:
        return False

    headers_raw = response[:header_end].decode("utf-8", errors="ignore").lower()
    body = response[header_end + 4:]

    if not _status_ok(headers_raw):
        return False
    if _has_web_content_type(headers_raw):
        return True
    return _body_looks_like_html(body)


def _status_ok(headers_raw: str) -> bool:
    """Parse the HTTP status line; reject 4xx/5xx responses."""
    status_line = headers_raw.split("\r\n")[0]
    try:
        status_code = int(status_line.split(" ")[1])
    except (IndexError, ValueError):
        return False
    return status_code < 400


def _has_web_content_type(headers_raw: str) -> bool:
    """True if headers declare any of our recognized web content types."""
    return any(ct in headers_raw for ct in _WEB_CONTENT_TYPES)


def _body_looks_like_html(body: bytes) -> bool:
    """Last-resort check: look for HTML markers in the first 2KB of body."""
    if not body:
        return False
    preview = body[:_BODY_PREVIEW_BYTES].decode("utf-8", errors="ignore").lower()
    return "<html" in preview or "<!doctype" in preview