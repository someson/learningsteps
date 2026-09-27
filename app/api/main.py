from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from dotenv import load_dotenv
from repositories.postgres_repository import PostgresDB
from routers.journal_router import router as journal_router
import logging

load_dotenv()

# Configure basic console logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
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
)
app.include_router(journal_router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


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
