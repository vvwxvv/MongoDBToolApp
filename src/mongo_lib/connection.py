"""
Connection management.

This is the ONE place a MongoClient gets constructed. Every repository,
every app module, every script imports get_database()/get_client() from
here instead of instantiating MongoClient itself. That gives you:

  - A single shared connection pool per process (cheap, fast, the way the
    driver is designed to be used) instead of a new pool per request.
  - One spot to change TLS/timeouts/pool size for every consumer at once.
  - A clean, mockable seam for unit tests (patch get_database).
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import ConnectionFailure, ConfigurationError
from pymongo.server_api import ServerApi

from .config import MongoSettings, get_settings
from .exceptions import ConnectionNotInitializedError

logger = logging.getLogger("mongo_lib.connection")


class MongoConnectionManager:
    """
    Thread-safe singleton wrapping a single pooled MongoClient.

    Usage:
        client = MongoConnectionManager.get_instance().client
        db = MongoConnectionManager.get_instance().db

    Or, more commonly, via the module-level helpers get_client()/get_database()
    below, which is what repositories use.
    """

    _instance: Optional["MongoConnectionManager"] = None
    _lock = threading.Lock()

    def __init__(self, settings: Optional[MongoSettings] = None):
        self._settings = settings or get_settings()
        self._client: MongoClient = self._build_client(self._settings)
        self._db: Database = self._client[self._settings.db_name]
        logger.info(
            "MongoDB connection pool initialized (db=%s, max_pool_size=%s)",
            self._settings.db_name,
            self._settings.max_pool_size,
        )

    @staticmethod
    def _build_client(settings: MongoSettings) -> MongoClient:
        kwargs = dict(
            maxPoolSize=settings.max_pool_size,
            minPoolSize=settings.min_pool_size,
            maxIdleTimeMS=settings.max_idle_time_ms,
            connectTimeoutMS=settings.connect_timeout_ms,
            serverSelectionTimeoutMS=settings.server_selection_timeout_ms,
            socketTimeoutMS=settings.socket_timeout_ms,
            retryWrites=settings.retry_writes,
            retryReads=settings.retry_reads,
            appname=settings.app_name,
            readPreference=settings.read_preference,
            w=settings.write_concern_w,
            journal=settings.write_concern_journal,
            server_api=ServerApi("1"),
            uuidRepresentation="standard",
        )
        if settings.tls:
            kwargs["tls"] = True
            if settings.tls_ca_file:
                kwargs["tlsCAFile"] = settings.tls_ca_file
            if settings.tls_allow_invalid_certificates:
                kwargs["tlsAllowInvalidCertificates"] = True

        try:
            client: MongoClient = MongoClient(settings.uri, **kwargs)
            # Fail fast on bad URI / unreachable cluster at startup rather than
            # on the first request.
            client.admin.command("ping")
            return client
        except ConfigurationError as exc:
            raise ConnectionNotInitializedError(f"Invalid MongoDB configuration: {exc}") from exc
        except ConnectionFailure as exc:
            raise ConnectionNotInitializedError(f"Could not connect to MongoDB: {exc}") from exc

    @classmethod
    def get_instance(cls, settings: Optional[MongoSettings] = None) -> "MongoConnectionManager":
        """Double-checked locking so concurrent first-callers don't race to create two clients."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(settings)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Close and drop the singleton. Used in tests and graceful shutdown."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance._client.close()
                cls._instance = None
                logger.info("MongoDB connection pool closed")

    @property
    def client(self) -> MongoClient:
        return self._client

    @property
    def db(self) -> Database:
        return self._db

    def health_check(self) -> bool:
        """Lightweight liveness check, e.g. for a /health endpoint."""
        try:
            self._client.admin.command("ping")
            return True
        except Exception:  # noqa: BLE001 - health checks should never raise
            logger.exception("MongoDB health check failed")
            return False


# ---------------------------------------------------------------------------
# Module-level convenience functions — this is what application code and
# repositories actually import day-to-day.
# ---------------------------------------------------------------------------

def get_client() -> MongoClient:
    return MongoConnectionManager.get_instance().client


def get_database(name: Optional[str] = None) -> Database:
    """Get the default configured database, or another database on the same
    cluster/connection by passing `name` (still reuses the same pool)."""
    manager = MongoConnectionManager.get_instance()
    return manager.client[name] if name else manager.db


def close_connection() -> None:
    """Call once at application shutdown (e.g. FastAPI lifespan/shutdown event)."""
    MongoConnectionManager.reset()
