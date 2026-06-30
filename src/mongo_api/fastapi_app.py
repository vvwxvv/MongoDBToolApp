"""
Example of wiring this library into a production FastAPI service.

Shows:
  - Connection initialized once at startup, closed at shutdown (lifespan)
  - Repository instantiated once, shared across requests via dependency injection
  - POST / GET / PATCH / DELETE endpoints reusing the same generic repository
  - A /health endpoint that checks the real DB connection

Run:  uvicorn examples.fastapi_app:app --reload
(requires MONGO_URI env var; pip install fastapi uvicorn)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel

from src.mongo_lib import (
    DocumentNotFoundException,
    DuplicateKeyException,
    InvalidObjectIdError,
    MongoConnectionManager,
    close_connection,
)
from item_repository import Item, ItemRepository


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Eagerly create the connection pool at startup so the first request
    # isn't the one paying the connection-establishment cost, and so a bad
    # MONGO_URI fails the deploy immediately instead of silently at runtime.
    MongoConnectionManager.get_instance()
    yield
    close_connection()


app = FastAPI(title="Items API", lifespan=lifespan)


def get_item_repo() -> ItemRepository:
    return ItemRepository()


class ItemCreate(BaseModel):
    name: str
    price: float
    stock: int = 0


class ItemUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    stock: Optional[int] = None


@app.get("/health")
def health(repo: ItemRepository = Depends(get_item_repo)):
    ok = MongoConnectionManager.get_instance().health_check()
    if not ok:
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok"}


@app.post("/items", status_code=status.HTTP_201_CREATED)
def create_item(payload: ItemCreate, repo: ItemRepository = Depends(get_item_repo)):
    try:
        item_id = repo.create(Item(**payload.model_dump()))
    except DuplicateKeyException as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": item_id}


@app.get("/items/{item_id}")
def get_item(item_id: str, repo: ItemRepository = Depends(get_item_repo)):
    try:
        return repo.require_by_id(item_id)
    except InvalidObjectIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DocumentNotFoundException as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/items")
def list_items(skip: int = 0, limit: int = 50, repo: ItemRepository = Depends(get_item_repo)):
    return repo.find(skip=skip, limit=limit)


@app.patch("/items/{item_id}")
def update_item(item_id: str, payload: ItemUpdate, repo: ItemRepository = Depends(get_item_repo)):
    new_values = payload.model_dump(exclude_none=True)
    if not new_values:
        raise HTTPException(status_code=400, detail="No fields provided to update")
    try:
        updated = repo.update(item_id, new_values)
    except InvalidObjectIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return updated


@app.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: str, repo: ItemRepository = Depends(get_item_repo)):
    try:
        deleted = repo.delete(item_id)
    except InvalidObjectIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found")
