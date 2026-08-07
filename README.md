# Skincare Routine Architect

**Recommender systems rank items independently. But nobody buys one skincare product — they
build a routine, and skincare products chemically interact. Ranking is the wrong abstraction;
routine construction is a constrained set-selection problem.** The insight that makes it tractable:
ingredient conflicts are *per time-of-day*, so the solver **schedules around** them (AM/PM) instead
of excluding products.

## Headline result

| | Naive top-K recommender | This system |
|---|---|---|
| **Budget adherence** (threshold-independent) | **0%** — spends ~2.4× budget | **100%** |
| Placement compliance — retinoid PM, etc. (any-position) | 61.5% | 100% |
| Routines with ≥1 hard ingredient conflict (any-position) | 21% | **0% (by construction)** |
| Latency (end-to-end, warm) | — | ~40 ms |

*(200 synthetic profiles. The budget result needs no ingredient-detection threshold and is the
hardest number. Real co-reviewed product sets show the conflict effect directly: conflict rate rises
**2.5% → 50%** with basket size — real data, see `DECISIONS.md`.)*

## Quick start (one command)

```bash
docker compose up --build      # then open http://localhost:8000
```

Mongo + Redis + the API come up together; the API loads Mongo from committed data and serves the UI.
FAISS/BM25/embedding indexes are **prebuilt and committed** (`data/processed/`) — no build step, no
Kaggle account needed. A Gemini key is optional (`GEMINI_API_KEY` in `.env`); without it, explanations
use a rule-based template grounded in matched-skin review snippets.

**Try:** click the four preset buttons. "Oily & acne-prone" forces an AM/PM split (BHA morning,
retinoid night); "Tight ₹5,000" makes the budget constraint visibly bind. Flip the **Safety layer**
toggle off to watch the same routine ship a red conflict.

### Run without Docker (dev)

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload      # runs with a parquet fallback if Mongo/Redis are absent
```

## What's inside

- **Conflict engine** (`app/core/conflicts.py`, `app/config/conflicts.yaml`) — 17 cited rules + AM/PM
  placement rules, three severity tiers (hard/soft/**contested**). Safety text is verbatim from YAML,
  **never LLM-generated**.
- **Beam-search solver** (`app/core/solver.py`) — relevance + coverage − redundancy − budget, subject
  to no-same-session-conflict / placement / budget / mandatory-SPF. Naive baseline on the same interface.
- **Hybrid retrieval** (dense MiniLM+FAISS + BM25, RRF) → **learned ranker** (semantic + co-review CF +
  Bayesian rating + skin affinity, temporally-validated weights).
- **Eval** (`eval/`) — standard metrics (warm/cold cohorts), routine-safety headline, beyond-accuracy,
  latency. Results in `eval/results.json`.

## Endpoints

`POST /recommend/routine[?constraints=off]` · `GET /product/{id}` · `GET /health` · `GET /metrics` · `GET /` (UI)

## Data

`scripts/00_verify_dataset.py` → `01_load_mongo.py` → `02_parse_ingredients.py` → `03_build_indexes.py`
→ `04_build_rank_priors.py`. Raw Kaggle *Sephora Products and Skincare Reviews* goes in `data/raw/`
(gitignored); a 200-product-equivalent processed set + sample reviews are committed so it runs offline.

> ⚠️ **Not medical advice.** Conflict rules are Western-dermatology heuristics, not clinically validated.
