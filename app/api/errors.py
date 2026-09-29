"""Error responses: JSON for the API, a web page for everything else.

Machine clients (/api/*, /openapi.json) keep FastAPI's JSON bodies. A person
who opens a missing or forbidden URL in the browser gets a page in the app's
look instead of {"detail": "Not Found"}.

The page is self-contained (inline CSS, no scripts) and carries its own
security headers, because the 500 handler runs outside the middleware stack.
"""
import html
import logging

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("errors")

# (title, message, button label, button target)
PAGES = {
    401: ("Sign in required", "You need to sign in to see this page.", "Sign in", "/"),
    403: (
        "Access denied",
        "Your account does not have permission to see this page. "
        "If you think it should, ask an administrator of LearningSteps.",
        "Back to your journal",
        "/",
    ),
    404: ("Page not found", "There is no page at this address.", "Back to your journal", "/"),
    405: ("Not allowed", "This page cannot be opened this way.", "Back to your journal", "/"),
    500: (
        "Something went wrong",
        "An unexpected error occurred on our side. Please try again in a moment.",
        "Try again",
        "",
    ),
}
GENERIC_4XX = ("Request not possible", "The request could not be completed.", "Back to your journal", "/")
GENERIC_5XX = PAGES[500]

# The page has no scripts and loads nothing; only its inline CSS is allowed.
PAGE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{status} · {title} · LearningSteps</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;min-height:100svh;display:flex;align-items:center;justify-content:center;padding:16px;
background:#fafafa;color:#0a0a0a;font:16px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
-webkit-font-smoothing:antialiased}}
main{{width:100%;max-width:420px;text-align:center}}
.brand{{display:flex;align-items:center;justify-content:center;gap:10px;margin-bottom:24px;font-weight:600;letter-spacing:-.01em}}
.logo{{width:36px;height:36px;border-radius:9px;background:#171717;display:grid;place-items:center}}
.card{{background:#fff;border:1px solid #e5e5e5;border-radius:14px;padding:32px 24px;box-shadow:0 1px 2px rgba(0,0,0,.05)}}
.code{{font-size:56px;font-weight:700;letter-spacing:-.04em;line-height:1;margin:0 0 12px;color:#0a0a0a;font-variant-numeric:tabular-nums}}
h1{{font-size:20px;margin:0 0 8px;letter-spacing:-.01em}}
p{{margin:0;color:#737373;font-size:14px}}
.path{{margin-top:12px;font:13px ui-monospace,SFMono-Regular,Menlo,monospace;color:#525252;word-break:break-all}}
.btn{{display:inline-flex;align-items:center;justify-content:center;height:36px;padding:0 16px;margin-top:24px;
border-radius:8px;background:#171717;color:#fafafa;font-size:14px;font-weight:500;text-decoration:none}}
.btn:hover{{background:#262626}}
.rid{{margin-top:16px;font:12px ui-monospace,SFMono-Regular,Menlo,monospace;color:#a3a3a3}}
</style>
</head>
<body>
<main>
<div class="brand"><span class="logo"><svg viewBox="0 0 32 32" width="20" height="20" fill="none" aria-hidden="true">
<path d="M6 24h5v-5h5v-5h5V9h5" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
LearningSteps</div>
<div class="card">
<p class="code">{status}</p>
<h1>{title}</h1>
<p>{message}</p>{path_line}
<a class="btn" href="{href}">{button}</a>
</div>{rid_line}
</main>
</body>
</html>
"""


def wants_json(request: Request) -> bool:
    path = request.url.path
    return path.startswith("/api/") or path == "/api" or path == "/openapi.json"


def error_page(request: Request, status: int, headers: dict | None = None) -> HTMLResponse:
    title, message, button, href = PAGES.get(status) or (GENERIC_5XX if status >= 500 else GENERIC_4XX)
    request_id = getattr(request.state, "request_id", None)
    path_line = ""
    if status == 404:
        # Escaped and shortened: the path is attacker-controlled.
        path_line = f'\n<p class="path">{html.escape(request.url.path[:200])}</p>'
    rid_line = f'\n<p class="rid">Request ID: {html.escape(request_id)}</p>' if request_id and status >= 500 else ""
    body = TEMPLATE.format(
        status=status,
        title=html.escape(title),
        message=html.escape(message),
        button=html.escape(button),
        # "" = reload the same page ("Try again").
        href=html.escape(href or request.url.path, quote=True),
        path_line=path_line,
        rid_line=rid_line,
    )
    all_headers = {**PAGE_HEADERS, **(headers or {})}
    if request_id:
        all_headers["X-Request-ID"] = request_id
    return HTMLResponse(body, status_code=status, headers=all_headers)


def install(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if wants_json(request):
            return await http_exception_handler(request, exc)
        return error_page(request, exc.status_code, exc.headers)

    # Unhandled errors. Runs outside the middleware stack, so the responses
    # carry their own headers. The traceback goes to the logs, never out.
    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception) -> Response:
        # The request ID is logged explicitly: this runs after the middleware
        # that tags log lines has returned. It matches the ID on the page.
        logger.error(
            "Unhandled error request_id=%s on %s %s",
            getattr(request.state, "request_id", "-"), request.method, request.url.path, exc_info=exc,
        )
        if wants_json(request):
            headers = {k: v for k, v in PAGE_HEADERS.items() if k != "Content-Security-Policy"}
            rid = getattr(request.state, "request_id", None)
            if rid:
                headers["X-Request-ID"] = rid
            return JSONResponse({"detail": "Internal Server Error"}, status_code=500, headers=headers)
        return error_page(request, 500)
