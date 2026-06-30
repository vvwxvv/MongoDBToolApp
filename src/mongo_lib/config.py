# src/mongo_lib/settings.py
"""
Centralized configuration for the Mongo client layer.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ============================================================================
# 🔧 EDIT HERE — MongoDB connection settings
# ============================================================================
MONGODB_URL = os.getenv("MONGODB_URL", "")
MONGODB_DB = os.getenv("MONGODB_DB", "")
# ============================================================================

class MongoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MONGODB_", env_file=".env", extra="ignore")

    uri: str = Field(
        default=MONGODB_URL,
        validation_alias="MONGODB_URL",
        description="Full MongoDB connection string",
    )
    db_name: str = Field(
        default=MONGODB_DB,
        validation_alias="MONGODB_DB",
        description="Default database name",
    )

    max_pool_size: int = Field(default=100, ge=1)
    min_pool_size: int = Field(default=0, ge=0)
    max_idle_time_ms: int = Field(default=60_000)
    connect_timeout_ms: int = Field(default=10_000)
    server_selection_timeout_ms: int = Field(default=10_000)
    socket_timeout_ms: int = Field(default=20_000)

    retry_writes: bool = Field(default=True)
    retry_reads: bool = Field(default=True)
    app_name: str = Field(default="app")

    tls: bool = Field(default=False)
    tls_ca_file: Optional[str] = Field(default=None)
    tls_allow_invalid_certificates: bool = Field(default=False)

    read_preference: str = Field(default="primaryPreferred")
    write_concern_w: str = Field(default="majority")
    write_concern_journal: bool = Field(default=True)

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, v: str) -> str:
        if not v.startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError(
                f"Invalid MongoDB URI: {v}. "
                "Must start with 'mongodb://' or 'mongodb+srv://'."
            )
        return v

@lru_cache(maxsize=1)
def get_settings() -> MongoSettings:
    return MongoSettings()