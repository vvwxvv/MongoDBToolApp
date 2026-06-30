"""
Connection management.

This is the ONE place a MongoClient gets constructed. Every repository,
every app module, every script imports get_database()/get_client() from
here instead of instantiating MongoClient itself.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import ConnectionFailure, ConfigurationError
from pymongo.server_api import ServerApi

from .config import MongoSettings, get_settings
from .exceptions import ConnectionNotInitializedError

logger = logging.getLogger("mongo_lib.connection")

_CONNECT_MAX_ATTEMPTS = 3
_CONNECT_RETRY_DELAY_SECONDS = 2


class MongoConnectionManager:
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

        last_error: Exception | None = None
        for attempt in range(1, _CONNECT_MAX_ATTEMPTS + 1):
            try:
                client: MongoClient = MongoClient(settings.uri, **kwargs)
                client.admin.command("ping")
                if attempt > 1:
                    logger.info("MongoDB connection succeeded on attempt %d", attempt)
                return client
            except ConfigurationError as exc:
                last_error = exc
                logger.warning(
                    "MongoDB connection attempt %d/%d failed (configuration/DNS): %s",
                    attempt, _CONNECT_MAX_ATTEMPTS, exc,
                )
            except ConnectionFailure as exc:
                last_error = exc
                logger.warning(
                    "MongoDB connection attempt %d/%d failed (connection): %s",
                    attempt, _CONNECT_MAX_ATTEMPTS, exc,
                )

            if attempt < _CONNECT_MAX_ATTEMPTS:
                time.sleep(_CONNECT_RETRY_DELAY_SECONDS)

        friendly = (
            f"Could not connect to MongoDB after {_CONNECT_MAX_ATTEMPTS} attempts. "
            f"Last error: {last_error}. "
            "Common causes: (1) MONGODB_URL is missing/incorrect, "
            "(2) your network's DNS resolver can't resolve the mongodb+srv:// "
            "SRV record (try again, or switch to a non-SRV mongodb:// URI), "
            "(3) MongoDB Atlas Network Access doesn't allow this IP — add "
            "0.0.0.0/0 if connecting from a dynamic-IP environment like "
            "serverless hosting."
        )
        raise ConnectionNotInitializedError(friendly) from last_error

    @classmethod
    def get_instance(cls, settings: Optional[MongoSettings] = None) -> "MongoConnectionManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(settings)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
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
        try:
            self._client.admin.command("ping")
            return True
        except Exception:
            logger.exception("MongoDB health check failed")
            return False


def get_client() -> MongoClient:
    return MongoConnectionManager.get_instance().client


def get_database(name: Optional[str] = None) -> Database:
    manager = MongoConnectionManager.get_instance()
    return manager.client[name] if name else manager.db


def close_connection() -> None:
    MongoConnectionManager.reset()