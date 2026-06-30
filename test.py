"""
MongoDB Dynamic API – Vercel Entrypoint

Mounts CRUD routers for multiple collections/databases,
serves static assets (favicon), and provides health checks.
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import logging

from src.mongo_api.crud_router_factory import create_crud_router
from src.mongo_lib import MongoConnectionManager, get_database, close_connection
from src.mongo_lib.config import get_settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- Startup ----
    # A Mongo connection failure here must NOT crash the whole app — log it
    # and let /health honestly report status, so a DNS/network blip degrades
    # gracefully instead of taking down every route.
    logger.info("Application starting up...")
    default_db = get_settings().db_name

    try:
        db = get_database()
        collections = db.list_collection_names()
        logger.info("Connected to default database: %s", default_db)
        logger.info("Collections in '%s': %s", default_db, collections)
    except Exception as e:
        logger.error(
            "Could not connect to default DB '%s' at startup: %s. "
            "App will still start; DB-dependent routes will fail until "
            "this is resolved (check MONGODB_URL, DNS, Atlas Network Access).",
            default_db, str(e),
        )

    custom_dbs = {"WXNoteBookApp": ["Writing"], "TestMy": ["Artwork"]}
    for db_name, coll_names in custom_dbs.items():
        try:
            db_conn = get_database(db_name)
            available = db_conn.list_collection_names()
            logger.info("Connected to custom database: %s", db_name)
            logger.info("Collections in '%s': %s", db_name, available)
            for coll in coll_names:
                if coll in available:
                    count = db_conn[coll].count_documents({})
                    logger.info("Collection '%s.%s' has %d documents", db_name, coll, count)
                else:
                    logger.warning("Collection '%s.%s' does not exist yet", db_name, coll)
        except Exception as e:
            logger.error("Could not connect to custom DB '%s' at startup: %s", db_name, str(e))

    yield  # application runs here

    # ---- Shutdown ----
    logger.info("Application shutting down...")
    close_connection()


app = FastAPI(
    title="MongoDB Dynamic API",
    description="Auto-generated CRUD endpoints for any MongoDB collection.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to your frontend domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static folder ONLY if it exists in the deployed bundle — StaticFiles()
# raises at import time if the directory is missing, which crashes the whole
# serverless function before any route is registered (a common 404 cause).
_static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
else:
    logger.warning("Static directory not found at %s — skipping mount", _static_dir)


app.include_router(
    create_crud_router(
        collection_name="Writing",
        db_name="WXNoteBookApp",
        prefix="/writing",
        tags=["Writing"],
    )
)

app.include_router(
    create_crud_router(
        collection_name="Artwork",
        db_name="TestMy",
        prefix="/artwork",
        tags=["Artwork"],
    )
)


@app.get("/")
def root():
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
    try:
        mgr = MongoConnectionManager.get_instance()
        ok = mgr.health_check()
        if not ok:
            raise HTTPException(status_code=503, detail="Database unavailable")
        return {"status": "ok", "database": get_settings().db_name}
    except Exception as e:
        logger.error("Health check failed: %s", str(e))
        raise HTTPException(status_code=503, detail=f"Database error: {str(e)}")


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


# No `if __name__ == "__main__"` block — Vercel's @vercel/python runtime
# imports `app` directly as an ASGI app and never executes this as a script.
