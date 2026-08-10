"""FastAPI service (async). Mongo read path, Redis cache, FAISS/BM25 on disk.

Endpoints:
  POST /recommend/routine[?constraints=off]  full AM/PM routine + avoided-conflict
       report + score decomposition + per-stage latency (everything the UI renders)
  GET  /product/{id}   GET /health   GET /metrics   GET / (UI)
"""
import hashlib
import json
import os
import time
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.core import solver as sv
from app.core.pipeline import recommend
from app.db.store import store

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
app = FastAPI(title="Skincare Routine Architect")
_state = {"requests": 0, "cache_hits": 0, "started": time.time()}


class RoutineRequest(BaseModel):
    skin_type: str = Field("combination", examples=["oily"])
    concerns: list[str] = Field(..., examples=[["aging", "texture"]])
    budget_inr: float = 12000
    exclusions: list[str] = Field(default=[], description="Hard filters: fragrance / essential oils / pregnancy-safe only / alcohol")
    owned: list[str] = Field(default=[], description="Products the user already uses (§5.5)")
    exclude: list[str] = Field(default=[], description="Product ids rejected via swap (§2d)")


class _Cache:
    def __init__(self):
        self.mem, self.redis = {}, None

    async def connect(self):
        url = os.getenv("REDIS_URL")
        if url:
            try:
                import redis.asyncio as aioredis
                self.redis = aioredis.from_url(url, decode_responses=True)
                await self.redis.ping()
                return "redis"
            except Exception as e:
                print(f"[cache] Redis unavailable ({e}); using in-memory")
                self.redis = None
        return "in-memory"

    async def get(self, k):
        if self.redis:
            v = await self.redis.get(k)
            return json.loads(v) if v else None
        return self.mem.get(k)

    async def set(self, k, v, ttl=3600):
        if self.redis:
            await self.redis.set(k, json.dumps(v), ex=ttl)
        else:
            self.mem[k] = v


cache = _Cache()


@app.on_event("startup")
async def _startup():
    await store.connect()
    app.state.cache_backend = await cache.connect()
    from app.core.retrieval import get_model
    get_model()  # warm the embedder so the first request isn't slow
    print(f"[startup] store={store.backend} cache={app.state.cache_backend}")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "store": store.backend, "cache": getattr(app.state, "cache_backend", "?")}


@app.get("/metrics")
async def metrics():
    out = {"requests": _state["requests"], "cache_hits": _state["cache_hits"],
           "uptime_s": round(time.time() - _state["started"]), "store": store.backend}
    res = ROOT.parent / "eval" / "results.json"
    if res.exists():
        r = json.load(open(res))
        rl = r.get("any_position", {})
        out["eval"] = {"naive_safety": rl.get("naive", {}).get("safety_rate"),
                       "solver_safety": rl.get("solver", {}).get("safety_rate")}
    return out


@app.get("/product/{pid}")
async def product(pid: str):
    p = await store.get_product(pid)
    if not p:
        return JSONResponse({"error": "not found"}, status_code=404)
    return p


@app.post("/recommend/routine")
async def recommend_routine(req: RoutineRequest, constraints: str = Query("on")):
    _state["requests"] += 1
    enforce = constraints != "off"
    key = "rt:" + hashlib.md5(json.dumps(
        [req.skin_type, sorted(req.concerns), req.budget_inr, enforce, sorted(req.owned),
         sorted(req.exclude), sorted(req.exclusions)]).encode()).hexdigest()
    hit = await cache.get(key)
    if hit:
        _state["cache_hits"] += 1
        hit["cached"] = True
        return hit
    profile = sv.Profile(concerns=req.concerns or ["aging"], budget=req.budget_inr, skin=req.skin_type)
    result = await recommend(profile, enforce_conflicts=enforce, owned=req.owned, exclude=req.exclude,
                             exclusions=req.exclusions)
    result["cached"] = False
    await cache.set(key, result)
    return result


app.mount("/static", StaticFiles(directory=STATIC), name="static")
