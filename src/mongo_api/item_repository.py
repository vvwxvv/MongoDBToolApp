"""
Example of reusing the generic library for one specific data model — this
mirrors your original `items` collection demo, but now POST/EDIT/DELETE/GET
are inherited, not hand-rolled per model.

Run directly:  python -m examples.item_repository
(requires MONGO_URI env var set)
"""
from __future__ import annotations

from typing import Optional

from bson import ObjectId
from pymongo import ASCENDING, ReturnDocument

from src.mongo_lib import BaseRepository, MongoBaseModel


class Item(MongoBaseModel):
    name: str
    price: float
    stock: int = 0
    sku: Optional[str] = None


class ItemRepository(BaseRepository[Item]):
    def __init__(self):
        super().__init__(
            collection_name="items",
            model=Item,
            # unique index example: prevents duplicate SKUs at the DB level
            unique_indexes=[("sku", ASCENDING)] if False else None,  # enable once `sku` is always populated
        )

    # Add model-specific query helpers here — generic CRUD stays in the base
    # class, anything specific to "items" (like stock logic) lives here.
    def decrement_stock(self, item_id: str, amount: int) -> Optional[Item]:
        """Atomic decrement — safer than read-modify-write under concurrency."""
        doc = self.collection.find_one_and_update(
            {"_id": ObjectId(item_id)},
            {"$inc": {"stock": -amount}},
            return_document=ReturnDocument.AFTER,
        )
        return self._load(doc)

    def low_stock(self, threshold: int = 5) -> list[Item]:
        return self.find({"stock": {"$lte": threshold}}, sort=[("stock", ASCENDING)])


if __name__ == "__main__":
    repo = ItemRepository()

    # CREATE
    item_id = repo.create(Item(name="Laptop", price=999.99, stock=10))
    print(f"Created: {item_id}")

    # READ
    item = repo.get_by_id(item_id)
    print(f"Fetched: {item}")

    # UPDATE
    updated = repo.update(item_id, {"price": 899.99, "stock": 8})
    print(f"Updated: {updated}")

    # DELETE
    deleted = repo.delete(item_id)
    print(f"Deleted: {deleted}")
