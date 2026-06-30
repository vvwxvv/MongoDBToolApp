# src/mongo_api/data_inserter.py
"""
Generic data ingestion helper for MongoDB.

Provides a single function `insert_document` that can insert a document
into any collection, using either:
  - a concrete Pydantic model (for validation), or
  - a dynamic dict-like mode (no schema enforcement).

The function returns the inserted ObjectId as a string.

Usage:
    from src.mongo_api.data_inserter import insert_document
    from src.mongo_lib import MongoBaseModel

    class Product(MongoBaseModel):
        name: str
        price: float

    # With a model
    doc_id = insert_document(
        collection_name="products",
        data={"name": "Laptop", "price": 999.99},
        model=Product,
        db_name="sales"  # optional
    )

    # Dynamic mode (no model)
    doc_id = insert_document(
        collection_name="logs",
        data={"event": "startup", "timestamp": "2025-01-01"},
    )
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Type, Union

from src.mongo_lib import BaseRepository, MongoBaseModel, DuplicateKeyException


def insert_document(
    collection_name: str,
    data: Union[Dict[str, Any], MongoBaseModel],
    *,
    model: Optional[Type[MongoBaseModel]] = None,
    db_name: Optional[str] = None,
) -> str:
    """
    Insert a single document into a MongoDB collection.

    Args:
        collection_name: Name of the target collection.
        data: Either a dict of fields or an instance of a MongoBaseModel subclass.
        model: Optional Pydantic model class. If provided, data is validated.
               If omitted, a dynamic model that accepts any fields is used.
        db_name: Optional database name. Defaults to the connection's default.

    Returns:
        The ObjectId of the inserted document as a string.

    Raises:
        DuplicateKeyException: If a unique index is violated.
        ValueError: If data cannot be validated against the model.
    """

    # 1. Determine the actual model to use
    if model is None:
        # Dynamic model – accepts any fields, adds id/created_at/updated_at
        class DynamicDocument(MongoBaseModel):
            model_config = {"extra": "allow"}
        actual_model = DynamicDocument
    else:
        actual_model = model

    # 2. Convert data to a model instance if it's a dict
    if isinstance(data, dict):
        try:
            instance = actual_model(**data)
        except Exception as e:
            raise ValueError(f"Invalid data for model {actual_model.__name__}: {e}") from e
    elif isinstance(data, actual_model):
        instance = data
    else:
        raise TypeError(
            f"data must be dict or {actual_model.__name__}, got {type(data).__name__}"
        )

    # 3. Instantiate the repository and insert
    repo = BaseRepository[actual_model](  # type: ignore
        collection_name=collection_name,
        model=actual_model,
        db_name=db_name,
    )

    try:
        inserted_id = repo.create(instance)
    except DuplicateKeyException as exc:
        # Re-raise with a clearer message
        raise DuplicateKeyException(
            f"Insert failed due to duplicate key in {collection_name}: {exc}"
        ) from exc

    return inserted_id