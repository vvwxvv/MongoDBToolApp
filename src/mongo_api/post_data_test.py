"""
test_post_repo.py

Quick smoke test: insert an Item directly via ItemRepository, bypassing
the FastAPI layer entirely. Use this to verify your MongoDB connection,
URI, and the repository's create() logic work in isolation.

Run:  python test_post_repo.py
(requires MONGODB_URL / MONGODB_DB env vars, or .env file, to be set)
"""
from __future__ import annotations

from src.mongo_api.item_repository import Item, ItemRepository


def main() -> None:
    repo = ItemRepository()

    new_item = Item(name="Test Laptop", price=1234.56, stock=5, sku="TEST-001")

    print(f"Posting item to MongoDB: {new_item}")
    item_id = repo.create(new_item)
    print(f"✅ Insert succeeded. New _id = {item_id}")

    fetched = repo.get_by_id(item_id)
    print(f"Fetched back from DB: {fetched}")

    assert fetched is not None, "Item was not found after insert!"
    assert fetched.name == "Test Laptop"
    print("✅ Verification passed: document exists and matches what was sent.")


if __name__ == "__main__":
    main()