"""Request hardening for the VoiceStack HTTP server (one pure-ASGI middleware, no extra dependencies).

What it does, in order, for every HTTP request:
  1. Assigns a request id (X-Request-ID) and writes ONE JSON log line per request (never bodies or keys).
  2. Checks the Host and Origin headers against an allow-list (DNS-rebinding and cross-site protection).
  3. Applies a per-client rolling rate limit (429 + Retry-After).
  4. Caps the request body size (413).
  5. Adds security headers to the response.

There is NO authentication: every route and tool is public. Real use would need OAuth (see docs).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone

from starlette.responses import JSONResponse

MAX_BODY_BYTES = 1_048_576
WINDOW_SECONDS = 60.0

DEFAULT_HOSTS = ("127.0.0.1:*", "localhost:*", "[::1]:*")
DEFAULT_ORIGINS = ("http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*")

log = logging.getLogger("voicestack.access")

CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
       "frame-ancestors 'none'; form-action 'self'")
SECURITY_HEADERS = {
    "content-security-policy": CSP,
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "microphone=(self), camera=(), geolocation=(), payment=()",
}


def _csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        return default
    return tuple(x.strip() for x in value.split(",") if x.strip())


@dataclass(frozen=True)
class Settings:
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    rate_per_min: int          # 0 disables the limiter
    trust_proxy: bool          # read the client address from X-Forwarded-For (only behind your own proxy)
    enable_seed: bool

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        env = os.environ if env is None else env
        return cls(
            allowed_hosts=_csv(env.get("VOICESTACK_ALLOWED_HOSTS"), DEFAULT_HOSTS),
            allowed_origins=_csv(env.get("VOICESTACK_ALLOWED_ORIGINS"), DEFAULT_ORIGINS),
            rate_per_min=int(env.get("VOICESTACK_RATE_PER_MIN", "600")),
            trust_proxy=env.get("VOICESTACK_TRUST_PROXY", "0") == "1",
            enable_seed=env.get("VOICESTACK_ENABLE_SEED", "1") != "0",
        )


def _match(patterns: tuple[str, ...], value: str) -> bool:
    """Exact match, or 'host:*' / 'scheme://host:*' meaning any port."""
    for p in patterns:
        if p == value:
            return True
        if p.endswith(":*") and value.startswith(p[:-1]) and value[len(p) - 1:].isdigit():
            return True
    return False


class _Window:
    """Rolling-window counter per key (in memory, single process)."""

    def __init__(self, limit: int):
        self.limit = limit
        self.hits: dict[str, deque] = defaultdict(deque)

    def _trim(self, key: str, now: float) -> deque:
        q = self.hits[key]
        while q and now - q[0] > WINDOW_SECONDS:
            q.popleft()
        if len(self.hits) > 10_000:                      # keep memory bounded
            for k in [k for k, v in self.hits.items() if not v]:
                del self.hits[k]
        return q

    def allow(self, key: str) -> float:
        """Record a hit. Returns 0 if allowed, else seconds to wait."""
        now = time.monotonic()
        q = self._trim(key, now)
        if len(q) >= self.limit:
            return max(1.0, WINDOW_SECONDS - (now - q[0]))
        q.append(now)
        return 0.0

    def blocked(self, key: str) -> float:
        now = time.monotonic()
        q = self._trim(key, now)
        return max(1.0, WINDOW_SECONDS - (now - q[0])) if len(q) >= self.limit else 0.0

    def add(self, key: str) -> None:
        now = time.monotonic()
        self._trim(key, now).append(now)


_RID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class Hardening:
    def __init__(self, app, settings: Settings):
        self.app = app
        self.s = settings
        self.rate = _Window(settings.rate_per_min) if settings.rate_per_min > 0 else None

    # ---- helpers ----
    def _client(self, headers: dict[str, str], scope) -> str:
        if self.s.trust_proxy and headers.get("x-forwarded-for"):
            return headers["x-forwarded-for"].split(",")[0].strip()[:64]
        c = scope.get("client")
        return c[0] if c else "unknown"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        t0 = time.perf_counter()
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        rid = headers.get("x-request-id", "")
        rid = rid if _RID.match(rid) else uuid.uuid4().hex[:16]
        path, method = scope["path"], scope["method"]
        ip = self._client(headers, scope)
        info = {"status": 0, "tools": []}

        async def send_wrapped(message):
            if message["type"] == "http.response.start":
                info["status"] = message["status"]
                hdrs = [(k, v) for k, v in message.get("headers", [])]
                have = {k.lower() for k, _ in hdrs}
                extra = dict(SECURITY_HEADERS)
                extra["x-request-id"] = rid
                if path.startswith("/api/") or path.startswith("/mcp"):
                    extra["cache-control"] = "no-store"
                for k, v in extra.items():
                    if k.encode() not in have:
                        hdrs.append((k.encode(), v.encode()))
                message = {**message, "headers": hdrs}
            await send(message)

        async def reply(status: int, body: dict, extra: dict | None = None):
            await JSONResponse(body, status_code=status, headers=extra)(scope, receive, send_wrapped)

        try:
            # 2. Host / Origin allow-list
            host = headers.get("host", "")
            if not _match(self.s.allowed_hosts, host):
                return await reply(403, {"ok": False, "error": "forbidden_host", "message": "Host header not allowed."})
            origin = headers.get("origin")
            if origin and not _match(self.s.allowed_origins, origin):
                return await reply(403, {"ok": False, "error": "forbidden_origin", "message": "Cross-origin request refused."})

            # 3. rate limit
            if self.rate is not None:
                wait = self.rate.allow(ip)
                if wait:
                    return await reply(429, {"ok": False, "error": "rate_limited", "message": "Too many requests. Slow down."},
                                       {"retry-after": str(int(wait) + 1)})

            # 4. buffer the MCP body to enforce the size cap and name the tools in the log, then replay it
            replay_receive = receive
            if method == "POST" and path.rstrip("/") == "/mcp":
                try:
                    declared = int(headers.get("content-length", "0") or 0)
                except ValueError:
                    declared = 0
                if declared > MAX_BODY_BYTES:
                    return await reply(413, {"ok": False, "error": "too_large", "message": "Request body too large."})
                chunks, size = [], 0
                while True:
                    msg = await receive()
                    if msg["type"] != "http.request":
                        break
                    chunk = msg.get("body", b"")
                    size += len(chunk)
                    if size > MAX_BODY_BYTES:
                        return await reply(413, {"ok": False, "error": "too_large", "message": "Request body too large."})
                    chunks.append(chunk)
                    if not msg.get("more_body"):
                        break
                body = b"".join(chunks)
                try:
                    parsed = json.loads(body or b"null")
                except ValueError:
                    parsed = None
                for item in (parsed if isinstance(parsed, list) else [parsed]):
                    if isinstance(item, dict) and item.get("method") == "tools/call":
                        name = (item.get("params") or {}).get("name")
                        if isinstance(name, str):
                            info["tools"].append(name[:64])
                sent = False

                async def replay():
                    nonlocal sent
                    if not sent:
                        sent = True
                        return {"type": "http.request", "body": body, "more_body": False}
                    return await receive()
                replay_receive = replay

            await self.app(scope, replay_receive, send_wrapped)
        finally:
            line = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "rid": rid, "ip": ip,
                    "method": method, "path": path, "status": info["status"],
                    "ms": round((time.perf_counter() - t0) * 1000, 1)}
            if info["tools"]:
                line["tools"] = info["tools"]
            log.info(json.dumps(line, separators=(",", ":")))
