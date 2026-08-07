# Build Plan — Skincare Routine Architect
### orbo.ai GenAI Intern Technical Assignment

**Deliverable priority order:** Document > Working demo > Code quality
**Time budget:** ~12 hours
**Submission:** PDF document + source repo + run instructions + test cases

---

## 0. The Thesis (memorize this — it's the whole submission)

> Recommender systems rank items independently. But nobody buys one skincare product — they build a routine, and skincare products chemically interact. Ranking is the wrong abstraction. Routine construction is a **constrained set-selection problem**, not a top-K problem.

Supporting insight that makes the design elegant:

> Ingredient conflicts are **per time-of-day**, not per routine. Retinol and vitamin C conflict in the same session, but split AM/PM and both are fine. So the system doesn't exclude conflicting products — it **schedules around** them.

Headline result to produce (fill in after eval):

> A conventional top-K recommender, built as a baseline, produced chemically conflicting routines in **___%** of cases. This system reduces that to 0% by construction, at ~___ms per request.

---

## 1. STEP ZERO — Go/No-Go Check (30 min, before writing anything else)

The entire angle depends on parseable ingredient lists. **Verify before committing.**

Dataset: Kaggle — *Sephora Products and Skincare Reviews* (`product_info.csv` + `reviews_*.csv`)
Fallback dataset: Amazon Reviews 2023, "All Beauty" category

Checks to run:

```python
import pandas as pd
df = pd.read_csv("product_info.csv")

print(len(df))                                    # expect ~8k
print(df['ingredients'].notna().mean())           # NEED > 0.70
print(df['ingredients'].dropna().sample(5).tolist())  # eyeball parseability
print(df.columns.tolist())                        # confirm price, category, rating, reviews_count

r = pd.read_csv("reviews_0-250.csv", nrows=50000)
print(r['skin_type'].notna().mean())              # NEED > 0.50
print(r['skin_tone'].notna().mean())
print(r['author_id'].nunique())
```

**Decision gate:**

| Condition | Action |
|---|---|
| `ingredients` populated >70% AND parseable | ✅ Proceed with this plan |
| `ingredients` 40–70% | ⚠️ Proceed, but scope to categories with good coverage; document as limitation |
| `ingredients` <40% | ❌ Abort to Fallback Plan (§10) |

Write the outcome into the decisions log immediately. This check is itself good material for the document — "I validated data feasibility before designing" is a point in your favour.

---

## 2. Architecture

```
                        ┌─────────────────────────────┐
   User input  ─────────▶│  1. QUERY UNDERSTANDING     │  Gemini + Redis cache
   (free text +          │     free text → filter JSON │  fallback: rule-based parser
    skin profile)        └──────────────┬──────────────┘
                                        │
                        ┌───────────────▼─────────────┐
                        │  2. HYBRID RETRIEVAL         │  per routine slot, top ~50
                        │     dense (MiniLM + FAISS)   │  LEARNED
                        │     + sparse (BM25)          │
                        │     fused via RRF            │
                        └───────────────┬──────────────┘
                                        │
                        ┌───────────────▼─────────────┐
                        │  3. HARD FILTERS             │  budget, category,
                        │                              │  exclusions, skin-type
                        └───────────────┬──────────────┘
                                        │
                        ┌───────────────▼─────────────┐
                        │  4. PREFERENCE RANKING       │  LEARNED
                        │  semantic + co-review CF     │
                        │  + Bayesian rating prior     │
                        │  + skin-attribute affinity   │
                        └───────────────┬──────────────┘
                                        │
                        ┌───────────────▼─────────────┐
                        │  5. BASKET SOLVER  ★NOVEL★   │  beam search over slots
                        │  conflict graph constraints  │  AM/PM scheduling
                        │  budget + coverage + anti-   │  DETERMINISTIC
                        │  redundancy objective        │
                        └───────────────┬──────────────┘
                                        │
                        ┌───────────────▼─────────────┐
                        │  6. EXPLANATION              │
                        │  safety claims ← rule engine │  ← NEVER the LLM
                        │  fit claims ← RAG over       │
                        │  matched-profile reviews     │
                        └──────────────────────────────┘
```

**Critical framing for the document:** rules handle *safety*, learned models handle *preference*. The conflict engine is a constraint layer **on top of** a learned ranker, not a substitute for one.

**Sanity test — run this and record the result:** disable the conflict layer entirely. The system must still produce good, personalized recommendations. If it doesn't, you built an expert system, not a recommender. This test belongs in the document.

---

## 3. Data Pipeline

### 3.1 Functional class taxonomy

Map ingredients → functional classes via keyword matching. Target ~20 classes covering the common actives:

```
CLEANSING:    cleanser_gentle, cleanser_foaming, cleanser_oil
ACTIVES:      retinoid, aha, bha, pha, vitamin_c_laa, vitamin_c_derivative,
              niacinamide, azelaic_acid, benzoyl_peroxide, hydroquinone,
              peptide, copper_peptide, sulfur
SUPPORT:      humectant, ceramide_barrier, occlusive, antioxidant_other,
              soothing, brightening_other
PROTECTION:   uv_filter_chemical, uv_filter_mineral
EXFOLIANT:    exfoliant_physical
```

### 3.2 Concentration-aware weighting

INCI ingredient lists are legally ordered by descending concentration for anything above 1%. So **position in the list is a free potency proxy.**

```python
weight = 1.0 / log2(position + 2)   # position 0 = highest concentration
```

Document this as an explicit assumption: *ordering gives relative rank, not absolute percentage.* Products list actives at 0.5% and 2% identically if both fall below the 1% threshold. Real limitation — say so.

### 3.3 Function vectors

Each product → sparse vector over the 20 functional classes, weighted as above. This powers:
- Redundancy detection (don't recommend two products doing the same thing)
- Conflict detection (operates on classes, not raw ingredient strings)
- Optional: dupe-finding, if time permits

### 3.4 Product text for embedding

Concatenate: `name + brand + category + highlights + top-10 ingredients + 3 most-cited review themes`

Embed with `sentence-transformers/all-MiniLM-L6-v2` (384-dim, CPU, ~2 min for 8k products). Index in FAISS. BM25 over the same text via `rank_bm25`.

---

## 4. Conflict Rule Base

Hardcode in `conflicts.yaml`. **~20 rules with citations. Twenty you can defend beats 500 you can't.**

| # | Class A | Class B | Severity | Reason |
|---|---|---|---|---|
| 1 | retinoid | aha | hard | Barrier disruption, irritation |
| 2 | retinoid | bha | hard | Barrier disruption, irritation |
| 3 | retinoid | benzoyl_peroxide | hard | BPO oxidises tretinoin, reduces efficacy |
| 4 | retinoid | vitamin_c_laa | hard | pH incompatibility, irritation |
| 5 | retinoid | exfoliant_physical | hard | Over-exfoliation |
| 6 | retinoid | retinoid | hard | Redundant + compounding irritation |
| 7 | vitamin_c_laa | aha | hard | pH interference |
| 8 | vitamin_c_laa | bha | hard | pH interference |
| 9 | vitamin_c_laa | copper_peptide | hard | Mutual oxidation/inactivation |
| 10 | copper_peptide | aha | hard | pH inactivation |
| 11 | benzoyl_peroxide | aha | soft | Cumulative over-drying |
| 12 | benzoyl_peroxide | bha | soft | Cumulative over-drying |
| 13 | aha | bha | soft | Over-exfoliation if both strong |
| 14 | aha | aha | soft | Redundant |
| 15 | hydroquinone | benzoyl_peroxide | soft | Oxidation, possible staining |
| 16 | vitamin_c_laa | niacinamide | **contested** | Legacy lab data suggests nicotinic acid conversion under heat; modern formulation consensus disputes this in finished products |
| 17 | niacinamide | aha | contested | pH-dependent, low real-world evidence |

### Rule schema — every rule carries its own explanation

Each entry in `conflicts.yaml` needs four fields, not two:

```yaml
- pair: [retinoid, bha]
  severity: hard
  mechanism: "Both disrupt the skin barrier. Layering them in one session
              causes irritation, dryness and peeling."
  citation: "Am Acad Dermatol — combination therapy tolerability guidance"
```

`mechanism` is what the user reads. `citation` is what makes it auditable.

**Hard constraint: `mechanism` is rendered verbatim from this file. The LLM never
generates chemistry.** Explanation surface = deterministic lookup for safety, LLM only for
fit/preference phrasing. State this explicitly in the document — it's the clearest signal in
the build that quasi-medical claims aren't being hallucinated.

Every conflict shown in the UI must also report **what the solver did**: `scheduled_apart`,
`product_swapped`, or `excluded_no_alternative`. "We avoided a conflict" is a claim; "we moved
your BHA to the morning" is verifiable against the board.

### Severity renders three ways

| Severity | Treatment | Copy pattern |
|---|---|---|
| `hard` | Blocked, danger tint | "We prevented this pairing." |
| `soft` | Allowed with caution, warning tint | "May over-dry — watch for tightness." |
| `contested` | Surfaced, neutral tint, user decides | "Widely described as conflicting. The claim traces to 1960s lab work under heat; formulation chemists largely dispute it in finished products. We surface it rather than decide for you." |

The `contested` card is a deliberate credibility play — most systems either apply folk wisdom
silently or ignore it silently. Showing the disagreement with provenance, and declining to
adjudicate, is the difference between an expert system and one built by someone who read the
primary sources.

**Placement rules** (not conflicts — scheduling constraints):

| Rule | Constraint |
|---|---|
| P1 | `retinoid` → PM only (UV photodegradation) |
| P2 | `vitamin_c_laa` → AM preferred (antioxidant/UV synergy) |
| P3 | `uv_filter_*` → AM, terminal step, **mandatory** if any photosensitiser present |
| P4 | `aha`/`bha` → PM preferred (photosensitivity) |

Rule 16 is your credibility play. Flagging a widely-repeated claim as *contested* rather than silently applying it shows you read primary sources instead of blog posts. Mention it explicitly in the document.

---

## 5. Basket Solver

Routine slots (scope to 4 for time):

```
cleanser  →  treatment  →  moisturizer  →  spf (AM only)
```

Objective:

```
maximize   Σ relevance(item)
         + α · concern_coverage(basket)
         − β · function_redundancy(basket)
         − γ · budget_overrun(basket)

subject to  no hard conflict within the same time-of-day session
            total_price ≤ budget
            placement rules P1–P4 satisfied
            SPF present if photosensitiser in AM
```

Beam search — search space is small (4 slots × ~20 candidates), runs in milliseconds:

```python
def solve(candidates_by_slot, profile, budget, beam_width=20):
    beams = [Basket()]
    for slot in SLOT_ORDER:
        next_beams = []
        for basket in beams:
            for item in candidates_by_slot[slot][:20]:
                for session in feasible_sessions(item):      # AM / PM / both
                    if violates_hard_conflict(basket, item, session): continue
                    if basket.price + item.price > budget * 1.15: continue
                    next_beams.append(basket.add(item, session))
        beams = top_k(next_beams, key=score, k=beam_width)
    return enforce_spf_rule(best(beams))
```

**Baseline to implement alongside it:** greedy top-1 per slot, no constraints. This is what produces your headline conflict-rate number. Do not skip it — it *is* the finding.

---

## 5.5 Open-World Handling — Products Not in the Catalogue

**The problem:** the catalogue is finite. A user says "I already use Minimalist 10% Niacinamide" or "find me a dupe for this" and the product isn't in the dataset.

**The reframe:** a product plays two distinct roles, with different requirements.

| Role | Must be in catalogue? |
|---|---|
| **Candidate to be recommended** | Yes — and that's correct. You can only recommend what's purchasable. |
| **Anchor / input** ("I already use X", "dupe for X") | **No.** |

The engine operates on **function vectors, not product IDs**. The catalogue is merely a convenient *source* of function vectors. Anything you can derive a function vector for, the system can reason about.

### Resolution ladder

| Tier | Method | Confidence | Conflict checking |
|---|---|---|---|
| 1 | Fuzzy name+brand match (`rapidfuzz`) | High | ✅ Full |
| 2 | Semantic match on product embeddings | High | ✅ Full |
| 3 | **User pastes INCI list from the box** → parse on the fly | **Full** | ✅ Full |
| 4 | LLM infers likely actives from product name | **Low (labelled)** | ❌ **Disabled** |
| 5 | User selects functional classes from dropdown | Medium | ⚠️ Partial, flagged |

Tier 3 is the real solution and costs ~20 lines — the ingredient parser already exists from §3.

### Hard safety rule

> **Never make a safety claim on LLM-inferred ingredient data.**

At Tier 4 the system must say: *"We couldn't verify this product's ingredients. Conflict checking is unavailable for it — please check manually."*

Refusing to print a confident green checkmark on unverified quasi-medical data is a deliberate design decision. Call it out in the document.

### Architectural claim this unlocks

The engine is **catalogue-agnostic**. Solver, conflict rules, and ranking depend only on an abstract interface:

```python
class ProductLike(Protocol):
    function_vector: dict[str, float]
    price: float | None
    category: str
    session_constraints: set[str]
    confidence: Literal["verified", "inferred", "user_supplied"]
```

Source — catalogue, user paste, or LLM inference — is a data-layer concern. orbo could point this at their own catalogue on day one. Say this explicitly in the document.

### Indian catalogue supplement (30–45 min, high ROI)

The Sephora dataset is US/Western and contains almost no Indian D2C brands. Hand-curate **25–30 products** with real ingredient lists into `data/sample/india_catalog.json`:

> Minimalist · Dot & Key · Deconstruct · The Derma Co · Foxtale · Plum · Re'equil · Cetaphil India · Aqualogica

This makes the demo feel local to the people evaluating it, and **proves** the catalogue-agnostic claim rather than asserting it. Cheapest credibility in the build.

---

## 6. Evaluation Plan

### 6.1 Standard metrics (DO NOT SKIP — the brief lists these explicitly)

Leave-one-out: users with ≥5 reviews, hold out most recent 4★+ item. Per-slot retrieval task.

| Method | Recall@10 | NDCG@10 | MAP@10 | HitRate@10 |
|---|---|---|---|---|
| Popularity baseline | | | | |
| Content-only (dense) | | | | |
| Co-review CF | | | | |
| **Hybrid (ours)** | | | | |

### 6.2 Beyond-accuracy

| Metric | Baseline | Ours |
|---|---|---|
| Catalog coverage | | |
| Intra-list diversity | | |
| Novelty (−log popularity) | | |
| Gini (popularity bias) | | |

### 6.3 Routine-level metrics (the novel contribution)

| Metric | Naive top-K | **Ours** |
|---|---|---|
| **Routine safety rate (0 violations)** | | ~100% |
| Concern coverage | | |
| Function redundancy (lower better) | | |
| Budget adherence | | |
| Placement-rule compliance | | |

### 6.3b Open-world resolution (see §5.5)

Take 30 product names deliberately *not* in the catalogue (incl. Indian D2C brands). Measure which tier resolves each:

| Resolution tier | Count | % |
|---|---|---|
| Tier 1–2 (matched to catalogue) | | |
| Tier 3 (ingredient paste) | | |
| Tier 4 (LLM inferred, conflict checking disabled) | | |
| Unresolved | | |

Also report: **false-match rate** — how often fuzzy/semantic matching confidently returns the *wrong* product. This is the failure mode that matters, since a wrong match produces confident wrong safety advice.

### 6.4 Latency

| Stage | p50 | p95 |
|---|---|---|
| Query parse (cold / warm cache) | | |
| Retrieval | | |
| Ranking | | |
| Basket solve | | |
| Explanation (LLM) | | |
| **End-to-end** | | |

### 6.5 Explanation faithfulness

LLM-as-judge over 30 sampled explanations: does every claim trace to a retrieved review or a conflict rule? Report the honest number, even if it's 80%.

---

## 7. Hour-by-Hour

| Hours | Task | Output |
|---|---|---|
| 0–0.5 | **Dataset go/no-go** | Decision recorded |
| 0.5–2.0 | Load to Mongo, ingredient parsing, function vectors | `products` collection enriched |
| 2.0–3.5 | Embeddings, FAISS, BM25, RRF retrieval | Working retrieval, testable |
| 3.5–5.0 | Conflict engine + basket solver + naive baseline | Routines generating |
| 5.0–6.5 | **Eval harness, run it** | **All tables above filled** |
| 6.5–7.5 | FastAPI endpoints, Redis, LLM layer | Service running |
| 7.5–9.0 | UI | Demoable |
| 9.0–11.5 | **Document + architecture diagram** | PDF |
| 11.5–12 | Clean-clone test, screenshots, zip | Submission |

**Decisions log: 5 minutes at the end of every hour.** Non-negotiable. The document is written from this log, not from memory at hour 10.

Note eval lands at hour 6.5, before the UI. If the headline number is unimpressive you find out with time to adjust the story.

---

## 8. Repo Structure

```
routine-architect/
├── README.md                    # run instructions + headline results table
├── DOCUMENT.pdf                 # ★ the main deliverable
├── docker-compose.yml           # mongo + redis + app, one command
├── .env.example
├── requirements.txt
├── data/
│   ├── raw/                     # (gitignored, download script provided)
│   └── sample/                  # 200-product sample so it runs without Kaggle
├── scripts/
│   ├── 00_verify_dataset.py
│   ├── 01_load_mongo.py
│   ├── 02_parse_ingredients.py
│   └── 03_build_indexes.py
├── app/
│   ├── main.py                  # FastAPI
│   ├── models.py                # Pydantic
│   ├── config/
│   │   ├── conflicts.yaml       # ★ cited rule base
│   │   └── functional_classes.yaml
│   ├── core/
│   │   ├── retrieval.py         # dense + BM25 + RRF
│   │   ├── ranking.py           # preference scoring
│   │   ├── conflicts.py         # rule engine
│   │   ├── solver.py            # ★ beam search
│   │   └── explain.py           # RAG explanations
│   ├── llm/
│   │   ├── parse.py             # + rule-based fallback
│   │   └── client.py            # retry, quota degradation
│   └── static/index.html        # UI
├── eval/
│   ├── run_eval.py
│   ├── metrics.py
│   └── results.json
├── tests/
│   ├── test_conflicts.py        # ★ prove rules fire correctly
│   └── test_solver.py
└── DECISIONS.md                 # running log
```

Endpoints: `POST /recommend/routine`, `POST /recommend/items`, `GET /product/{id}/similar`, `GET /health`, `GET /metrics`

---

## 9. The Document (main deliverable)

Target 10–14 pages. **Main body readable by a non-engineer; technical depth in appendices.** That layering demonstrates the skill they're selecting for.

| § | Section | Words | Notes |
|---|---|---|---|
| 1 | Executive summary | 350 | Zero jargon. Problem, insight, build, headline number, commercial meaning. Assume some readers stop here. |
| 2 | Problem statement | 500 | The reframe: nobody buys one product; products interact. |
| 3 | Why current platforms don't solve it | 400 | **Go audit Nykaa/Sephora/Amazon. Screenshot a cart with retinol + glycolic acid and no warning.** Primary evidence. |
| 4 | Approach & architecture | 700 | Diagram first, plain language, then technical. |
| 5 | Recommendation methodology | 700 | Retrieval → ranking → constraint solving → explanation. |
| 6 | Dataset & assumptions | 400 | Incl. INCI ordering assumption, coverage gaps. |
| 7 | Results | 700 | Standard tables, then the routine-safety headline. |
| 8 | Test cases: works / fails | 600 | Screenshots. Failures stated plainly. |
| 9 | Known limitations | 500 | See §11. Unflinching. |
| 10 | Business impact | 400 | AOV, return rate, review ratings, trust, support load. Their language. |
| 11 | Benchmark vs Nykaa/Sephora | 400 | Bonus challenge: similarities, differences, gaps, improvements. |
| 12 | Roadmap | 400 | Phased. Tie phase 2 to orbo's own skin-analysis capability. |
| 13 | **Closed-world vs open-world assumptions** | 450 | §5.5. Most submissions silently assume the catalogue is the universe. State the assumption, then show labelled-confidence degradation and the catalogue-agnostic interface. Strong production-thinking signal. |
| 14 | **What I'd want to know before building this for real** | 300 | Their return-rate data, a derm to validate rules, true ingredient coverage. Knowing what you don't know reads as senior. Almost no one will include this. |
| A–C | Appendices | — | Technical detail, run instructions, full rule base with citations. |

### Headline framing — get this right

❌ *"Baseline top-K recommender conflict rate: 0.31"*

✅ *"As a baseline I built a conventional recommender of the kind most e-commerce platforms use. On real user profiles, **31% of the routines it produced contained chemically conflicting products** — roughly one in three users receiving a routine that could irritate their skin. That is simultaneously a returns problem, a review-ratings problem, and a trust problem. This system reduces it to zero by construction, at a cost of ~40ms per request."*

Same number. One is a metric; the other is something a founder repeats in a meeting.

---

## 10. Fallback Plan

If the ingredient data fails the §1 gate: build the skin-aware hybrid recommender without the routine layer — hybrid retrieval, skin-attribute affinity ranking, RAG explanations from matched-profile reviews, full standard eval, Nykaa-style UI. Solid, lower ceiling. Decide in the first 30 minutes, not at hour 4.

If you stall mid-build: the hour-5 single-slot system is submittable on its own. Ship that rather than a broken solver.

---

## 11. Known Limitations (draft now, refine later)

- INCI ordering gives concentration *rank*, not percentage — cannot distinguish 0.5% from 2% retinol
- Conflict rules are Western-dermatology-centric and **not clinically validated**
- No medical validation; **explicit not-medical-advice disclaimer required**
- Shade/undertone matching for complexion products is out of scope — embeddings cannot represent undertone
- Review-derived signals are biased: reviewers aren't a random sample of users
- Cold-start for new products with no reviews relies on content signals alone
- Ingredient coverage incomplete for some brands
- Free-tier LLM quota limits; system degrades to rule-based parsing
- Prompt-injection surface in the free-text input
- **Catalogue is US/Western (Sephora); Indian D2C brands underrepresented.** Mitigated by the supplementary Indian catalogue (§5.5) and the catalogue-agnostic interface, but a production deployment needs a local catalogue
- **LLM-inferred ingredient lists can be wrong**, so conflict checking is deliberately disabled at Tier 4 rather than guessed at
- Fuzzy/semantic product matching can silently return the wrong product — measured as false-match rate (§6.3b), not assumed away

---

## 12. Non-Negotiables Checklist

- [ ] Runs from clean clone with **one command** (`docker compose up`)
- [ ] Works when the LLM quota is exhausted (graceful degradation, documented)
- [ ] Sample dataset committed so it runs without a Kaggle account
- [ ] Eval results table in README above the fold
- [ ] Standard metrics reported, not just novel ones
- [ ] Conflict-layer-off sanity test run and recorded
- [ ] **No safety claim ever made on LLM-inferred ingredient data** (§5.5)
- [ ] Unknown-product flow works and is demoed (paste-ingredients path)
- [ ] Indian catalogue supplement included
- [ ] Not-medical-advice disclaimer in UI and document
- [ ] Screenshots of UI in the document
- [ ] Nykaa/Sephora audit screenshots captured
- [ ] Document exported as PDF
- [ ] Tested on a fresh clone before submitting

---

*The code proves the document is true. The document is what gets remembered.*
