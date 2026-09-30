"""Prometheus metrics, served on a separate port (METRICS_PORT, default 9000).

A separate port rather than a /metrics route on :8000: Caddy only ever
proxies to :8000, so the metrics cannot reach the internet even if the
Caddyfile changes, and the NetworkPolicy can admit Prometheus to :9000
without admitting it to the application.

  learningsteps_http_requests_total              requests by method, route, status
  learningsteps_http_request_duration_seconds    latency histogram by method, route
  learningsteps_http_requests_in_progress        requests being served right now
  learningsteps_db_up                            1 if the last database ping succeeded
  learningsteps_db_ping_duration_seconds         duration of the last ping
  learningsteps_db_pool_connections              pool connections by state (idle, in_use)
  learningsteps_db_pool_max_connections          pool size limit
  learningsteps_logins_total                     sign-ins by method and result

Plus the prometheus_client defaults: process CPU, memory, open files, GC.
"""
import asyncio
import logging
import os
import time

from prometheus_client import Counter, Gauge, Histogram, start_http_server
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

METRICS_PORT = int(os.getenv("METRICS_PORT", "9000"))
DB_PROBE_INTERVAL_SECONDS = 10

HTTP_REQUESTS = Counter(
    "learningsteps_http_requests_total",
    "HTTP requests handled, by method, route template and status code.",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "learningsteps_http_request_duration_seconds",
    "Time from receiving a request to sending the end of its response.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
HTTP_IN_PROGRESS = Gauge(
    "learningsteps_http_requests_in_progress",
    "HTTP requests currently being served.",
)
DB_UP = Gauge(
    "learningsteps_db_up",
    "1 if the last database ping succeeded, 0 if it failed.",
)
DB_PING_DURATION = Gauge(
    "learningsteps_db_ping_duration_seconds",
    "Duration of the last database ping (SELECT 1 through the pool).",
)
DB_POOL_CONNECTIONS = Gauge(
    "learningsteps_db_pool_connections",
    "Connections in this process's pool, by state.",
    ["state"],
)
DB_POOL_MAX = Gauge(
    "learningsteps_db_pool_max_connections",
    "Upper limit of this process's connection pool (DB_POOL_MAX_SIZE).",
)
LOGINS = Counter(
    "learningsteps_logins_total",
    "Sign-in attempts, by method (password, entra) and result.",
    ["method", "result"],
)
# Pre-create the series so dashboards and rate() see zeros, not gaps,
# before the first sign-in.
for _method, _results in {
    "password": ("ok", "failed", "throttled", "disabled"),
    "entra": ("ok", "failed", "disabled"),
}.items():
    for _result in _results:
        LOGINS.labels(_method, _result)


def _route_label(scope: Scope) -> str:
    """The route template (/api/entries/{entry_id}), never the raw path: raw
    paths would create a series per entry ID and per probe of a scanner."""
    path = scope["path"]
    route = scope.get("route")
    template = getattr(route, "path", None)
    if template:
        # Routes of an included router carry their path relative to the
        # include prefix (/api). The prefix is what precedes the part of the
        # request path that the route's own pattern matches.
        regex = getattr(route, "path_regex", None)
        if regex is not None and not regex.match(path):
            for i in range(1, len(path)):
                if path[i] == "/" and regex.match(path[i:]):
                    return path[:i] + template
        return template
    if path.startswith("/assets/"):
        return "/assets"
    return "unmatched"


class MetricsMiddleware:
    """Pure ASGI, outermost: counts every response, including the ones the
    other middlewares reject (413, 403) and unhandled errors (500)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status = 500
        start = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        HTTP_IN_PROGRESS.inc()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            HTTP_IN_PROGRESS.dec()
            route = _route_label(scope)
            HTTP_DURATION.labels(scope["method"], route).observe(time.perf_counter() - start)
            HTTP_REQUESTS.labels(scope["method"], route, str(status)).inc()


async def _probe_database(db) -> None:
    """Pings the database every few seconds and records the result. Runs in
    the app's event loop, because the pool is asyncio-only; the exporter
    thread just reads the gauges."""
    DB_POOL_MAX.set(db.pool.get_max_size())
    while True:
        start = time.perf_counter()
        try:
            await asyncio.wait_for(db.ping(), timeout=5)
            DB_UP.set(1)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            DB_UP.set(0)
            logger.warning("Database ping failed: %s", e.__class__.__name__)
        DB_PING_DURATION.set(time.perf_counter() - start)
        size, idle = db.pool.get_size(), db.pool.get_idle_size()
        DB_POOL_CONNECTIONS.labels("idle").set(idle)
        DB_POOL_CONNECTIONS.labels("in_use").set(size - idle)
        await asyncio.sleep(DB_PROBE_INTERVAL_SECONDS)


class MetricsServer:
    """Starts the exporter and the database probe for the app's lifetime."""

    def __init__(self, db) -> None:
        self.db = db

    async def __aenter__(self):
        self.server, self.thread = start_http_server(METRICS_PORT)
        self.probe = asyncio.create_task(_probe_database(self.db))
        logger.info("Prometheus metrics on :%d/metrics", METRICS_PORT)
        return self

    async def __aexit__(self, *exc) -> None:
        self.probe.cancel()
        try:
            await self.probe
        except asyncio.CancelledError:
            pass
        self.server.shutdown()
        self.server.server_close()
