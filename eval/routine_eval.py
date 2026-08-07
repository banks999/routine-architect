"""BUILD_PLAN §6.3 routine-level eval (THE HEADLINE): naive vs solver, on synthetic
profiles, under BOTH conflict-detection definitions (top-15 and any-position).

    python eval/routine_eval.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.core import retrieval as ret  # noqa: E402
from app.core import solver as sv  # noqa: E402
from app.core import conflicts as cf  # noqa: E402
from app.core.ingredients import present_classes  # noqa: E402

RNG = np.random.default_rng(0)
N = 200
prod = pd.read_parquet(ROOT / "data" / "processed" / "products_enriched.parquet")
priors = pd.read_parquet(ROOT / "data" / "processed" / "rank_priors.parquet").set_index("product_id")
_e = np.load(ROOT / "data" / "processed" / "emb_all.npz", allow_pickle=True)
EMB = dict(zip(_e["ids"], _e["emb"]))
META = {r.product_id: r for r in prod.itertuples()}
CL15 = {p: present_classes(i, 15) for p, i in zip(prod["product_id"], prod["ingredients"]) if isinstance(i, str)}
CLANY = {p: present_classes(i, None) for p, i in zip(prod["product_id"], prod["ingredients"]) if isinstance(i, str)}

CONCERN_QUERY = {
    "aging": "retinol anti-aging serum for wrinkles", "texture": "glycolic acid AHA exfoliating serum",
    "acne": "salicylic acid BHA serum for acne", "dark_spots": "vitamin c serum for dark spots",
    "dullness": "vitamin c brightening serum", "redness": "azelaic acid serum for redness",
    "dryness": "hyaluronic acid hydrating serum",
}
BASE_Q = {"cleanser": "gentle cleanser", "moisturizer": "hydrating moisturizer", "spf": "sunscreen spf"}
CONCERNS = list(CONCERN_QUERY)
CP = np.array([0.20, 0.16, 0.16, 0.16, 0.14, 0.10, 0.08])
SKINS, SKP = ["combination", "dry", "normal", "oily"], [0.554, 0.189, 0.132, 0.125]


def _z(a):
    a = np.asarray(a, "float32")
    return (a - a.mean()) / a.std() if a.std() > 1e-9 else np.zeros_like(a)


def _pool(q, slot):
    model = ret.get_model()
    ids = [h["product_id"] for h in ret.retrieve(q, slot, top_k=30) if h["product_id"] in EMB and h["product_id"] in priors.index]
    qv = model.encode([q], normalize_embeddings=True)[0]
    return ids, np.array([float(qv @ EMB[i]) for i in ids]), np.array([priors.at[i, "bayes"] for i in ids])


print("precomputing candidate pools...")
TREAT = {c: _pool(CONCERN_QUERY[c], "treatment") for c in CONCERN_QUERY}
BASE = {s: _pool(BASE_Q[s], s) for s in BASE_Q}


def _cands(pool, skin, slot, classes):
    ids, sem, rat = pool
    ski = np.array([priors.at[i, f"aff_{skin}"] for i in ids])
    rel = 0.3 * _z(sem) + 0.1 * _z(rat) + 0.1 * _z(ski)
    # SHIPPED-engine parity: cleansers are rinse-off -> no conflict-relevant classes.
    out = [sv.Candidate(i, f"{META[i].brand_name} — {META[i].product_name}",
                        float(META[i].price_inr) if pd.notna(META[i].price_inr) else 1e9,
                        frozenset() if slot == "cleanser" else frozenset(classes.get(i, set())),
                        {}, float(r), slot) for i, r in zip(ids, rel)]
    return sorted(out, key=lambda c: c.relevance, reverse=True)


def build(profile, classes):
    c1, c2 = profile.concerns[0], profile.concerns[-1]
    return {"cleanser": _cands(BASE["cleanser"], profile.skin, "cleanser", classes),
            "moisturizer": _cands(BASE["moisturizer"], profile.skin, "moisturizer", classes),
            "spf": _cands(BASE["spf"], profile.skin, "spf", classes),
            "treatment_A": _cands(TREAT[c1], profile.skin, "treatment_A", classes),
            "treatment_B": _cands(TREAT[c2], profile.skin, "treatment_B", classes)}


def gen_profiles():
    out = []
    for _ in range(N):
        cs = [CONCERNS[i] for i in RNG.choice(len(CONCERNS), 2, replace=False, p=CP)]
        skin = RNG.choice(SKINS, p=SKP)
        budget = float(RNG.choice([5000, 7000, 9000, 12000, 15000], p=[0.15, 0.2, 0.2, 0.3, 0.15]))
        out.append(sv.Profile(concerns=cs, budget=budget, skin=skin))
    return out


def metrics(r, profile):
    hard = r.hard_violations
    n_conf = sum(1 for v in hard if v.kind == "conflict")
    n_place = sum(1 for v in hard if v.kind == "placement")
    n_spf = sum(1 for v in hard if v.kind == "spf")
    return dict(safe=n_conf == 0, coverage=sv._covered(r.placements, profile.concerns),
                redundancy=sv._redundancy(r.placements),
                within_budget=r.total_price <= profile.budget * 1.15,
                placement_ok=n_place == 0, spf_ok=n_spf == 0,
                relevance=sum(pl.cand.relevance for pl in r.placements))


def run(profiles, classes):
    agg = {"naive": [], "greedy": [], "solver": []}
    for p in profiles:
        cands = build(p, classes)
        agg["naive"].append(metrics(sv.naive_greedy(cands, p), p))
        agg["greedy"].append(metrics(sv.budget_greedy(cands, p), p))
        agg["solver"].append(metrics(sv.solve(cands, p), p))
    def summ(rows):
        return dict(safety_rate=np.mean([r["safe"] for r in rows]),
                    coverage=np.mean([r["coverage"] for r in rows]),
                    redundancy=np.mean([r["redundancy"] for r in rows]),
                    budget_adherence=np.mean([r["within_budget"] for r in rows]),
                    placement_compliance=np.mean([r["placement_ok"] for r in rows]),
                    spf_compliance=np.mean([r["spf_ok"] for r in rows]),
                    relevance=np.mean([r["relevance"] for r in rows]))
    return {k: summ(v) for k, v in agg.items()}


if __name__ == "__main__":
    profiles = gen_profiles()
    t0 = time.perf_counter()
    res = {"top15": run(profiles, CL15), "any_position": run(profiles, CLANY)}
    dt = time.perf_counter() - t0

    print("\n" + "=" * 78)
    print(f"ROUTINE-LEVEL EVAL — {N} synthetic profiles, naive vs solver ({dt:.0f}s)")
    print("=" * 78)
    for det in ("top15", "any_position"):
        print(f"\n--- conflict detection: {det} ---")
        print(f"{'metric':22} {'naive':>12} {'budget-greedy':>15} {'solver':>10}")
        for m in ("safety_rate", "coverage", "redundancy", "budget_adherence",
                  "placement_compliance", "spf_compliance", "relevance"):
            row = res[det]
            fmt = (lambda x: f"{x:.3f}") if m in ("redundancy", "relevance") else (lambda x: f"{x:.1%}")
            print(f"{m:22} {fmt(row['naive'][m]):>12} {fmt(row['greedy'][m]):>15} {fmt(row['solver'][m]):>10}")

    json.dump(res, open(ROOT / "eval" / "results.json", "w"), indent=2, default=float)
    print("\nwrote eval/results.json")
