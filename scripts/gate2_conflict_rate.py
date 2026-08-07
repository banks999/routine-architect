"""GATE 2 (throwaway) — headline conflict rate of a NAIVE recommender, measured
before building the solver. If this is <10% the whole framing is wrong.

Naive baseline = what Nykaa/Amazon-style ranking does: for each of the user's
concerns, surface the top-rated matching treatment; fill cleanser/moisturizer/spf
with top-rated products in-category; schedule NOTHING (both treatments default to
AM, as an unscheduled system would). We then count how many routines contain >=1
HARD ingredient conflict within the AM session.

No retrieval, no solver. Conflict = two DIFFERENT products in the session carrying
a hard-conflicting pair of active classes (active = present within the first 15
INCI positions, the reliable "meaningful dose" region).
"""
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.ingredients import present_classes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
df = pd.read_parquet(ROOT / "data" / "processed" / "products_enriched.parquet")

RNG = np.random.default_rng(0)
N_PROFILES = 200
TOP_K = 5          # naive system surfaces top-K by rating; user picks one
MAX_POS = 15       # "meaningful dose" cutoff for an active to count

# HARD conflicts only (BUILD_PLAN §4 rows 1-10). Soft/contested excluded.
HARD = [
    ("retinoid", "aha"), ("retinoid", "bha"), ("retinoid", "benzoyl_peroxide"),
    ("retinoid", "vitamin_c_laa"), ("retinoid", "exfoliant_physical"),
    ("retinoid", "retinoid"),
    ("vitamin_c_laa", "aha"), ("vitamin_c_laa", "bha"),
    ("vitamin_c_laa", "copper_peptide"), ("copper_peptide", "aha"),
]

# concern -> treatment active classes it would be marketed for
CONCERNS = {
    "acne":       ["bha", "benzoyl_peroxide", "sulfur", "azelaic_acid"],
    "aging":      ["retinoid", "peptide"],
    "dark_spots": ["vitamin_c_laa", "vitamin_c_derivative", "brightening_other", "azelaic_acid"],
    "texture":    ["aha", "bha", "pha"],
    "dullness":   ["vitamin_c_laa", "vitamin_c_derivative", "aha"],
    "redness":    ["azelaic_acid", "soothing"],
}
# rough real-world concern popularity (skincare); not in the review schema, so a
# stated prior — flagged in DECISIONS as a synthetic assumption.
CONCERN_P = np.array([0.22, 0.20, 0.20, 0.15, 0.15, 0.08])
CONCERN_NAMES = list(CONCERNS)
# skin_type sampled from the REAL review distribution (measured, one shard)
SKIN = {"combination": 0.554, "dry": 0.189, "normal": 0.132, "oily": 0.125}


def bayesian_rating(sub: pd.DataFrame, m: float, C: float) -> pd.Series:
    v = sub["reviews"].fillna(0)
    R = sub["rating"].fillna(C)
    return (v / (v + m)) * R + (m / (v + m)) * C


# ---- precompute presence sets (active in top-15) once per product ----
df = df.copy()
df["pres"] = df["ingredients"].map(lambda x: present_classes(x, max_pos=MAX_POS) if isinstance(x, str) else set())
C = df["rating"].mean()
m = df["reviews"].median()
df["bayes"] = bayesian_rating(df, m, C)


def top_pool(mask: pd.Series) -> pd.DataFrame:
    return df[mask].nlargest(TOP_K, "bayes")


# per-slot / per-concern candidate pools (top-K by Bayesian rating)
POOLS = {
    "cleanser":   top_pool(df["slot"] == "cleanser"),
    "moisturizer": top_pool(df["slot"] == "moisturizer"),
    "spf":        top_pool(df["slot"] == "spf"),
}
CONCERN_POOL = {}
for c, cls in CONCERNS.items():
    mask = (df["slot"] == "treatment") & df["pres"].map(lambda p: bool(p & set(cls)))
    CONCERN_POOL[c] = top_pool(mask)


def pick(pool: pd.DataFrame):
    return pool.iloc[RNG.integers(len(pool))]


def session_conflicts(products: list) -> set:
    """Hard rules violated by >=2 distinct products in the session."""
    fired = set()
    for a, b in HARD:
        pa = [i for i, p in enumerate(products) if a in p["pres"]]
        pb = [i for i, p in enumerate(products) if b in p["pres"]]
        # need two DIFFERENT products, one carrying a, one carrying b
        if any(i != j for i in pa for j in pb):
            fired.add((a, b))
    return fired


def main() -> None:
    n_conflicted = 0
    rule_fires: Counter = Counter()
    skin_counter: Counter = Counter()
    for _ in range(N_PROFILES):
        skin = RNG.choice(list(SKIN), p=list(SKIN.values()))
        skin_counter[skin] += 1
        cA, cB = RNG.choice(len(CONCERN_NAMES), size=2, replace=False, p=CONCERN_P)
        tA = pick(CONCERN_POOL[CONCERN_NAMES[cA]])
        tB = pick(CONCERN_POOL[CONCERN_NAMES[cB]])
        # naive AM session: everything, both treatments, no scheduling
        am = [pick(POOLS["cleanser"]), tA, tB, pick(POOLS["moisturizer"]), pick(POOLS["spf"])]
        fired = session_conflicts([{"pres": p["pres"]} for p in am])
        if fired:
            n_conflicted += 1
            rule_fires.update(fired)

    rate = n_conflicted / N_PROFILES
    print("=" * 64)
    print(f"NAIVE ROUTINE HARD-CONFLICT RATE : {rate:.1%}  ({n_conflicted}/{N_PROFILES})")
    print("=" * 64)
    print(f"(profiles={N_PROFILES}, top-K pick={TOP_K}, active cutoff=top-{MAX_POS} INCI, seed=0)")
    print("\nWhich hard rules fired (share of all routines):")
    for (a, b), n in rule_fires.most_common():
        print(f"  {a:16s} x {b:18s}: {n:3d}  ({n/N_PROFILES:.1%})")
    print("\nprofile skin-type mix (sampled from real review dist):")
    for k in SKIN:
        print(f"  {k:12s}: {skin_counter[k]}")

    # ---- cross-slot active carriage (the conflict opportunity) ----
    print("\n" + "=" * 64)
    print("CROSS-SLOT ACTIVE CARRIAGE (why conflicts are possible at all)")
    print("=" * 64)
    for cutoff, label in ((MAX_POS, f"top-{MAX_POS}"), (None, "any position")):
        cl = df[df["slot"] == "cleanser"]["ingredients"].map(lambda x: present_classes(x, cutoff))
        cl_ab = cl.map(lambda p: bool(p & {"aha", "bha"})).mean()
        mo = df[df["slot"] == "moisturizer"]["ingredients"].map(lambda x: present_classes(x, cutoff))
        mo_act = mo.map(lambda p: bool(p & {"niacinamide", "retinoid", "vitamin_c_laa", "vitamin_c_derivative"})).mean()
        print(f"  [{label:12s}] cleansers carrying AHA/BHA            : {cl_ab:.1%}")
        print(f"  [{label:12s}] moisturizers carrying niac/retinoid/VitC: {mo_act:.1%}")


if __name__ == "__main__":
    main()
