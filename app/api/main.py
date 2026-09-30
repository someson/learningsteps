from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from repositories.postgres_repository import PostgresDB
from routers.admin_router import router as admin_router
from routers.auth_router import current_user, require_admin, router as auth_router
import errors
from metrics import MetricsMiddleware, MetricsServer
from routers.journal_router import router as journal_router
from security import (
    DOCS_ENABLED,
    BodySizeLimitMiddleware,
    CSRFMiddleware,
    RequestIdFilter,
    SecurityHeadersMiddleware,
)
import logging

load_dotenv()

# Console logging. Every line carries the request ID that is also returned in
# the X-Request-ID header, so a user's report can be matched to the logs.
# Security-relevant events (logins, changes, deletes) go to the "audit" logger.
_handler = logging.StreamHandler()
_handler.addFilter(RequestIdFilter())
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] %(message)s',
    handlers=[_handler],
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A single connection pool for the life of the process. Previously a new
    # pool was opened and closed on every request.
    # Metrics (HTTP, database probe) on their own port, see metrics.py.
    async with PostgresDB() as db, MetricsServer(db):
        app.state.db = db
        logger.info("LearningSteps API started successfully")
        yield


app = FastAPI(
    title="LearningSteps API",
    description="A simple learning journal API for tracking daily work, struggles, and intentions",
    lifespan=lifespan,
    # Served by the routes below, which check the session first.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
# JSON API. Everything under /api is data; the web UI and docs live outside it.
app.include_router(auth_router, prefix="/api")
app.include_router(journal_router, prefix="/api")
app.include_router(admin_router, prefix="/api")

# JSON errors under /api, web pages everywhere else (errors.py).
errors.install(app)

# Web UI: the Vite build of frontend/ (see app/frontend/vite.config.ts). The
# image builds it in a separate stage; locally run `npm run build` once.
STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"

# Last added runs first: headers wrap everything (including the rejections
# below), then oversized bodies, then cross-site requests are turned away
# before any route or database work.
app.add_middleware(CSRFMiddleware)
app.add_middleware(BodySizeLimitMiddleware)

# Swagger UI from this origin (copied into static/ by the frontend build),
# not a CDN: no third-party script on a page that carries the session.
DOCS_HTML = get_swagger_ui_html(
    openapi_url="/openapi.json",
    title="LearningSteps API",
    swagger_js_url="/assets/swagger/swagger-ui-bundle.js",
    swagger_css_url="/assets/swagger/swagger-ui.css",
    swagger_favicon_url="/assets/swagger/favicon-32x32.png",
).body.decode()

app.add_middleware(SecurityHeadersMiddleware, index_html=INDEX_HTML, docs_html=DOCS_HTML)
# Outermost: measures every response, including the ones rejected above.
app.add_middleware(MetricsMiddleware)


async def require_docs_access(request: Request) -> None:
    """Signed-in users only, unless ENABLE_DOCS=true. Anonymous visitors get
    401: a sign-in page for /docs, JSON for /openapi.json."""
    if DOCS_ENABLED:
        return
    await current_user(request)


@app.get("/openapi.json", include_in_schema=False)
async def openapi_schema(request: Request):
    await require_docs_access(request)
    return JSONResponse(app.openapi())


@app.get("/docs", include_in_schema=False)
async def swagger_ui(request: Request):
    await require_docs_access(request)
    return HTMLResponse(DOCS_HTML)

app.mount(
    "/assets",
    StaticFiles(directory=STATIC_DIR / "assets", check_dir=False),
    name="assets",
)


def serve_index():
    if not INDEX_HTML.is_file():
        return JSONResponse(
            status_code=503,
            content={"detail": "Web UI is not built. Run `npm ci && npm run build` in app/frontend."},
        )
    # index.html references hashed asset names, so it must always be revalidated.
    return FileResponse(INDEX_HTML, headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def root():
    return serve_index()


@app.get("/admin", include_in_schema=False)
async def admin_ui(request: Request):
    """The administration page of the web UI. The role is checked here too,
    so a direct visit gets a 401 or 403 page rather than an empty screen;
    the admin API enforces it independently."""
    await require_admin(request)
    return serve_index()


# Liveness: the process is up and serving. Deliberately does not touch the
# database, so a DB outage does not make Kubernetes restart every pod.
@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


# Readiness: the pod can serve real requests. Failing it takes the pod out of
# the Service's endpoints without restarting it.
@app.get("/readyz", include_in_schema=False)
async def readyz(request: Request):
    try:
        await request.app.state.db.ping()
    except Exception:
        logger.exception("Readiness check failed")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ok"}
