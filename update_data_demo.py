from src.mongo_api.data_updater import update_by_id
from src.mongo_lib import MongoBaseModel

class Product(MongoBaseModel):
    name: str
    price: float
    stock: int = 0

# Update a product's price and stock – creates if missing because upsert=True
updated = update_by_id(
    item_id="67a1b2c3d4e5f67890abcd12",
    collection_name="products",
    new_values={"name": "Tablet", "price": 299.99, "stock": 8},
    model=Product,
    db_name="sales",
    upsert=True,  # <-- now supported
)

if updated:
    print(f"Updated/Inserted: {updated.name} now costs ${updated.price} with stock {updated.stock}")
else:
    # This won't happen when upsert=True
    print("Something went wrong")