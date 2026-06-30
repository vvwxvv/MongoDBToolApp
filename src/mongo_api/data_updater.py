# src/mongo_api/data_updater.py
"""
Generic update/delete helpers for MongoDB.

All functions accept a `model` (optional) for validation, and `db_name` to
target a specific database.

Examples:
    from src.mongo_api.data_updater import update_by_id

    # Update existing, or create if missing (upsert)
    updated = update_by_id(
        "67a1b2c3...",
        "products",
        {"name": "Laptop", "price": 999.99},
        model=Product,
        upsert=True,
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Type, Union

from bson import ObjectId
from pymongo import ReturnDocument

from src.mongo_lib import BaseRepository, MongoBaseModel


def _get_repo(
    collection_name: str,
    model: Optional[Type[MongoBaseModel]],
    db_name: Optional[str],
) -> BaseRepository:
    """Build a repository for the given collection and model."""
    if model is None:
        # Dynamic model – accepts any fields
        class DynamicDocument(MongoBaseModel):
            model_config = {"extra": "allow"}
        actual_model = DynamicDocument
    else:
        actual_model = model

    return BaseRepository[actual_model](  # type: ignore
        collection_name=collection_name,
        model=actual_model,
        db_name=db_name,
    )


def update_by_id(
    item_id: str,
    collection_name: str,
    new_values: Dict[str, Any],
    *,
    model: Optional[Type[MongoBaseModel]] = None,
    db_name: Optional[str] = None,
    upsert: bool = False,  # <-- NEW parameter
) -> Optional[Union[MongoBaseModel, Dict[str, Any]]]:
    """
    Update a document by its ObjectId.

    If `upsert=True`, inserts a new document with the given `_id` if none exists.

    Returns:
        The updated (or inserted) document as a model instance (if `model` provided)
        or as a dict. Returns None only if `upsert=False` and the document wasn't found.
    """
    repo = _get_repo(collection_name, model, db_name)

    if model is not None:
        try:
            model(**new_values)
        except Exception as e:
            raise ValueError(f"Invalid fields for {model.__name__}: {e}") from e

    if upsert:
        # Build a query on _id and use the generic upsert
        query = {"_id": ObjectId(item_id)}
        doc = repo.upsert(query, new_values)
        if model is None:
            return doc.model_dump(by_alias=True)
        return doc
    else:
        updated = repo.update(item_id, new_values)
        if updated is not None and model is None:
            return updated.model_dump(by_alias=True)
        return updated


def update_one(
    query: Dict[str, Any],
    collection_name: str,
    new_values: Dict[str, Any],
    *,
    model: Optional[Type[MongoBaseModel]] = None,
    db_name: Optional[str] = None,
) -> Optional[Union[MongoBaseModel, Dict[str, Any]]]:
    """Update the first document matching the query. Returns updated doc or None."""
    repo = _get_repo(collection_name, model, db_name)

    if model is not None:
        try:
            model(**new_values)
        except Exception as e:
            raise ValueError(f"Invalid fields for {model.__name__}: {e}") from e

    doc = repo.collection.find_one_and_update(
        query,
        {"$set": {**new_values, "updated_at": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        return None
    if model is not None:
        return model.model_validate(doc)
    else:
        doc["_id"] = str(doc["_id"])
        return doc


def update_many(
    query: Dict[str, Any],
    collection_name: str,
    new_values: Dict[str, Any],
    *,
    model: Optional[Type[MongoBaseModel]] = None,
    db_name: Optional[str] = None,
) -> int:
    """Update all matching documents. Returns number modified."""
    repo = _get_repo(collection_name, model, db_name)

    if model is not None:
        try:
            model(**new_values)
        except Exception as e:
            raise ValueError(f"Invalid fields for {model.__name__}: {e}") from e

    return repo.update_many(query, new_values)


def upsert(
    query: Dict[str, Any],
    collection_name: str,
    new_values: Dict[str, Any],
    *,
    model: Optional[Type[MongoBaseModel]] = None,
    db_name: Optional[str] = None,
) -> Union[MongoBaseModel, Dict[str, Any]]:
    """Update if document matches query, else insert. Returns the resulting document."""
    repo = _get_repo(collection_name, model, db_name)

    if model is not None:
        try:
            model(**new_values)
        except Exception as e:
            raise ValueError(f"Invalid fields for {model.__name__}: {e}") from e

    doc = repo.upsert(query, new_values)
    if model is None:
        return doc.model_dump(by_alias=True)
    return doc


def delete_by_id(
    item_id: str,
    collection_name: str,
    *,
    model: Optional[Type[MongoBaseModel]] = None,
    db_name: Optional[str] = None,
) -> bool:
    """Delete a document by its ObjectId. Returns True if deleted."""
    repo = _get_repo(collection_name, model, db_name)
    return repo.delete(item_id)


def delete_many(
    query: Dict[str, Any],
    collection_name: str,
    *,
    model: Optional[Type[MongoBaseModel]] = None,
    db_name: Optional[str] = None,
) -> int:
    """Delete all documents matching the query. Returns the number deleted."""
    repo = _get_repo(collection_name, model, db_name)
    return repo.delete_many(query)