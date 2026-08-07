"""GATE 2 hardening — four data-layer measurements to firm up the headline.
No retrieval. Reuses gate2's pools/logic.

1. Real-user conflict rate (co-reviewed routine-slot product sets)
2. Sensitivity: naive rate at top-15 vs any-INCI-position active detection
3. Naive rate with vs without the retinoid x retinoid (redundancy) rule
4. Single top-rated-per-slot routine: does it conflict, on which rule, which products
"""
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scripts.gate2_conflict_rate as g  # module-level pools already built  # noqa: E402
from app.core.ingredients import present_classes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
df = g.df  # has: product_id, slot, ingredients, pres(top15), bayes, product_name, brand_name
HARD = g.HARD
HARD_NO_RR = [r for r in HARD if r != ("retinoid", "retinoid")]

# any-position presence per product (top-15 already on df['pres'])
df["pres_any"] = df["ingredients"].map(lambda x: present_classes(x, None) if isinstance(x, str) else set())
# presence lookups by id — pool rows were built before pres_any existed, so go by id
PRES15 = dict(zip(df["product_id"], df["pres"]))
PRESANY = dict(zip(df["product_id"], df["pres_any"]))


def conflicts(pres_list, rules):
    """Rules violated by two DIFFERENT products in the set."""
    fired = set()
    for a, b in rules:
        pa = [i for i, s in enumerate(pres_list) if a in s]
        pb = [i for i, s in enumerate(pres_list) if b in s]
        if any(i != j for i in pa for j in pb):
            fired.add((a, b))
    return fired


# ============================================================
# 1. REAL-USER CONFLICT RATE
# ============================================================
def real_users():
    slot_df = df[df["slot"].notna()]
    pres15 = dict(zip(slot_df["product_id"], slot_df["pres"]))
    slot_ids = set(pres15)

    user_prods = defaultdict(set)
    for f in sorted((ROOT / "data" / "raw").glob("reviews_*.csv")):
        for ch in pd.read_csv(f, usecols=["author_id", "product_id"], chunksize=200_000):
            ch = ch[ch["product_id"].isin(slot_ids)].dropna(subset=["author_id"])
            for a, p in zip(ch["author_id"].astype(str), ch["product_id"]):
                user_prods[a].add(p)

    # only users who reviewed >=2 DIFFERENT routine-slot products can conflict
    assessable = {u: ps for u, ps in user_prods.items() if len(ps) >= 2}
    n_conf = 0
    fires = Counter()
    sizes = []
    for ps in assessable.values():
        sizes.append(len(ps))
        pres_list = [pres15[p] for p in ps]
        fired = conflicts(pres_list, HARD)
        if fired:
            n_conf += 1
            fires.update(fired)

    n = len(assessable)
    sizes = np.array(sizes)
    print("=" * 64)
    print("1. REAL-USER CONFLICT RATE (co-reviewed routine-slot products)")
    print("=" * 64)
    print(f"users with >=1 routine-slot review : {len(user_prods):,}")
    print(f"users with >=2 (assessable)        : {n:,}")
    print(f"  -> contain >=1 hard conflict     : {n_conf:,}  ({n_conf/n:.1%})")
    print(f"set size  min/median/mean/max      : {sizes.min()}/{int(np.median(sizes))}/{sizes.mean():.1f}/{sizes.max()}")
    for lo, hi in [(2, 2), (3, 4), (5, 9), (10, 10**9)]:
        c = int(((sizes >= lo) & (sizes <= hi)).sum())
        lbl = f"{lo}" if lo == hi else (f">={lo}" if hi > 10**8 else f"{lo}-{hi}")
        print(f"    size {lbl:5s}: {c:,} users")
    print("  rule breakdown (share of assessable users):")
    for (a, b), c in fires.most_common():
        print(f"    {a:14s} x {b:16s}: {c:,}  ({c/n:.1%})")


# ============================================================
# 2-3. NAIVE SIM — regenerate the same 200 routines (seed 0), score 4 ways
# ============================================================
def naive_variants():
    g.RNG = np.random.default_rng(0)
    routines = []  # each: list of product rows
    for _ in range(g.N_PROFILES):
        _skin = g.RNG.choice(list(g.SKIN), p=list(g.SKIN.values()))  # keep RNG stream identical to gate2
        cA, cB = g.RNG.choice(len(g.CONCERN_NAMES), size=2, replace=False, p=g.CONCERN_P)
        tA = g.pick(g.CONCERN_POOL[g.CONCERN_NAMES[cA]])
        tB = g.pick(g.CONCERN_POOL[g.CONCERN_NAMES[cB]])
        am = [g.pick(g.POOLS["cleanser"]), tA, tB, g.pick(g.POOLS["moisturizer"]), g.pick(g.POOLS["spf"])]
        routines.append(am)

    def rate(lookup, rules):
        n = sum(1 for am in routines if conflicts([lookup[p["product_id"]] for p in am], rules))
        return n / len(routines)

    print("\n" + "=" * 64)
    print("2-3. NAIVE-BASELINE SENSITIVITY (same 200 routines, seed 0)")
    print("=" * 64)
    print(f"{'detection':<16}{'with retinoidxretinoid':>26}{'without':>12}")
    for lookup, lbl in ((PRES15, "top-15 (conservative)"), (PRESANY, "any position")):
        print(f"{lbl:<16}{rate(lookup, HARD):>25.1%}{rate(lookup, HARD_NO_RR):>12.1%}")
    print("\npublish: top-15 with-rule = conservative headline; any-position = cited upper bound.")


# ============================================================
# 4. SINGLE TOP-RATED PER SLOT (deterministic, no simulation)
# ============================================================
def single_topk():
    print("\n" + "=" * 64)
    print("4. SINGLE TOP-RATED-PER-SLOT ROUTINE (deterministic)")
    print("=" * 64)
    routine = []
    for slot in ("cleanser", "treatment", "moisturizer", "spf"):
        top = df[df["slot"] == slot].nlargest(1, "bayes").iloc[0]
        routine.append(top)
        print(f"  {slot:12s}: {top['brand_name']} — {top['product_name']}")
        print(f"               actives(top-15): {sorted(top['pres']) or '—'}")
    fired = conflicts([PRES15[p["product_id"]] for p in routine], HARD)
    fired_any = conflicts([PRESANY[p["product_id"]] for p in routine], HARD)
    print(f"\n  hard conflict (top-15)     : {sorted(fired) or 'NONE'}")
    print(f"  hard conflict (any position): {sorted(fired_any) or 'NONE'}")


if __name__ == "__main__":
    real_users()
    naive_variants()
    single_topk()
