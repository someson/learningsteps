from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from repositories.postgres_repository import PostgresDB
from routers.auth_router import router as auth_router
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
    async with PostgresDB() as db:
        app.state.db = db
        logger.info("LearningSteps API started successfully")
        yield


app = FastAPI(
    title="LearningSteps API",
    description="A simple learning journal API for tracking daily work, struggles, and intentions",
    lifespan=lifespan,
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url=None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
)
# JSON API. Everything under /api is data; the web UI and docs live outside it.
app.include_router(auth_router, prefix="/api")
app.include_router(journal_router, prefix="/api")

# Web UI: the Vite build of frontend/ (see app/frontend/vite.config.ts). The
# image builds it in a separate stage; locally run `npm run build` once.
STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"

# Last added runs first: headers wrap everything (including the rejections
# below), then oversized bodies, then cross-site requests are turned away
# before any route or database work.
app.add_middleware(CSRFMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware, index_html=INDEX_HTML)

app.mount(
    "/assets",
    StaticFiles(directory=STATIC_DIR / "assets", check_dir=False),
    name="assets",
)


@app.get("/", include_in_schema=False)
def root():
    if not INDEX_HTML.is_file():
        return JSONResponse(
            status_code=503,
            content={"detail": "Web UI is not built. Run `npm ci && npm run build` in app/frontend."},
        )
    # index.html references hashed asset names, so it must always be revalidated.
    return FileResponse(INDEX_HTML, headers={"Cache-Control": "no-cache"})


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
