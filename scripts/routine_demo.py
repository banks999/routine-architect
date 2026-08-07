"""3 example routines end-to-end: retrieval -> deployed-weight relevance -> solver,
with the avoided-conflict detail and solver latency.

    python scripts/routine_demo.py
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.core import retrieval as ret  # noqa: E402
from app.core import solver as sv  # noqa: E402
from app.core.ingredients import present_classes  # noqa: E402

DEPLOYED = {"semantic": 0.3, "cf": 0.5, "rating": 0.1, "skin": 0.1}  # cf=0 for cold users

import json  # noqa: E402

prod = pd.read_parquet(ROOT / "data" / "processed" / "products_enriched.parquet")
priors = pd.read_parquet(ROOT / "data" / "processed" / "rank_priors.parquet").set_index("product_id")
_emb = np.load(ROOT / "data" / "processed" / "emb_all.npz", allow_pickle=True)
EMB = dict(zip(_emb["ids"], _emb["emb"]))
META = {r.product_id: r for r in prod.itertuples()}

# SAFETY-side conflict detection: use ANY-position presence, not the top-15 "meaningful
# dose" cutoff used for the conservative headline stat. For a live safety layer a false
# positive (an unnecessary AM/PM split) is cheap; a false negative ships an irritating
# routine. So a "Retinol Serum" with retinol listed deep still counts as a retinoid.
CLASSES = {pid: present_classes(ing, None) for pid, ing in zip(prod["product_id"], prod["ingredients"])
           if isinstance(ing, str)}


def _z(a):
    a = np.array(a, "float32")
    return (a - a.mean()) / a.std() if a.std() > 1e-9 else np.zeros_like(a)


# concern -> a query that surfaces that concern's active (so each treatment slot is
# concern-specific, mirroring how a real recommender picks one product per concern —
# which is exactly what creates cross-active conflicts).
CONCERN_QUERY = {
    "aging": "retinol anti-aging serum for wrinkles and fine lines",
    "texture": "glycolic acid AHA exfoliating serum for uneven texture",
    "acne": "salicylic acid BHA serum for acne and breakouts",
    "dark_spots": "vitamin c serum for dark spots and hyperpigmentation",
    "dullness": "vitamin c brightening serum for dull skin",
    "redness": "azelaic acid serum for redness and sensitivity",
    "dryness": "hyaluronic acid hydrating serum for dry skin",
}


def _score_pool(q: str, slot: str, skin_col: str, model) -> list:
    qv = model.encode([q], normalize_embeddings=True)[0]
    ids = [h["product_id"] for h in ret.retrieve(q, "treatment" if slot.startswith("treatment") else slot, top_k=30)
           if h["product_id"] in EMB and h["product_id"] in priors.index]
    sem = [float(qv @ EMB[i]) for i in ids]
    rat = [priors.at[i, "bayes"] for i in ids]
    ski = [priors.at[i, skin_col] if skin_col in priors.columns else priors.at[i, "posrate"] for i in ids]
    rel = DEPLOYED["semantic"] * _z(sem) + DEPLOYED["rating"] * _z(rat) + DEPLOYED["skin"] * _z(ski)
    cands = []
    for i, rv in zip(ids, rel):
        r = META[i]
        price = float(r.price_inr) if pd.notna(r.price_inr) else 1e9
        cands.append(sv.Candidate(i, f"{r.brand_name} — {r.product_name}", price,
                                  frozenset(CLASSES.get(i, set())), json.loads(r.function_vector),
                                  float(rv), slot))
    return sorted(cands, key=lambda c: c.relevance, reverse=True)


def build_candidates(profile: sv.Profile) -> dict:
    model = ret.get_model()
    skin_col = f"aff_{profile.skin}" if profile.skin else "posrate"
    out = {
        "cleanser": _score_pool(f"gentle cleanser for {profile.skin} skin", "cleanser", skin_col, model),
        "moisturizer": _score_pool(f"hydrating moisturizer for {profile.skin} skin", "moisturizer", skin_col, model),
        "spf": _score_pool("sunscreen spf broad spectrum", "spf", skin_col, model),
    }
    c1, c2 = profile.concerns[0], profile.concerns[-1]
    out["treatment_A"] = _score_pool(CONCERN_QUERY[c1], "treatment_A", skin_col, model)
    out["treatment_B"] = _score_pool(CONCERN_QUERY[c2], "treatment_B", skin_col, model)
    return out


def show(routine: sv.Routine, naive: sv.Routine):
    def line(pl):
        cl = ",".join(sorted(pl.cand.classes & sv._active_classes())) or "—"
        return f"      {pl.slot:12} ₹{pl.cand.price:>6.0f}  [{cl:22.22}] {pl.cand.name[:52]}"
    print("  AM:")
    for pl in sorted(routine.session("AM"), key=lambda p: sv.SLOT_ORDER.index(p.slot)):
        print(line(pl))
    print("  PM:")
    for pl in sorted(routine.session("PM"), key=lambda p: sv.SLOT_ORDER.index(p.slot)):
        print(line(pl))
    print(f"  price ₹{routine.total_price:.0f}   score {routine.score:.2f}   "
          f"hard-violations {len(routine.hard_violations)}")
    print("  avoided (what the solver DID about each conflict a naive picker would ship):")
    if not routine.avoided:
        print("      (none — naive picks did not conflict for this profile)")
    for a in routine.avoided:
        print(f"      [{a.action}] {a.rule_id} {a.class_a}×{a.class_b}")
        print(f"          {a.mechanism}")
        print(f"          {a.product_a.split('::')[1]}  |  {a.product_b.split('::')[1]}")
    if routine.cautions:
        print("  cautions (surfaced, not blocked):")
        for c in {(v.rule_id, v.mechanism) for v in routine.cautions}:
            print(f"      {c[0]}: {c[1][:90]}")
    for n in routine.notes:
        print(f"  note: {n}")
    nh = [v for v in naive.hard_violations if v.kind == "conflict"]
    print(f"  NAIVE baseline (same interface): {len(nh)} hard conflict(s) shipped "
          f"[{', '.join(sorted({v.rule_id for v in nh})) or 'none'}]")


PROFILES = [
    sv.Profile(concerns=["aging", "texture"], budget=9000, skin="combination"),   # retinoid x aha
    sv.Profile(concerns=["aging", "acne"], budget=7000, skin="oily"),             # retinoid x bha
    sv.Profile(concerns=["dullness", "aging"], budget=12000, skin="dry"),         # vitamin C x retinoid
]

if __name__ == "__main__":
    for i, p in enumerate(PROFILES, 1):
        cands = build_candidates(p)
        r = sv.solve(cands, p)
        n = sv.naive_greedy(cands, p)
        print("\n" + "=" * 92)
        print(f"PROFILE {i}: concerns={p.concerns}  skin={p.skin}  budget=₹{p.budget:.0f}")
        print("=" * 92)
        show(r, n)

    # latency on the last profile's candidate set
    lat = []
    for _ in range(100):
        t = time.perf_counter()
        sv.solve(cands, PROFILES[-1])
        lat.append((time.perf_counter() - t) * 1000)
    lat = np.array(lat)
    print(f"\nsolver latency (100 runs): p50={np.percentile(lat,50):.1f}ms  "
          f"p95={np.percentile(lat,95):.1f}ms  (includes the naive-baseline diff)")
