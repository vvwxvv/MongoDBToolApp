"""
Generic repository layer.

This is the reusable "POST/GET/EDIT/DELETE for any data model" piece you
asked about. Any app defines a Pydantic model + picks a collection name,
then gets full CRUD, pagination, bulk ops, and upserts for free by
subclassing BaseRepository[YourModel].

Example (see examples/item_repository.py for a complete one):

    class Item(MongoBaseModel):
        name: str
        price: float
        stock: int = 0

    class ItemRepository(BaseRepository[Item]):
        def __init__(self):
            super().__init__(collection_name="items", model=Item)

    repo = ItemRepository()
    item_id = repo.create(Item(name="Laptop", price=999.99, stock=10))
    item = repo.get_by_id(item_id)
    repo.update(item_id, {"price": 899.99})
    repo.delete(item_id)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Generic, Iterable, Optional, Sequence, Type, TypeVar

from bson import ObjectId
from bson.errors import InvalidId
from pydantic import BaseModel, Field, GetCoreSchemaHandler
from pydantic_core import core_schema
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError, PyMongoError

from .connection import get_database
from .exceptions import DocumentNotFoundException, DuplicateKeyException, InvalidObjectIdError

logger = logging.getLogger("mongo_lib.repository")

ModelT = TypeVar("ModelT", bound=BaseModel)


# ---------------------------------------------------------------------------
# Shared ObjectId + base model so every app's schema speaks the same
# "Mongo doc <-> Pydantic model" dialect.
# ---------------------------------------------------------------------------

class PyObjectId(ObjectId):
    """Allows Pydantic v2 models to use Mongo's ObjectId as a field type,
    validating from both ObjectId and str, and serializing to str for JSON."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        return core_schema.json_or_python_schema(
            json_schema=core_schema.str_schema(),
            python_schema=core_schema.union_schema(
                [
                    core_schema.is_instance_schema(ObjectId),
                    core_schema.chain_schema(
                        [core_schema.str_schema(), core_schema.no_info_plain_validator_function(cls.validate)]
                    ),
                ]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )

    @classmethod
    def validate(cls, value: Any) -> ObjectId:
        if isinstance(value, ObjectId):
            return value
        if not ObjectId.is_valid(value):
            raise InvalidObjectIdError(f"Invalid ObjectId: {value!r}")
        return ObjectId(value)


class MongoBaseModel(BaseModel):
    """
    Base class every app's data model can extend. Provides the common
    `id`, `created_at`, `updated_at` fields so repositories can rely on
    them existing without each app reimplementing audit fields.
    """

    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {ObjectId: str},
    }


# ---------------------------------------------------------------------------
# Generic repository
# ---------------------------------------------------------------------------

def _to_object_id(value: str | ObjectId) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(value)
    except (InvalidId, TypeError) as exc:
        raise InvalidObjectIdError(f"Invalid ObjectId: {value!r}") from exc


class BaseRepository(Generic[ModelT]):
    """
    Generic, reusable CRUD repository over a single Mongo collection.

    Subclass it per data model/app:

        class UserRepository(BaseRepository[User]):
            def __init__(self):
                super().__init__("users", User, unique_indexes=[("email", ASCENDING)])

    Every method returns plain dicts or validated Pydantic model instances,
    never raw pymongo result objects, so callers don't need driver knowledge.
    """

    def __init__(
        self,
        collection_name: str,
        model: Type[ModelT],
        db_name: Optional[str] = None,
        unique_indexes: Optional[Sequence[tuple[str, int]]] = None,
        extra_indexes: Optional[Iterable[Sequence[tuple[str, int]]]] = None,
    ):
        """
        :param collection_name: Mongo collection this repo manages.
        :param model: Pydantic model class used to validate/serialize documents.
        :param db_name: Optional override; defaults to the configured database.
        :param unique_indexes: list of (field_name, ASCENDING|DESCENDING) tuples,
               each created as its own unique index. e.g. [("email", ASCENDING)]
        :param extra_indexes: iterable of compound index specs, each a list of
               (field, direction) tuples, e.g. [[("status", ASCENDING), ("created_at", DESCENDING)]]
        """
        self.collection_name = collection_name
        self.model = model
        self._collection: Collection = get_database(db_name)[collection_name]
        self._ensure_indexes(unique_indexes, extra_indexes)

    # -- setup -----------------------------------------------------------

    def _ensure_indexes(
        self,
        unique_indexes: Optional[Sequence[tuple[str, int]]],
        extra_indexes: Optional[Iterable[Sequence[tuple[str, int]]]],
    ) -> None:
        try:
            if unique_indexes:
                for field, direction in unique_indexes:
                    self._collection.create_index([(field, direction)], unique=True, background=True)
            if extra_indexes:
                for spec in extra_indexes:
                    self._collection.create_index(list(spec), background=True)
        except PyMongoError:
            logger.exception("Failed to ensure indexes on %s", self.collection_name)
            raise

    @property
    def collection(self) -> Collection:
        """Escape hatch for advanced/aggregation queries not covered below."""
        return self._collection

    # -- serialization helpers -------------------------------------------

    def _dump(self, model_instance: ModelT, *, is_create: bool) -> dict:
        data = model_instance.model_dump(by_alias=True, exclude_none=True)
        data.pop("_id", None)  # let Mongo assign on insert; never overwrite on update
        now = datetime.now(timezone.utc)
        if is_create:
            data["created_at"] = data.get("created_at") or now
        data["updated_at"] = now
        return data

    def _load(self, doc: Optional[dict]) -> Optional[ModelT]:
        return self.model.model_validate(doc) if doc is not None else None

    # -- CREATE ------------------------------------------------------------

    def create(self, item: ModelT) -> str:
        """Insert one document. Returns the new document's id as a string."""
        payload = self._dump(item, is_create=True)
        try:
            result = self._collection.insert_one(payload)
        except DuplicateKeyError as exc:
            raise DuplicateKeyException(
                f"Duplicate key inserting into {self.collection_name}: {exc.details}"
            ) from exc
        logger.info("Inserted document %s into %s", result.inserted_id, self.collection_name)
        return str(result.inserted_id)

    def create_many(self, items: Sequence[ModelT], ordered: bool = False) -> list[str]:
        """Bulk insert. ordered=False lets independent documents succeed even
        if one fails (typical for production ingestion jobs)."""
        if not items:
            return []
        payloads = [self._dump(item, is_create=True) for item in items]
        try:
            result = self._collection.insert_many(payloads, ordered=ordered)
        except DuplicateKeyError as exc:
            raise DuplicateKeyException(
                f"Duplicate key during bulk insert into {self.collection_name}: {exc.details}"
            ) from exc
        return [str(_id) for _id in result.inserted_ids]

    # -- READ ----------------------------------------------------------------

    def get_by_id(self, item_id: str | ObjectId) -> Optional[ModelT]:
        doc = self._collection.find_one({"_id": _to_object_id(item_id)})
        return self._load(doc)

    def get_one(self, query: dict) -> Optional[ModelT]:
        return self._load(self._collection.find_one(query))

    def exists(self, query: dict) -> bool:
        return self._collection.find_one(query, projection={"_id": 1}) is not None

    def count(self, query: Optional[dict] = None) -> int:
        return self._collection.count_documents(query or {})

    def find(
        self,
        query: Optional[dict] = None,
        *,
        skip: int = 0,
        limit: int = 50,
        sort: Optional[Sequence[tuple[str, int]]] = None,
    ) -> list[ModelT]:
        """Paginated find. Defaults keep limit bounded so a forgotten arg
        can't accidentally pull an entire production collection into memory."""
        cursor = self._collection.find(query or {}).skip(skip).limit(min(limit, 500))
        if sort:
            cursor = cursor.sort(list(sort))
        else:
            cursor = cursor.sort([("_id", DESCENDING)])
        return [self._load(doc) for doc in cursor]

    # -- UPDATE (EDIT) -------------------------------------------------------

    def update(self, item_id: str | ObjectId, new_values: dict) -> Optional[ModelT]:
        """Partial update ($set) of an existing document. Returns the updated
        document, or None if no document matched the id."""
        new_values = dict(new_values)
        new_values.pop("_id", None)
        new_values.pop("id", None)
        new_values["updated_at"] = datetime.now(timezone.utc)
        try:
            doc = self._collection.find_one_and_update(
                {"_id": _to_object_id(item_id)},
                {"$set": new_values},
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError as exc:
            raise DuplicateKeyException(
                f"Duplicate key updating {self.collection_name}/{item_id}: {exc.details}"
            ) from exc
        return self._load(doc)

    def update_many(self, query: dict, new_values: dict) -> int:
        new_values = dict(new_values)
        new_values.pop("_id", None)
        new_values["updated_at"] = datetime.now(timezone.utc)
        result = self._collection.update_many(query, {"$set": new_values})
        return result.modified_count

    def upsert(self, query: dict, new_values: dict) -> ModelT:
        """Update if a document matches `query`, else insert one with the merge
        of query + new_values. Common for idempotent sync/import jobs."""
        new_values = dict(new_values)
        now = datetime.now(timezone.utc)
        new_values["updated_at"] = now
        doc = self._collection.find_one_and_update(
            query,
            {"$set": new_values, "$setOnInsert": {"created_at": now}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return self._load(doc)

    # -- DELETE --------------------------------------------------------------

    def delete(self, item_id: str | ObjectId) -> bool:
        """Hard delete by id. Returns True if a document was actually deleted."""
        result = self._collection.delete_one({"_id": _to_object_id(item_id)})
        return result.deleted_count > 0

    def delete_many(self, query: dict) -> int:
        result = self._collection.delete_many(query)
        return result.deleted_count

    def soft_delete(self, item_id: str | ObjectId) -> Optional[ModelT]:
        """Sets deleted_at instead of removing the doc — recommended default
        for production data you may need to audit or recover."""
        return self.update(item_id, {"deleted_at": datetime.now(timezone.utc)})

    # -- convenience ----------------------------------------------------------

    def require_by_id(self, item_id: str | ObjectId) -> ModelT:
        """Like get_by_id, but raises instead of returning None — useful in
        API handlers that should 404 on missing resources."""
        item = self.get_by_id(item_id)
        if item is None:
            raise DocumentNotFoundException(f"No document with id={item_id} in {self.collection_name}")
        return item
