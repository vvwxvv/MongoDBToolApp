# crud_router_factory.py
"""
FastAPI router factory that generates CRUD endpoints for ANY MongoDB collection.
You can either:
  - pass a custom Pydantic model (for validation), or
  - pass nothing and get a flexible API that accepts arbitrary JSON.

Usage:
    from crud_router_factory import create_crud_router
    from src.mongo_lib import MongoBaseModel

    # Strict model (validates fields)
    class Product(MongoBaseModel):
        name: str
        price: float

    router = create_crud_router(
        collection_name="products",
        model=Product,              # optional – if omitted, dynamic mode
        db_name="sales",            # optional, defaults to MONGODB_DB
        prefix="/products",
        tags=["Products"],
    )

    # Dynamic mode – no model needed
    router = create_crud_router(
        collection_name="logs",
        db_name="analytics",
        prefix="/logs",
        tags=["Logs"],
    )
"""

from __future__ import annotations

from typing import Any, Optional, Sequence, Type

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, create_model

from src.mongo_lib import (
    BaseRepository,
    DocumentNotFoundException,
    DuplicateKeyException,
    InvalidObjectIdError,
    MongoBaseModel,
)


def create_crud_router(
    collection_name: str,
    model: Optional[Type[MongoBaseModel]] = None,  # now optional
    *,
    db_name: Optional[str] = None,
    unique_indexes: Optional[Sequence[tuple[str, int]]] = None,
    extra_indexes: Optional[Sequence[Sequence[tuple[str, int]]]] = None,
    prefix: str = "",
    tags: Optional[list[str]] = None,
    default_limit: int = 50,
    max_limit: int = 500,
) -> APIRouter:
    """
    Generate a FastAPI router with CRUD endpoints for a MongoDB collection.

    Args:
        collection_name: Name of the Mongo collection.
        model: Optional Pydantic model class (must inherit from MongoBaseModel).
               If not provided, a dynamic model that accepts any fields is used.
        db_name: Optional database name. If not given, uses the default from settings.
        unique_indexes: List of (field, direction) tuples for unique indexes.
        extra_indexes: List of compound index specs.
        prefix: URL prefix for all routes (e.g., "/items").
        tags: OpenAPI tags for the endpoints.
        default_limit: Default `limit` for GET /.
        max_limit: Maximum allowed `limit`.

    Returns:
        FastAPI APIRouter with CRUD endpoints.
    """

    # ------------------------------------------------------------------
    # 1. Determine the actual model to use
    # ------------------------------------------------------------------
    if model is None:
        # Dynamic model: accepts any fields, adds id/created_at/updated_at
        class DynamicDocument(MongoBaseModel):
            model_config = {"extra": "allow"}

        actual_model = DynamicDocument
    else:
        actual_model = model

    # ------------------------------------------------------------------
    # 2. Build dynamic Pydantic schemas for create / update
    # ------------------------------------------------------------------
    excluded_fields = {"id", "_id", "created_at", "updated_at"}

    # For dynamic mode, we want a schema that accepts any fields,
    # so we create a BaseModel with extra='allow' and no defined fields.
    if model is None:
        # CreateSchema: accepts any JSON body
        CreateSchema = type(
            f"{actual_model.__name__}Create",
            (BaseModel,),
            {"model_config": {"extra": "allow"}},
        )
        # UpdateSchema: same, accepts any fields (all optional)
        UpdateSchema = type(
            f"{actual_model.__name__}Update",
            (BaseModel,),
            {"model_config": {"extra": "allow"}},
        )
    else:
        # Explicit model: generate strict schemas as before
        create_fields = {}
        for field_name, field_info in actual_model.model_fields.items():
            if field_name in excluded_fields:
                continue
            create_fields[field_name] = (field_info.annotation, field_info.default)

        CreateSchema = create_model(
            f"{actual_model.__name__}Create",
            __base__=BaseModel,
            **create_fields,
        )

        update_fields = {}
        for field_name, field_info in actual_model.model_fields.items():
            if field_name in excluded_fields:
                continue
            annotation = Optional[field_info.annotation] if field_info.annotation else Optional[Any]
            update_fields[field_name] = (annotation, None)

        UpdateSchema = create_model(
            f"{actual_model.__name__}Update",
            __base__=BaseModel,
            **update_fields,
        )

    # ------------------------------------------------------------------
    # 3. Repository factory (instantiated per request)
    # ------------------------------------------------------------------
    def get_repo() -> BaseRepository[actual_model]:  # type: ignore
        return BaseRepository[actual_model](  # type: ignore
            collection_name=collection_name,
            model=actual_model,
            db_name=db_name,
            unique_indexes=unique_indexes,
            extra_indexes=extra_indexes,
        )

    # ------------------------------------------------------------------
    # 4. Router and endpoints
    # ------------------------------------------------------------------
    router = APIRouter(prefix=prefix, tags=tags or [collection_name])

    @router.get("/", response_model=list[actual_model])
    def list_items(
        skip: int = 0,
        limit: int = default_limit,
        repo: BaseRepository[actual_model] = Depends(get_repo),  # type: ignore
    ):
        if limit > max_limit:
            limit = max_limit
        return repo.find(skip=skip, limit=limit)

    @router.get("/{item_id}", response_model=actual_model)
    def get_item(
        item_id: str,
        repo: BaseRepository[actual_model] = Depends(get_repo),  # type: ignore
    ):
        try:
            return repo.require_by_id(item_id)
        except InvalidObjectIdError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DocumentNotFoundException as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/", response_model=dict, status_code=status.HTTP_201_CREATED)
    def create_item(
        payload: CreateSchema,
        repo: BaseRepository[actual_model] = Depends(get_repo),  # type: ignore
    ):
        try:
            item = actual_model(**payload.model_dump())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid data: {exc}") from exc

        try:
            item_id = repo.create(item)
        except DuplicateKeyException as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"id": item_id}

    @router.patch("/{item_id}", response_model=actual_model)
    def update_item(
        item_id: str,
        payload: UpdateSchema,
        repo: BaseRepository[actual_model] = Depends(get_repo),  # type: ignore
    ):
        new_values = payload.model_dump(exclude_none=True)
        if not new_values:
            raise HTTPException(status_code=400, detail="No fields to update")

        try:
            updated = repo.update(item_id, new_values)
        except InvalidObjectIdError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DuplicateKeyException as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        if updated is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return updated

    @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_item(
        item_id: str,
        repo: BaseRepository[actual_model] = Depends(get_repo),  # type: ignore
    ):
        try:
            deleted = repo.delete(item_id)
        except InvalidObjectIdError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Document not found")
        return None

    return router