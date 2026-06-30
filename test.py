# test.py
"""
MongoDB Dynamic API – Production Entrypoint

Mounts CRUD routers for multiple collections/databases,
serves static assets (favicon), and provides health checks.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
import logging

from src.mongo_api.crud_router_factory import create_crud_router
from src.mongo_lib import MongoConnectionManager, get_database, close_connection
from src.mongo_lib.config import get_settings


# ----------------------------------------------------------------------------
# Logging setup
# ----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- Startup ----
    logger.info("Application starting up...")
    mgr = MongoConnectionManager.get_instance()
    default_db = get_settings().db_name

    # Default database
    try:
        db = get_database()
        collections = db.list_collection_names()
        logger.info("Connected to default database: %s", default_db)
        logger.info("Collections in '%s': %s", default_db, collections)
    except Exception as e:
        logger.error("Failed to connect to default DB '%s': %s", default_db, str(e))

    # Custom databases used by routers
    custom_dbs = {"WXNoteBookApp": ["Writing"], "TestMy": ["Artwork"]}
    for db_name, collections in custom_dbs.items():
        try:
            db_conn = get_database(db_name)
            available = db_conn.list_collection_names()
            logger.info("Connected to custom database: %s", db_name)
            logger.info("Collections in '%s': %s", db_name, available)
            for coll in collections:
                if coll in available:
                    count = db_conn[coll].count_documents({})
                    logger.info("Collection '%s.%s' has %d documents", db_name, coll, count)
                else:
                    logger.warning("Collection '%s.%s' does not exist yet", db_name, coll)
        except Exception as e:
            logger.error("Failed to connect to custom DB '%s': %s", db_name, str(e))

    yield  # application runs here

    # ---- Shutdown ----
    logger.info("Application shutting down...")
    close_connection()


# ----------------------------------------------------------------------------
# FastAPI app
# ----------------------------------------------------------------------------
app = FastAPI(
    title="MongoDB Dynamic API",
    description="Auto-generated CRUD endpoints for any MongoDB collection.",
    version="1.0.0",
    lifespan=lifespan,
)

# ---- CORS middleware ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to your frontend domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static folder for favicon.ico and other assets
app.mount("/static", StaticFiles(directory="static"), name="static")


# ----------------------------------------------------------------------------
# CRUD Routers
# ----------------------------------------------------------------------------
# Router 1: Writing collection in WXNoteBookApp
app.include_router(
    create_crud_router(
        collection_name="Writing",
        db_name="WXNoteBookApp",
        prefix="/writing",
        tags=["Writing"],
    )
)

# Router 2: Artwork collection in TestMy
app.include_router(
    create_crud_router(
        collection_name="Artwork",
        db_name="TestMy",
        prefix="/artwork",
        tags=["Artwork"],
    )
)


# ----------------------------------------------------------------------------
# Root & health endpoints
# ----------------------------------------------------------------------------
@app.get("/")
def root():
    """Welcome page with greeting and API documentation."""
    return {
        "greeting": "Welcome to the MongoDB Dynamic API",
        "message": "Your data is ready to be explored.",
        "endpoints": {
            "writing": "/writing",
            "artwork": "/artwork",
            "health": "/health"
        },
        "documentation": "/docs"
    }

@app.get("/health")
def health():
    """Returns service health and the default database name."""
    try:
        mgr = MongoConnectionManager.get_instance()
        ok = mgr.health_check()
        if not ok:
            raise HTTPException(status_code=503, detail="Database unavailable")
        return {"status": "ok", "database": get_settings().db_name}
    except Exception as e:
        logger.error("Health check failed: %s", str(e))
        raise HTTPException(status_code=503, detail=f"Database error: {str(e)}")


# ----------------------------------------------------------------------------
# Favicon shortcut – returns 204 to silence browser requests
# ----------------------------------------------------------------------------
@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


# ----------------------------------------------------------------------------
# Development server runner (production uses uvicorn CLI)
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "test:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info",
    )
