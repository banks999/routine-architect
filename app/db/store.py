"""Data read path. Mongo when MONGO_URL is reachable (the docker-compose path);
parquet + committed sample reviews as a local fallback so the app runs from a bare
checkout for screenshots/dev. Vector indexes (FAISS/BM25/embeddings) stay on disk.
"""
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
_ENRICHED = ROOT / "data" / "processed" / "products_enriched.parquet"
_SAMPLE_REVIEWS = ROOT / "data" / "sample" / "reviews_sample.parquet"


class Store:
    def __init__(self):
        self.backend = "uninitialised"
        self._db = None
        self._products = None   # fallback DataFrame indexed by product_id
        self._reviews = None

    async def connect(self):
        url = os.getenv("MONGO_URL")
        if url:
            try:
                from motor.motor_asyncio import AsyncIOMotorClient
                client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=2000)
                await client.admin.command("ping")
                self._db = client["routine"]
                if await self._db.products.estimated_document_count() == 0:
                    raise RuntimeError("products collection empty — run scripts/01_load_mongo.py")
                self.backend = "mongodb"
                return
            except Exception as e:  # fall through to parquet
                print(f"[store] Mongo unavailable ({e}); using parquet fallback")
        self._products = pd.read_parquet(_ENRICHED).set_index("product_id")
        self._reviews = pd.read_parquet(_SAMPLE_REVIEWS) if _SAMPLE_REVIEWS.exists() else pd.DataFrame()
        self.backend = "parquet-fallback"

    async def get_product(self, pid: str) -> dict | None:
        if self._db is not None:
            return await self._db.products.find_one({"_id": pid}, {"function_vector": 0, "ingredient_tokens": 0})
        if pid not in self._products.index:
            return None
        r = self._products.loc[pid]
        return {"_id": pid, "product_name": r["product_name"], "brand_name": r["brand_name"],
                "price_inr": float(r["price_inr"]) if pd.notna(r["price_inr"]) else None,
                "primary_category": r.get("primary_category"), "slot": r.get("slot"),
                "highlights": r.get("highlights")}

    async def review_snippets(self, pid: str, skin: str, k: int = 3) -> tuple[int, list[dict]]:
        """(# of 4★+ matched-skin reviews, up to k skin-tagged snippet dicts) — the RAG
        grounding shown in the UI."""
        if self._db is not None:
            cur = self._db.reviews.find({"product_id": pid, "skin_type": skin, "rating": {"$gte": 4}},
                                        {"review_text": 1, "skin_type": 1}).limit(50)
            rows = [d async for d in cur]
            texts = [(d.get("review_text", ""), d.get("skin_type", skin)) for d in rows]
        else:
            if self._reviews is None or self._reviews.empty:  # store not connected / no reviews
                return 0, []
            m = self._reviews[(self._reviews["product_id"] == pid)
                              & (self._reviews["skin_type"] == skin)]
            texts = [(t, skin) for t in m["review_text"].dropna().astype(str).tolist()]
        _spam = ("complimentary", "received this", "in exchange", "voxbox", "influenster",
                 "pinchme", "for testing", "was sent", "gifted", "for free in")
        clean = [(t, s) for t, s in texts if not any(w in str(t).lower() for w in _spam)]
        pick = (clean or texts)  # prefer non-sponsored snippets; fall back if none
        snippets = [{"text": t.strip(), "skin": s} for t, s in pick if 40 < len(str(t)) < 300][:k]
        return len(texts), snippets


store = Store()
