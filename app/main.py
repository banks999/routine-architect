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
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app.core import solver as sv
from app.core.pipeline import recommend
from app.db.store import store

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
_state = {"requests": 0, "cache_hits": 0, "started": time.time()}


SkinType = Literal["combination", "oily", "dry", "normal"]
Concern = Literal["aging", "texture", "acne", "dark_spots", "dullness", "redness", "dryness", "oiliness"]
# Exact strings the UI sends (app/core/filters.py matches on these). Anything else is a 422, never
# silently ignored: a safety filter that is accepted but not applied is the worst failure mode.
Exclusion = Literal["fragrance", "essential oils", "pregnancy-safe only", "alcohol"]


class RoutineRequest(BaseModel):
    skin_type: SkinType = Field("combination", examples=["oily"])
    concerns: list[Concern] = Field(..., min_length=1, max_length=4, examples=[["aging", "texture"]])
    budget_inr: float = Field(12000, ge=1000, le=100000)
    exclusions: list[Exclusion] = Field(default=[], max_length=4, description="Hard filters: fragrance / essential oils / pregnancy-safe only / alcohol")
    owned: list[str] = Field(default=[], max_length=5, description="Products the user already uses (§5.5); a name or a pasted INCI list")
    exclude: list[str] = Field(default=[], max_length=50, description="Product ids rejected via swap (§2d)")

    @field_validator("owned")
    @classmethod
    def _owned_len(cls, v):
        if any(len(x) > 3000 for x in v):
            raise ValueError("an owned-product entry is limited to 3000 characters")
        return v

    @field_validator("exclude")
    @classmethod
    def _exclude_len(cls, v):
        if any(len(x) > 40 for x in v):
            raise ValueError("product ids are at most 40 characters")
        return v


class _Limiter:
    """In-memory sliding window, per client IP plus one global ceiling. Public-demo protection, not
    auth: the first X-Forwarded-For hop is client-reported, so a determined caller can rotate it —
    the global ceiling is what actually protects the host."""

    def __init__(self, per_ip: int, global_cap: int, window: float = 60.0):
        self.per_ip, self.global_cap, self.window = per_ip, global_cap, window
        self.hits: dict[str, deque] = {}
        self.all: deque = deque()

    def _prune(self, q: deque, now: float):
        while q and now - q[0] > self.window:
            q.popleft()

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        self._prune(self.all, now)
        q = self.hits.setdefault(ip, deque())
        self._prune(q, now)
        if len(self.all) >= self.global_cap or len(q) >= self.per_ip:
            return False
        q.append(now); self.all.append(now)
        if len(self.hits) > 5000:   # drop idle clients so the dict can't grow without bound
            for k in [k for k, v in self.hits.items() if not v]:
                del self.hits[k]
        return True


# Free-tier LLM quota protection: per-IP and global hourly budgets for Gemini calls. Over budget the
# request is still served — explanations just come from the deterministic template.
_limiter = _Limiter(int(os.getenv("RATE_LIMIT_PER_MIN", "20")), int(os.getenv("RATE_LIMIT_GLOBAL_PER_MIN", "200")))
_llm_ip = _Limiter(int(os.getenv("LLM_PER_IP_PER_HOUR", "10")), int(os.getenv("LLM_GLOBAL_PER_HOUR", "100")), window=3600.0)


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    return (xff.split(",")[0].strip() if xff else (request.client.host if request.client else "?"))


class _Cache:
    MAX_MEM = 500   # in-memory fallback is a bounded LRU: a public site must not grow without limit

    def __init__(self):
        self.mem, self.redis = OrderedDict(), None

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
        v = self.mem.get(k)
        if v is not None:
            self.mem.move_to_end(k)
        return v

    async def set(self, k, v, ttl=3600):
        if self.redis:
            await self.redis.set(k, json.dumps(v), ex=ttl)
        else:
            self.mem[k] = v
            self.mem.move_to_end(k)
            while len(self.mem) > self.MAX_MEM:
                self.mem.popitem(last=False)


cache = _Cache()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await store.connect()
    app.state.cache_backend = await cache.connect()
    from app.core.retrieval import get_model
    get_model()  # warm the embedder so the first request isn't slow
    print(f"[startup] store={store.backend} cache={app.state.cache_backend}")
    yield


app = FastAPI(title="Skincare Routine Architect", lifespan=lifespan)


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
async def recommend_routine(req: RoutineRequest, request: Request, constraints: str = Query("on")):
    ip = _client_ip(request)
    if not _limiter.allow(ip):
        return JSONResponse({"error": "Too many requests — please wait a minute and try again."},
                            status_code=429, headers={"Retry-After": "60"})
    _state["requests"] += 1
    enforce = constraints != "off"
    # LLM explanations only if a key is configured AND this client/global hourly budget allows it.
    # `llm` is part of the cache key so a template-mode result is never served as an LLM one.
    llm = bool(os.getenv("GEMINI_API_KEY")) and _llm_ip.allow(ip)
    key = "rt:" + hashlib.md5(json.dumps(
        [req.skin_type, sorted(req.concerns), req.budget_inr, enforce, sorted(req.owned),
         sorted(req.exclude), sorted(req.exclusions), llm]).encode()).hexdigest()
    hit = await cache.get(key)
    if hit:
        _state["cache_hits"] += 1
        hit["cached"] = True
        return hit
    profile = sv.Profile(concerns=req.concerns, budget=req.budget_inr, skin=req.skin_type)
    result = await recommend(profile, enforce_conflicts=enforce, owned=req.owned, exclude=req.exclude,
                             exclusions=req.exclusions, use_llm=llm)
    result["cached"] = False
    await cache.set(key, result)
    return result


app.mount("/static", StaticFiles(directory=STATIC), name="static")
