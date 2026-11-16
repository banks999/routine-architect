"""End-to-end latency of the SHIPPED request path (pipeline.recommend), LLM off.

Why this exists: extra_eval.latency() times ONE retrieval slot + the ranking build + the solve, and its
sum (~50 ms) was being quoted as 'end to end'. The real request retrieves for all five slots (each
embeds its query, runs FAISS + BM25 + RRF), so this measures the whole thing exactly as the API runs it.
Writes results.json['latency_e2e'].   Run: python -m eval.e2e_latency
"""
import asyncio
import itertools
import json
import os
import time
from pathlib import Path

import numpy as np

os.environ.pop("GEMINI_API_KEY", None)   # measure the deterministic path; LLM cost is reported separately
from app.core import pipeline as pl  # noqa: E402
from app.core import solver as sv  # noqa: E402
from app.db.store import store  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONC = [["acne", "aging"], ["texture", "dullness"], ["dark_spots", "redness"], ["dryness", "aging"],
        ["oiliness", "acne"], ["aging", "texture"]]
SKINS = ["oily", "dry", "combination", "normal"]


async def main(n_warm=5):
    await store.connect()
    profiles = [sv.Profile(concerns=c, budget=9000 + 700 * i, skin=s)
                for i, (c, s) in enumerate(itertools.product(CONC, SKINS))]
    for p in profiles[:n_warm]:
        await pl.recommend(p, use_llm=False)
    rows = []
    for p in profiles:
        t0 = time.perf_counter()
        r = await pl.recommend(p, use_llm=False)
        total = (time.perf_counter() - t0) * 1000
        rows.append({**r["latency_ms"], "total_ms": total})
    out = {"n": len(rows), "store": store.backend, "llm": False}
    for k in ["retrieval_and_rank_ms", "solve_ms", "explain_ms", "total_ms"]:
        a = np.array([r[k] for r in rows])
        out[k] = {"p50": round(float(np.percentile(a, 50)), 1), "p95": round(float(np.percentile(a, 95)), 1)}
    print(json.dumps(out, indent=1))
    path = ROOT / "eval" / "results.json"
    res = json.loads(path.read_text()); res["latency_e2e"] = out
    path.write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
