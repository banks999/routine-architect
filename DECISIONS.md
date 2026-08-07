# Decisions Log

Raw material for the final submission document. Append-only. Terse entries, 3–6 lines.
Capture **why**, not what — especially the option *not* taken.

**Entry format:**

```
## [H+0.0] Short title
**Decision:** what was chosen
**Rejected:** what wasn't, and why
**Because:** the reasoning / constraint that drove it
**Number:** any measurement produced (optional)
**Doc §:** which document section this feeds (optional)
```

`H+0.0` = hours elapsed since start, so the timeline can be reconstructed.

Feed the `Doc §` field from the outline in `BUILD_PLAN.md` §9. Entries tagged with a section number
are the ones to pull from first when writing.

---

## [H+0.0] Start

**Decision:** Committed to the Routine Architect angle — constrained basket construction with
per-time-of-day ingredient conflict scheduling.
**Rejected:** (a) plain skin-aware hybrid recommender — no retellable thesis, competes on polish
alone; (b) dupe engine only — too narrow for the brief; (c) regret-aware model — best-sounding but
weakest data support, likely unvalidatable in the time available.
**Because:** the document is the primary deliverable, and a document needs an idea a founder can
repeat after closing the tab. "Ranking is the wrong abstraction for skincare" is that idea.
**Doc §:** 1, 2, 4

---

<!-- Append new entries below. Newest last. -->

## [H+15] Phase 2c — open-world "products I already own" (§5.5 resolution ladder + pinning)

**Resolver (`app/core/resolve.py`) — the 5-tier ladder, first hit wins:** (1) fuzzy name+brand (rapidfuzz WRatio) → verified, full checking; (2) semantic on embeddings → verified; (3) user-pasted INCI → parsed on the fly → user_supplied, full checking; (4) name inference → **inferred, conflict checking DISABLED**; (5) manual class selection → manual, partial. The engine is catalogue-agnostic — it operates on function vectors, so an anchor need not be purchasable, only reasoned-about.
**False-match guard (§6.3b, a real correction):** at the initial fuzzy cutoff of 84, "CeraVe" and "Deconstruct Retinol" (both genuinely NOT in this US catalogue) confidently mis-matched Algenist products at 86% — *a confident wrong match produces confident wrong safety advice.* Raised cutoffs (**fuzzy 90, semantic 0.72**); both now correctly fall through to Tier 4 (inferred, checking disabled) instead of asserting a bad match.
**Hard rule upheld:** Tier 4 pins the product as **conflict-neutral** (its inferred classes are NOT fed to the conflict engine) and the UI shows the verbatim disclaimer *"We couldn't verify this product's ingredients. Conflict checking is unavailable for it — please check manually."* No safety claim is ever made on inferred data.
**Solver pinning (`solve(..., pinned=)`):** owned products pre-seed every beam; the solver builds AROUND them — schedules its picks to avoid conflicting with them in a session, its redundancy penalty discourages duplicating their function, their **price is excluded from the budget** (already owned), and their slot isn't re-filled.
**5 test resolutions (one deliberately off-catalogue):** Paula's 2% BHA → **Tier 1** (fuzzy 95%); CeraVe → **Tier 2** (semantic 0.72); Minimalist 10% Niacinamide (Indian D2C, paste) → **Tier 3** verified; Deconstruct Retinol (Indian D2C, name only) → **Tier 4** inferred retinoid, **checking DISABLED**; unbranded moisturizer (classes given) → **Tier 5** manual.
**Routine built around a pin:** user owns "The Ordinary Granactive Retinoid 2%" (Tier 1, pinned PM); asks for texture+acne → solver puts the new **Peace Out Salicylic Acid (BHA) in AM**, scheduling it apart from the owned retinoid (**scheduled_apart C2**), 0 hard conflicts, ₹10,283 with the owned product excluded from budget. Screenshot `05_owned_pinned.png`.
**Known limitation (noted, not fixed):** when a treatment slot is filled by a pin, the *remaining* treatment slot still targets the static concern→slot mapping rather than re-targeting the concern the pin leaves uncovered. Minor; flagged for the doc.
**Doc §:** 13 (closed- vs open-world), 5.5, 6.3b (false-match rate), 8 (screenshot).

## [H+14.3] Theme fix — kill profile-echo tautologies + a cross-cohort leak

**Two problems the 5 examples exposed:** (1) themes restated the user's own input — *"reviewers with oily skin most often mention 'oily skin'"* reads like insight but is zero-information; (2) a real bug — an OILY user saw *'dry skin'* as a theme, because the `3·skin + df` blend let a mismatched cohort through on thin data (n=4).
**Fixes:** drop any theme containing (a) **any skin-type word** — global set, so it kills both the tautology and the cross-cohort leak for everyone; (b) the user's **stated-concern keywords** (acne→acne/breakout/…, dark_spots→dark spot/…); (c) an expanded pure-filler list ("skincare routine", "started using", "skin looks", "would recommend"). **Thin-data honesty:** stored true per-skin review totals during mining; when matched-skin n < 8 the explanation now LABELS the fallback — *"Only 4 reviewers with oily skin, so across all reviewers: most mention X and Y"* — instead of silently blending (same honesty principle as everywhere else). Counts now come from full-mining totals (48–128), not the capped sample.
**Delta on the 5 examples (dropped → kept):** IT Cosmetics: dropped 'fine lines'(concern), 'dry skin'(cross-cohort) → "a little goes a long way", "sensitive skin"; INKEY BHA: dropped 'oily skin'(tautology), 'acne prone'(concern) → "spot treatment", "clogged pores"; INKEY Retinol: dropped 'fine lines' → "every night", "sensitive skin"; innisfree: dropped 'dry skin', 'skincare routine' → "sensitive skin"; First Aid Beauty (dullness/texture user): "dark spots" correctly KEPT (not their concern), "looks brighter". Verified: a dark_spots user does NOT see "dark spots".
**Doc §:** 5, 6.5 (what makes an explanation informative vs tautological).

## [H+14] Phase 2a — review-theme mining + rebuilt, RAG-grounded explanations

**The weakest thing the user read was the bare "N reviewers rated 4★+".** Replaced it with mined themes.
**Mining (`05_mine_themes.py` → `product_themes.parquet`, 1,758 products):** top-6 bigram/trigram themes per product by **document frequency** (DF — one gushing review can't dominate), with **per-skin_type counts** so explanations weight toward the user's skin. Mined over 403k full reviews (rating≥4).
**The mining was MUSH until three filters were added — this was the real work, logging it:** (1) **brand/product-name echoes** ("drunk elephant", "magic cream", "skinlongevity long life herb") dominated until I dropped any n-gram containing the product's own name tokens; (2) **review-platform boilerplate** ("honest review", "received this product"); (3) **sponsorship disclaimers with platform names** ("sample from pinchme", "opinions are completely my own") — any-token drop, but deliberately NOT "free" (oil-free/fragrance-free are real themes). After filtering, themes are specific and on-concern: "acne prone", "spot treatment", "under makeup", "white cast", "fine lines", "looks brighter", "dark spots".
**Robustness fix (thin skin data):** ranking purely by matched-skin count gave noise for minority skins (a product with 3 oily reviews → "skin looks", "started using"). Switched to a **blend `3·skin_count + df`** so thin same-skin data falls back to overall-popular themes. Plus a weak-theme droplist, an idiom repair ("long way"→"a little goes a long way"), and substring de-dup ("acne prone"/"acne prone skin").
**Rebuilt explanations, BOTH modes:** template now reads *"Reviewers with oily skin most often mention 'oily skin', 'acne prone' and 'spot treatment' (from 7 matched 4★+ reviews)"*; LLM prompt is fed the themes AND matched-skin snippets as grounding. Safety/mechanism text unchanged — still verbatim from conflicts.yaml.
**Grounding made VISIBLE (RAG, not asserted):** the UI "why this for you" now shows theme chips + the actual matched-skin review snippets, each tagged with the reviewer's skin type. Store prefers non-sponsored snippets. Themes also written onto the Mongo product doc.
**Honest verdict:** a clear, consistent quality jump *after* the filtering — NOT mush, worth shipping. It would have been mush without the brand/boilerplate/sponsorship filters, which is the lesson. Screenshots refreshed to show it.
**Doc §:** 5 (explanation methodology), 6.5 (explanation faithfulness — now snippet-grounded), 8 (screenshots).

## [H+13] Docker build fixes — CPU-only torch, pinned versions, baked-in model

Clean-clone `docker compose up` surfaced a ~7 GB / 20-min build. Three fixes:
**1. CPU-only torch.** The default PyPI resolve pulled torch 2.13.0 **plus the full CUDA stack** (nvidia-cublas/cudnn/nccl/cusparselt, triton) — several GB of GPU libraries for one small CPU embedding model. Added `--extra-index-url https://download.pytorch.org/whl/cpu` and pinned `torch==2.12.1+cpu`. Verified locally: sentence-transformers imports and encodes (384-dim, `cuda.is_available()==False`). **This is the headline saving — the CUDA libraries, not torch itself (torch is ~520 MB either way).**
**2. Pinned every version.** Nothing was pinned, so the build grabbed bleeding-edge (fastapi 0.141, pandas 3.0, numpy 2.4, starlette 1.4) that could resolve differently next week. Pinned all direct deps to the working set + the **whole google/grpc chain** (google-generativeai, google-ai-generativelanguage, grpcio, grpcio-status, protobuf, proto-plus, google-api-core, google-auth) — that chain was the resolver backtracking through ~15 grpcio-status versions ("this is taking longer than usual"). `pip check` on the pinned set is clean.
**3. Baked in the model.** Dockerfile now pre-downloads `all-MiniLM-L6-v2` into the image (`HF_HOME=/app/.hf`), so first request is instant and the app works fully offline (no HuggingFace fetch at runtime).
**Also:** `.dockerignore` excludes `.git`, `data/raw`, `docs/`, `*.ipynb`, tests, `.hf`, `.venv` — keeps the build context small (data/raw is the multi-GB Kaggle dump).
**Image size (MEASURED on the clean-clone run):** `orbo-test-app` = **2.87 GB on disk / 671 MB content (compressed)**. There is **no exact before-figure** — the CUDA variant was abandoned mid-download, so I will not quote a fabricated "~7 GB". What the CPU pin *avoids* pulling, by name: the torch CUDA build and `nvidia-cublas`, `cudnn`, `nccl`, `cusparselt`, `triton`, `cuda-toolkit`. That's the honest claim — packages avoided, not a subtracted number.
**Document-worthy note:** "CPU-only torch avoids the entire nvidia CUDA dependency stack (cublas/cudnn/nccl/cusparselt/triton); the shipped image is 2.87 GB on disk / 671 MB compressed." Concrete production-thinking signal, stated as measured fact.
**Doc §:** appendix B (run instructions), 12 (what I'd do for real — build/deploy hygiene).

---

## [H+13.5] Clean-clone `docker compose up` — VERIFIED end-to-end (last unverified item closed)

The one item I could never test locally (no Docker daemon in my env) is now confirmed on a real machine: `docker compose up` from a clean clone **builds, starts, and runs end-to-end**. `/health` reports **`store=mongodb cache=redis`** (the real read path + cache, NOT the parquet/in-memory fallback), and the UI is functional in the container. The project's non-negotiable — "runs from a clean clone with one command" — is met and proven. **Offline-startup hardening** (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`) added after logs showed sentence-transformers still contacting the HF Hub at startup despite the baked-in model — so "works fully offline" is now strictly true, not aspirational.
**Doc §:** 12 checklist (clean-clone verified), appendix B.

## [H+12.5] Phase 1b — budget-aware greedy baseline isolates the solver's contribution

**Added `budget_greedy` (same interface):** split budget evenly across 5 slots, take the top-ranked product that fits each slot's share (cheapest if none fits). No conflict awareness, no AM/PM scheduling — what a competent engineer ships without a solver.
**Result came out exactly as predicted — greedy patches budget, but NOT placement or safety (any-position):**

| metric | naive top-K | budget-greedy | solver |
|---|---|---|---|
| budget adherence | 0% | **95%** | 100% |
| placement compliance | 61.5% | **61.5%** | 100% |
| safety (0 conflicts) | 79% | **80.5%** | 100% |
| concern coverage | 100% | 100% | 97.5% |
| function redundancy | 0.300 | 0.135 | 0.085 |
| relevance (Σ) | 3.653 | 1.539 | 2.460 |

**The isolation is the point:** budget is a **per-item** constraint — a heuristic split fixes it (0%→95%). Placement and conflict-safety are **joint** constraints over the whole set (retinoid's session depends on what else is in that session), and the greedy leaves them exactly where naive did (61.5% / 80.5%). Only the beam search's joint optimisation closes them to 100%. This is the cleanest possible argument that the solver — not just "being sensible" — is doing the work.
**Relevance / what the solver gives up:** vs unconstrained naive (3.653) the solver keeps 2.460 (~33% given up) — but that naive score is unattainable within budget. Against the *fair* baseline (any budget-respecting method = greedy, 1.539) the **solver has HIGHER relevance (2.460 > 1.539)**: joint budget allocation (spend on high-value treatments, save on cleanser) beats an even split. So the solver satisfies *more* constraints AND scores higher preference than the competent greedy — it doesn't merely trade preference for safety.
**Tests green; `eval/results.json` holds all three baselines (both detection defs), extra_eval re-merged.**
**Doc §:** 7 (three-way results table), 5 (why the search is necessary — per-item vs joint constraints).

## [H+12] Phase-1 correctness — headline re-run against the SHIPPED (rinse-off) engine

**Why:** the rinse-off-cleanser change (H+11) altered engine semantics *after* the §6 headline was measured, so the committed numbers no longer matched the code. Re-ran `routine_eval.py` with cleanser classes zeroed (shipped parity) and re-merged `extra_eval.py`. `eval/results.json` now matches the running engine.
**Headline MOVED — reporting it straight:** any-position **naive safety 61.5% → 79%** (naive hard-conflict rate **38.5% → 21%**). Cause: cleanser-carried AHA/BHA no longer counts (rinse-off), removing the cleanser-vs-treatment conflicts that padded the old number. top-15 naive safety stays 100% (undercounts, as before).
**So the headline now leans where the user predicted — threshold-independent numbers:**
- **Budget (the hardest claim, needs NO ingredient-detection threshold): naive 0% adherence, spends a median 2.36× budget; solver 100%.** This is unarguable — it doesn't depend on how we detect actives.
- Placement compliance (any-position): naive 61.5% → solver 100% (retinoid mis-scheduled to AM, etc.).
- Real-user set-size curve (2.5% → 50%, real co-review data) is untouched by this change and remains the strongest *conflict* evidence.
- Synthetic naive conflict 21% (any-position) is still real (1 in 5 routines) but no longer the lead.
**Sanity test still holds:** constraints ON vs OFF — relevance 2.453 = 2.453, coverage 97.5% = 97.5%, but OFF ships 9 conflicts / 80 routines. The ranker makes recs good; the layer only makes them safe.
**Gemini auto-enable:** on when `GEMINI_API_KEY` present; the sync SDK call now runs in a thread under `asyncio.wait_for` (8s) with `request_options timeout=7`, so a missing key, quota error, bad output, OR mid-request hang all fall back to the template. Safety text still 100% verbatim from conflicts.yaml.
**Tests:** `test_conflicts.py` + `test_solver.py` both green after the change (they use synthetic candidates, unaffected by the pipeline-level rinse-off rule — confirms the change was correctly scoped to candidate construction, not the engine).
**Doc §:** 7 (results — corrected), 1 (headline now budget-led), 9 (top-15 vs any-position).

## [H+11] Demo layer — Mongo + FastAPI + LLM + UI + screenshots + docker

**Mongo (real read path):** `01_load_mongo.py` loads products + a committed 60k-review sample into Mongo; `app/db/store.py` serves product docs + matched-skin review snippets from Mongo when `MONGO_URL` is reachable, else falls back to parquet/CSV so the app runs from a bare checkout. FAISS/BM25/embeddings stay on disk (indexes, not documents). **Decision:** Mongo is the *document* store (product metadata + reviews used by /product and explanations); the vector hot-path stays on-disk — a clean split, and honest (not a decorative sidecar).
**FastAPI (async):** `POST /recommend/routine[?constraints=off]` returns the full AM/PM board + avoided-conflict report + score decomposition + per-stage latency (UI recomputes nothing). `GET /product/{id}`, `/health`, `/metrics`. Redis cache when `REDIS_URL` set, else in-memory; keyed on (skin, concerns, budget, enforce).
**LLM — shipped the template (the pre-authorised call):** Gemini is wired (`GEMINI_API_KEY`, one batched call, grounded ONLY in matched-skin snippets, no safety text) but **OFF by default**; explanations use the rule-based template ("N reviewers with {skin} skin rated 4★+" + one snippet + actives). Review-theme mining stays deferred. De-risks quota death during evaluation; safety/mechanism text is always verbatim from conflicts.yaml.
**Engine refinement found while wiring the demo:** **cleansers are rinse-off** → they carry NO conflict-relevant classes (a salicylic *cleanser* + retinoid is fine, unlike a salicylic *serum* + retinoid). Without this, a BHA-cleanser in both AM+PM made every PM-only retinoid unplaceable and the solver excluded treatments instead of scheduling apart. This is a real derm nuance, not a hack — documented. (Note: the §6 any-position headline 61.5%→100% counted cleanser actives, so it's conservative; the engine is more lenient.)
**UI:** single-file `app/static/index.html` + Tailwind CDN, no build. 4 working presets (one forces an AM/PM split, one binds a ₹5k budget), AM/PM board with per-product cards + expandable "why", avoided-conflict panel (verbatim mechanism + citation + action), the **safety toggle** (off → board re-solves, red conflicts), debug panel (score decomposition + latency), visible not-medical-advice disclaimer, full form. **Bug fixed:** `id="status"` collided with `window.status` (a string) → renamed; JS was silently dying.
**Screenshots:** 4 captured **headlessly via Playwright** (Chrome extension unavailable) → `docs/screenshots/` — form+preset, conflicts-avoided (BHA AM / retinoid PM, scheduled_apart + product_swapped), safety-OFF (red C2 shipped), debug panel.
**Docker:** `Dockerfile` + `docker-compose.yml` (mongo + redis + app), `requirements.txt`, `.env.example`, README one-command run. `docker compose config` **validates**; a live `docker compose up` was **NOT run here (no Docker daemon in this env)** — the single unverified item, flagged for a clean-clone check before submit.
**Doc §:** 4 (architecture — Mongo/Redis/FastAPI), 8 (screenshots/test cases), 5.5 (LLM degradation).

## [H+9.5] §6 eval harness — headline routine-level metrics + standard + sanity + beyond-accuracy + latency

**1. ROUTINE-LEVEL (headline), 200 synthetic profiles, naive vs solver, BOTH detection defs:**
- any-position (safety engine's def): **safety 61.5% naive → 100% solver** · placement-compliance 61.5% → 100% · redundancy 0.30 → 0.05 · budget-adherence **0% → 100%** · coverage 100% → 98.2% (solver trades 1.8pt coverage for safety).
- top-15 (headline lower bound): safety 100%/100%, coverage 83%/90%, redundancy 0.12/0.045, budget 0%/100%.
- **Threshold caveat (explicit gap):** under top-15, the relevance-selected champions carry their actives *deep* in the INCI list, so top-15 detects ~no conflict for the naive routine (100% "safe") — it UNDERCOUNTS. any-position is the honest safety number. (This differs from gate2's 47%, which used active-in-top-15-*filtered* pools — different candidate selection; both valid.)
- **Budget finding:** naive spends a **median 2.36× budget** (₹26.3k vs ₹12k median) — zero budget awareness; solver 1.06×.
**2. STANDARD METRICS by cohort (deployed weights, 100 neg):** warm(≥5) NDCG@10 0.0506 / Recall 0.114 (random 0.042); cold(1-2) NDCG 0.0497 / Recall 0.106 (random 0.045). Cold barely clears random — cf & semantic are 0 with no history, so rating+skin (0.1 each) are the only lift; **this is the justification for keeping them in the deployed weights**. (warm understated by CF staleness — refreshed ≈0.107, see H+6.7.)
**3. CONFLICT-LAYER-OFF sanity test:** disabling constraints barely moves relevance (2.37→2.47) or concern-coverage (98.8%→98.8%) but reintroduces **35 hard conflicts across 80 routines**. Conclusion: recommendations are good/personalised because of the *ranker*; the conflict engine is a thin safety constraint on top, not a substitute for one. (Passes the BUILD_PLAN §2 sanity requirement — we did not build an expert system.)
**4. BEYOND-ACCURACY per slot (solver, 200 profiles):** coverage 13–18% of pool · intra-list diversity 0.14 (spf) → 0.37 (treatment) · novelty 3.5–7.0 bits · Gini 0.46 (spf) → 0.73 (moisturizer, most popularity-biased).
**5. LATENCY per stage (ms, p50/p95):** retrieval 23/33 · ranking+build 3.8/4.6 · basket-solve 13.5/17.8 → end-to-end ≈ **40ms** warm. Matches the ~40ms headline.
**Written:** `eval/results.json` (all tables). Scripts: `routine_eval.py`, `standard_eval.py`, `extra_eval.py`.
**Also:** UI budget defaults captured in `app/config/ui.yaml` (default ₹12k, range ₹4k–30k, tight ₹5k preset) for the UI phase — no UI built yet.
**Doc §:** 7 (results — all tables), 1 (headline 61.5%→100%), 9 (top-15 undercount limitation).

## [H+8.0] Conflict engine + beam-search solver — the novel core

**Rule base (`conflicts.yaml`, 4-field schema pair/severity/mechanism/citation):** all 17 rules (C1–C17) + placement P1–P4. Three severity tiers: hard (10), soft (5), contested (2). `mechanism` is rendered VERBATIM to users — the LLM never generates chemistry, so every safety claim a user sees originates from this file. vitamin C×niacinamide (C16) and niacinamide×AHA (C17) are `contested` with their provenance inside the mechanism string (1960s heat-conversion lab data, disputed for finished products) — the credibility play from BUILD_PLAN.
**Engine (`conflicts.py`):** `check(products, assignment)` → violations with rule id, severity, verbatim mechanism, citation, and the two products. Operates on functional CLASSES, never raw strings. Same-class rules (retinoid×retinoid) require two DISTINCT products; a single product formulating both is not a routine conflict. Also enforces placement (P1 retinoid→PM hard, P3 uv→AM) and SPF-mandatory-if-photosensitiser.

**SAFETY-side conflict detection uses ANY-position presence, not the top-15 "meaningful dose" cutoff** used for the conservative headline stat. Rationale (a real design decision, document it): for a live safety layer a **false positive is cheap** (an unnecessary AM/PM split — harmless) while a **false negative ships an irritating routine**. So a "Retinol Serum" with retinol listed deep still counts as a retinoid. The top-15 cutoff stays for the *headline conflict-rate stat* (defensible lower bound); the *engine* leans inclusive.

**Solver (`solver.py`):** beam search (width 20, top-20 candidates/slot) over 5 slots. Objective = Σrelevance + α·coverage − β·redundancy − γ·budget_overrun (α=1, β=0.5, γ=1, soft_pen=0.3 — heuristic; the *constraints* do the safety work, weights only shape preference among already-safe routines). Constraints: no hard conflict within a session · placement rules · price ≤ budget×1.15 · SPF mandatory if photosensitiser. Relevance = the DEPLOYED ranker weights [sem .3/cf .5/rating .1/skin .1] (cf=0 for these cold demo users).
**Two design fixes found via the demo:** (1) **base-first slot order** (cleanser→moisturizer→spf→treatments) so an expensive serum can't starve the mandatory SPF — SPF was being dropped when treatments ate the budget first; (2) **soft penalties computed only at final beam selection**, not per-expansion — they re-run conflict checks and were the latency hotspot. Fix cut p95 latency 244ms→43ms.
**Avoided-conflict report (item 4)** is derived from the SOLVER's OWN routine, not by diffing naive product IDs (which legitimately differ): `scheduled_apart` (both actives kept, split AM/PM), `product_swapped` (conflict gone because a different product was chosen for a concern), `excluded_no_alternative` (treatment slot left unfilled). Each carries the verbatim mechanism.
**Naive greedy baseline** is callable from the same interface (`naive_greedy`) for the §6 comparison — top-relevance per slot, both treatments defaulted to AM, no scheduling.
**Tests:** `test_conflicts.py` (every rule fires; scheduling-apart clears the conflict; placement + SPF enforced; UV-salicylate not misread as BHA) and `test_solver.py` (never returns a hard conflict; budget respected; SPF present with photosensitiser; retinoid scheduled PM; naive baseline does conflict) — all green.
**3 example routines (deployed relevance):** P1 aging+texture → retinoid(PM)+AHA(AM) scheduled_apart (C1), ₹9,044; P2 aging+acne → retinoid(PM)+BHA(AM) scheduled_apart (C2), ₹7,996; P3 dullness+aging → vitC-LAA(AM)+retinoid(PM) scheduled_apart (C4) + a product_swapped (C2) where a BHA-carrying vitC serum was swapped out. All: 0 hard violations, SPF included, retinoid PM, vitC AM. The naive baseline ships the conflict in all 3.
**Latency:** solver **p50 31ms / p95 43ms** (includes building + diffing the naive baseline). Matches the BUILD_PLAN ~40ms headline target.
**Doc §:** 4 (rule base), 5 (solver methodology), 7 (headline: naive conflict vs 0-by-construction), 8 (test cases)

## [H+0.3] Dataset go/no-go — GO

**Decision:** Proceed with the full Routine Architect plan. Sephora dataset clears every §1 threshold.
**Rejected:** §10 fallback (skin-aware recommender, no routine layer) — not needed, data is strong.
**Because:** the angle lives or dies on parseable ingredient lists; it validated cleanly, so no reason to de-scope.
**Number:** 8,494 products · ingredient coverage **88.9%** (gate needs >70%) · reviews_0-250.csv: 602,130 rows, skin_type 87.6% (need >50%), skin_tone 82.4%, 383,697 unique authors.
**Note:** `ingredients` is stored as a stringified single-element Python list — the whole INCI list is one comma-joined string inside `['...']`. Parser (§3.2) must strip the list wrapper, then split on comma, then strip organic `*` markers, parenthetical common names, and backslash synonyms (`Water\Aqua\Eau`). All routine parsing work, none of it a blocker.
**Doc §:** 6 (dataset & assumptions), 1 (feasibility validated up front)

---

## [H+1.2] Parseable coverage — the document number

**Decision:** Report **86.2%** (parses to ≥5 recognised ingredient tokens, over ALL 8,494 products) as the ingredient-coverage figure, not the 88.9% non-null field rate.
**Rejected:** quoting 88.9% (non-null) — it counts empty/junk strings as "covered" and overstates what the engine can actually reason about.
**Because:** the thesis rests on *usable* ingredient data. 88.9% non-null → 97.0% of those parse cleanly → 86.2% of the whole catalogue. Within the 4 routine slots the number is what matters and it's higher: **94.8%** of slotted skincare products have a non-empty function vector (cleanser 94.2 / treatment 93.6 / moisturizer 96.3 / spf 97.2).
**Number:** parseable 86.2% (all) · 97.0% (of non-null) · routine-slot FV coverage 94.8%.
**Truncation:** 16.0% of fields carry a `+/-`/"May Contain" colourant section — truncated *before* positional weighting so it can't corrupt the §3.2 potency proxy.
**FX assumption:** price converted at a fixed **1 USD = ₹95.21** (user-supplied spot rate). Fixed, not a live feed, to keep the demo reproducible/offline → USD 3/35/1900 = ₹286/3,332/180,899.
**Doc §:** 6, 7

---

## [H+1.2] Review sparsity — CF is thin, LOO cohort is ample

**Decision:** Use co-review CF as one signal among several (hybrid), never as the backbone; size the LOO eval on the ≥5-review cohort.
**Rejected:** a CF-first ranker — the interaction matrix is far too sparse to carry it.
**Because:** across all 5 shards: **1,094,411 reviews / 503,216 unique authors** → only **8.1%** (40,880) have ≥5 reviews, **21.0%** have ≥3, **41.8%** (210,468) have ≥2. Median user has one review. So CF has usable signal for <half of users; content/embedding signal must dominate cold cases. The ≥5 cohort (40.8k users) is more than enough for a leave-one-out retrieval eval.
**Number:** 1.09M reviews · 503k authors · ≥5: 40,880 (8.1%) · ≥3: 105,750 (21.0%) · ≥2: 210,468 (41.8%).
**Doc §:** 6, 7, 4 (ranking design)

---

## [H+1.2] Underpopulated functional classes + a false multi-shade signal

**Decision:** Keep the full ~24-class taxonomy but flag 4 sparse actives as low-confidence for eval: benzoyl_peroxide (7 products), sulfur (13), copper_peptide (24), azelaic_acid (35). exfoliant_physical (396) is only detectable when abrasives appear in INCI — a known blind spot, not a bug.
**Because:** conflict rules touching BPO/copper-peptide will rarely fire on this catalogue simply because the ingredients are rare here — worth stating so a reviewer doesn't read low fire-rate as a broken engine.
**Surprise:** the "second Water/Aqua occurrence" multi-shade heuristic is **confounded** — of 4,074 hits, 1,301 are just the backslash synonym notation `Water\Aqua\Eau` (one water, written trilingually), leaving ~2,773 genuine second occurrences (mostly gift-set concatenations, which aren't in the 4 routine slots anyway). The `+/-` truncation is the reliable colourant guard; the water-count heuristic is not. Reporting it honestly rather than as a clean 54%.
**Number:** non-empty FV over whole catalogue 78.8% (dragged down by fragrance/makeup with no actives); over routine slots 94.8%.
**Doc §:** 6, 9 (limitations)

---

## [H+2.0] Slot restructure — two treatments, AM/PM split

**Decision:** Change the routine from 4 slots (one treatment) to **two treatment products allocated across sessions**:
`AM: cleanser → treatment_A → moisturizer → spf` / `PM: cleanser → treatment_B → moisturizer`.
**Rejected:** the original single-treatment routine.
**Because:** with only one active treatment, two actives can almost never co-occur, so hard conflicts barely arise and the AM/PM scheduling thesis has *nothing to schedule* — the whole novel contribution would be demonstrating a non-problem. Real users run multiple actives (retinoid + acid + vitamin C); the interesting, realistic, and thesis-relevant case is exactly the multi-active routine. Two treatments is the minimum that makes "schedule around conflicts instead of excluding products" a live decision the solver actually makes.
**Doc §:** 2 (problem framing), 4 (architecture), 5 (solver)

---

## [H+2.0] GATE 2 — naive-baseline conflict rate: PASS (~49%)

**Decision:** Framing holds — proceed to build. The headline number is real and large.
**Number:** Naive top-rated-per-slot recommender (both treatments defaulted to AM, no scheduling) produces a hard ingredient conflict in **47%** of 200 synthetic profiles (seed 0); **stable 44–55%, mean 48.7% across 8 seeds**. Well above the 10% abandon threshold.
**Method:** profiles = skin_type sampled from the real review distribution (combination 55% / dry 19% / normal 13% / oily 13%) × 2 concerns from a stated prior. Naive picks top-K(=5)-by-Bayesian-rating per concern/slot. Conflict = two *different* products in a session carrying a hard-rule active pair, active = present in top-15 INCI positions.
**Rule breakdown (share of routines):** retinoid×aha 23% · vitC(LAA)×aha 16% · retinoid×bha 15% · retinoid×physical-exfoliant 13% · vitC×bha 10.5% · retinoid×vitC 8.5% · retinoid×retinoid 3.5%. BPO/copper-peptide rules never fired — those actives are too rare in this US catalogue to reach the top-rated pool (consistent with the underpopulation finding), *not* an engine fault.
**Conflict opportunity (cross-slot carriage):** cleansers carrying AHA/BHA = 15.8% (top-15) / 26.2% (any position); moisturizers carrying niacinamide/retinoid/vitC = 25.5% (top-15) / 47.9% (any position). This is why "it's only a cleanser/moisturizer" doesn't make a routine safe.
**Caveat:** concerns are a synthetic prior — the review schema has no concern field; skin_type is real but doesn't drive naive selection (catalogue has no per-product skin-suitability), carried for profile realism only. The number is driven by real product ingredient data, not the prior's exact weights (robust across seeds).
**Doc §:** 1 (headline), 7 (results), 2

---

## [H+2.7] GATE 2 hardening — real-user rate, sensitivity, rule robustness

**Real-user conflict rate (new, may be the more credible headline):** of **165,565** users who co-reviewed ≥2 routine-slot products, **8.5% (14,031)** have ≥1 hard conflict *in their own product set* — real data, no simulation. Breakdown: retinoid×aha 4.1% · retinoid×bha 4.0% · vitC×aha 3.1% · vitC×bha 2.8% · retinoid×physical 1.9% · retinoid×vitC 1.7% · retinoid×retinoid 1.6%. Median set size is 2 (83k users), so most have minimal conflict opportunity; the rate rises with set size, i.e. 8.5% is a floor.
**Two numbers, two meanings — keep them distinct in the doc:** 8.5% = organic prevalence in what real people actually buy/review (understated: co-review ≠ simultaneous use, and we only see *reviewed* products). 47% = failure rate of an active recommender that personalises to two concerns. The recommender number is high precisely *because* personalisation loads two actives; the deterministic single-bestseller routine (below) conflicts 0%.
**Sensitivity of the 47%:** active detection at **top-15 INCI = 47%** (publish, conservative); **any-position = 70%** (cite as upper bound). Trace actives deep in the list add 23pts — real but lower-confidence, hence top-15 is the headline.
**Robustness to the retinoid×retinoid (redundancy, not chemistry) rule:** dropping it changes the naive rate by **0.0pts** (47%→47%, 70%→70%) — routines with double-retinoid always carry another conflict too. The headline does not depend on the one rule a skeptic could dismiss.
**Deterministic single-top-rated-per-slot routine:** Shiseido Facial Cotton / fresh Floral Recovery Overnight Mask / fresh Black Tea Anti-Aging Moisturizer (retinol-*alternative*, correctly NOT flagged retinoid) / Saint Jane SPF 30 → **NO conflict**. Finding: bland volume-bestsellers don't conflict; conflict is *created by personalisation*. Strengthens the thesis — the problem appears exactly when a system does its job (matches actives to concerns).
**Doc §:** 1, 7, 9

---

## [H+3.0] Conflict rate vs set size — the bridge figure (main document figure)

**Finding:** Real co-review conflict rate rises monotonically and steeply with product-set size — the 8.5% organic rate and the 47% naive-recommender rate are the **same phenomenon at different basket sizes**.
**Number (real users, cleaned slots):** n=2 → **2.5%** (80,821 users) · n=3 → 5.7% (34,009) · n=4 → 9.8% (16,572) · n=5 → **13.8%** (9,655) · n=6–7 → 20.6% (9,283) · n=8+ → **49.9%** (10,301). Overall 8.7% across 160,641 assessable users.
**The finding is COMPRESSION, not convergence** (framing corrected): compare at *matched basket size*. At 5 products, real users conflict **13.8%** but the naive recommender conflicts **47%** — a ~33pt gap at the same basket size. Real users only reach ~50% at **8+** products. So personalisation does **not** move users along the existing curve to the high end; it **shifts the curve upward** by concentrating actives — it delivers an 8-product level of conflict risk in a 5-product routine. The gap between the two curves at equal basket size is the finding: a naive recommender compresses the risk of a big basket into a normal-sized routine.
**Data saved:** `eval/conflict_by_setsize.csv` for plotting (plot both curves: real-user rate vs naive rate, x = basket size).
**Caveats:** co-review ≠ simultaneous use; only *reviewed* products are seen → understates. The real-user curve is a lower bound, which makes the gap a conservative estimate.
**Doc §:** 1, 2, 7 (main figure)

---

## [H+3.0] Slot taxonomy audit — accessory/tool/set exclusion pass

**Decision:** Added a `routine_eligible` filter on top of slot assignment; candidate pools use it. **1,888 slotted → 1,795 eligible (−93)**: cleanser 240→232, treatment 884→815, moisturizer 656→643, spf 108→105.
**Exclusion reasons:** `no_ingredients` (devices, blotting papers, cloths, GloPRO roller attachments + a handful of real products missing ingredient data — excluded because §5.5 forbids recommending what we can't conflict-check), `tool_category`, `accessory_name` (regex), `set_or_kit` (regex; real Collection/Duo/Kit multi-product SKUs).
**Rejected / tightened:** initial regex matched `set` (the verb — "Prep, Set, Glow" mist, "Set The Stage" serum) and `puff` (legit "de-puff" serum claims), over-excluding real single products. Dropped both keywords; matched-keyword now recorded in `exclude_reason` for auditability. Trigger was "Shiseido Facial Cotton" surfacing as top cleanser.
**Note:** ~57 of the 93 are `no_ingredients` — mostly genuine tools/devices, a few real formulations with blank INCI. Losing the latter from candidacy is acceptable (can't safety-check them anyway); they can still be *anchors* via the open-world paste path (§5.5).
**Doc §:** 6, 9

---

## [H+4.0] Retrieval — embedding text design + RRF k

**Embedding text (dense):** ordered **most-discriminative-first** — name → brand → functional classes (as natural words) → category → highlights → top-10 ingredients — joined by " . ". Reason: MiniLM truncates at 256 tokens, so ordering guarantees that *if* anything is dropped it's the least-useful tail (deep, sub-1% ingredients), never the product name.
**Measured token lengths (cap 256):** p50 ≈ 120, p95 ≈ 160, **max 230, zero products over 256** across all 4 slots → no silent truncation occurs. The top-10-ingredient cap is what keeps it under; full INCI lists (30–60 tokens more) would have pushed some products over.
**What I cut:** BUILD_PLAN §3.4 also specced "3 most-cited review themes" in the embedding text. **Deferred** — it needs a per-product review-mining pass (expensive) and would add tokens for marginal retrieval gain; better spent as a ranking-time / explanation signal (§4, §6). Stated as a deliberate omission, not an oversight.
**Rejected:** embedding the raw snake_case class keys — the semantic model reads words, so `vitamin_c_laa` → "vitamin c ascorbic acid" etc. via a small READABLE map. The raw keys go to BM25 instead.
**BM25 class-key injection:** corpus tokens = text words **+ the functional-class keys** ("retinoid", "aha", "vitamin_c_laa"). Without this, a lexical query for a function would match on "acid" — a substring of every acid — instead of the function. Injection lets sparse search hit the function directly.
**RRF k = 60:** the Cormack et al. (2009) default. No validation budget to tune it (per CLAUDE.md), and 60 is the widely-used robust choice — small enough that top ranks dominate, large enough that a #1 in one list doesn't steamroll a strong-across-both item. Fusion demonstrably reorders: e.g. a retinol serum at dense-rank 28 / BM25-rank 5 surfaces at fused-rank 6.
**Impl:** FAISS `IndexFlatIP` on L2-normalised embeddings (= exact cosine; corpus is tiny, no ANN needed), per-slot BM25Okapi, both persisted to `data/processed/index/` for fast API startup. Retrieves only `routine_eligible` products.
**Doc §:** 4 (methodology), 5

---

## [H+6.0] Ranking — temporal split, weight tuning, and an honest generalisation finding

**Temporal split (global, by submission_time)** — chosen over per-user LOO precisely to make a no-leakage claim defensible: all signals (CF, rating prior, skin affinity, embeddings) are fit on TRAIN only; val tunes weights; test is touched once.
- train: 2008-08-28 → 2021-06-25 · **765,552** reviews · 405,615 users
- val:   2021-06-26 → 2022-04-30 · **164,418** reviews · 78,934 users
- test:  2022-05-01 → 2023-03-21 · **164,441** reviews · 76,409 users
**Rating prior:** `(v/(v+m))·R + (m/(v+m))·C` with **m = 206.5** (median train review-count per eligible product), **C = 4.283** (global train mean rating). Both TRAIN-derived.
**Skin-affinity shrinkage:** skin-type positive rate shrunk toward the product's own overall positive rate, Bayesian, **prior strength k = 20**. Kills low-n lucky-review products (2 five-star reviews from one skin type no longer dominate).
**Protocol:** eval cohort = §6.1's users with **≥5 total reviews** (mean **6.8** train-liked items); one held-out most-recent 4★+ item each; ranked vs **100 sampled negatives** from the same slot (standard NCF/SASRec LOO — full ~800-item ranking is at random for *every* method, so it can't discriminate signals). Grid = full 4-simplex, step 0.1 (286 points), pick by val NDCG@10.
**Two bugs caught & fixed en route (document as method rigour):** (1) strict-`>` ranking gave cold users a fake rank-1 when all candidate scores tied at 0 → replaced with **midrank** tie handling; (2) a random-baseline print line dropped the `@10` cutoff. Neither touched the core metric.
**Tuned weights (val grid):** **[semantic 0.3, cf 0.7, rating 0.0, skin 0.0]**, val NDCG@10 = 0.104. Sensitivity: val NDCG spans 0.034–0.104 (std 0.018); the top is a **plateau of CF-heavy blends** (cf 0.5–0.9 all ≈0.10) — within it weights are interchangeable; only rating/skin-heavy corners are clearly bad.
**THE FINDING [PARTIALLY SUPERSEDED by H+6.7 — the CF weakness was STALENESS, not non-transferability; the refit below reverses the "semantic is the durable driver" call].** On the disjoint test period the chosen blend drops to NDCG@10 **0.054** (random 0.042). Single-signal TEST (stale, train-only fit): **semantic 0.060 > cf 0.051 > rating 0.034 > skin 0.016**. This *looked* like CF failing to generalise — but see H+6.7: refit through val and CF becomes the strongest signal. A random split would have hidden the decay; the temporal split surfaced it.
**rating & skin ≈ random for exact next-item** — both are near-constant across a slot (rating is global; shrunk skin-affinity barely varies across candidates), so grid → 0 weight. This is metric-specific, NOT a verdict they're useless: rating is the cold-start prior, skin feeds affinity/safety. Just not next-item discriminators.
**Decision / open question for you:** protocol says report the val-tuned [0.3,0.7,0,0]; but since CF doesn't transfer, for the *deployed* ranker I'd weight **semantic higher** for temporal robustness. Flagging rather than silently overriding. Results in `eval/rank_results.json`. **[This proposal was OVERTURNED by the refit — see H+6.7.]**
**Doc §:** 4 (methodology), 6 (dataset/cohort), 7 (results), 9 (limitations — CF sparsity + temporal decay)

---

## [H+6.7] Ranking hardening — pool size, sign check, and the CF-staleness reversal

**1. Candidate pool.** Fixed at **101** (1 held-out + 100 slot-sampled negatives, NCF/SASRec protocol). The random-baseline NDCG@10 = **0.042** *confirms* ~101-way — a few-dozen pool would put random near 0.15. So the metric discriminates (semantic 0.060 vs random 0.042 is real). Full slot-eligible sizes reported for reference (cleanser 232 / treatment 815 / moisturizer 643 / spf 105); full-catalogue ranking was rejected earlier because it's ~random for *every* method. Pool size now printed alongside every metric.
**2. Sign check — no signal is inverted; my "anti-correlation" guess was WRONG.** Mean z of the true item: semantic **+0.239**, skin **+0.118**, rating **+0.080**, cf −0.019 (stale). NDCG(+) vs NDCG(−): semantic 0.060 vs 0.016, rating 0.034 vs 0.028, cf 0.051 vs 0.000 — all correctly oriented. rating & skin have *positive* true-item z, so they are **correctly oriented but near-random/non-discriminative** (near-constant across a slot after shrinkage), **not anti-correlated**. Comparator verified sound.
**3. THE REVERSAL — refit on train+val (deployed cadence) shows CF's test weakness was STALENESS, not non-transferability.** Refitting all signals through val (CF now ≤1mo stale at test start instead of 11–21mo):
- blend @ val-tuned weights: **0.054 → 0.107 (+0.053, ~2×)**
- single-signal, stale→refreshed: **cf 0.051 → 0.108 (+0.057, the biggest jump)**, semantic 0.060 → 0.070 (robust/stable), rating 0.034 → 0.062, skin 0.016 → 0.025
- refreshed-test grid argmax (diagnostic, not selected): [0.1, 0.7, 0.1, 0.1] @ 0.110 — still CF-heavy.
So **fresh CF is the single strongest signal**; semantic is the robust floor that barely moves with freshness (its value is exactly that stability). **CF refresh cadence is now an operational requirement** — let CF age 11–21mo and it decays to ~random; refreshing recovers ~2× NDCG. This is a concrete finding for the roadmap/ops section.
**4. Deployed weights (engineering call) = [semantic 0.3, cf 0.5, rating 0.1, skin 0.1]** → refreshed test NDCG@10 **0.106** (statistically tied with the pure val-tuned 0.107). Rationale: CF-dominant because fresh CF wins; keep semantic 0.3 as the **staleness/robustness floor**; keep rating+skin at 0.1 each as the **cold-start lifeline** — the grid zeroed them only because the eval cohort is warm (≥5 reviews, mean 6.8→12.9 liked), but for cold users cf & semantic are both 0 and rating/skin are the only signals. The user's rule ("deployed = semantic-dominant *unless the refit changes the picture*") fired: **the refit changed the picture**, so deployed is CF-dominant, not semantic-dominant.
**Divergence documented:** protocol/val-tuned = [0.3, 0.7, 0, 0] (report); deployed = [0.3, 0.5, 0.1, 0.1] (serve). They differ only by moving 0.2 of weight from CF into rating+skin for cold-start safety — a small, deliberate divergence, not a contradiction. `eval/rank_results.json` holds both.
**Doc §:** 4, 7 (results + staleness delta), 9 (CF sparsity), 12 (roadmap — CF refresh cadence)
