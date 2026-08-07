"""Load products + sample reviews into MongoDB (the API's document read path).
Idempotent: drops and reloads. Vector indexes stay on disk.

    MONGO_URL=mongodb://localhost:27017 python scripts/01_load_mongo.py
"""
import json
import os
import sys
from pathlib import Path

import pandas as pd
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parent.parent


def main():
    url = os.getenv("MONGO_URL", "mongodb://localhost:27017")
    db = MongoClient(url)["routine"]

    prod = pd.read_parquet(ROOT / "data" / "processed" / "products_enriched.parquet")
    docs = []
    for r in prod.itertuples():
        docs.append({"_id": r.product_id, "product_name": r.product_name, "brand_name": r.brand_name,
                     "price_inr": float(r.price_inr) if pd.notna(r.price_inr) else None,
                     "primary_category": r.primary_category, "secondary_category": r.secondary_category,
                     "slot": r.slot if pd.notna(r.slot) else None,
                     "routine_eligible": bool(r.routine_eligible),
                     "function_vector": json.loads(r.function_vector),
                     "highlights": r.highlights if pd.notna(r.highlights) else None})
    db.products.drop()
    db.products.insert_many(docs)
    print(f"products: {db.products.count_documents({})}")

    rev = pd.read_parquet(ROOT / "data" / "sample" / "reviews_sample.parquet")
    db.reviews.drop()
    db.reviews.insert_many(rev.to_dict("records"))
    db.reviews.create_index([("product_id", 1), ("skin_type", 1), ("rating", -1)])
    print(f"reviews: {db.reviews.count_documents({})}")


if __name__ == "__main__":
    sys.exit(main())
