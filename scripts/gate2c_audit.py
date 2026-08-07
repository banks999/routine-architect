"""Slot-taxonomy audit + conflict-rate-vs-set-size curve. Last analysis detour.

1. Exclude non-formulations from routine slots (accessories/tools/sets, and any
   product with no ingredient list — we can't conflict-check what we can't read,
   §5.5). Writes routine_eligible/exclude_reason back to the enriched parquet.
2. Real co-review conflict rate conditioned on product-set size -> eval/ for plotting.
   This is meant to bridge the 8.5% organic rate and the 47% naive-recommender rate:
   same phenomenon, different basket sizes.
"""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.ingredients import present_classes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PARQUET = ROOT / "data" / "processed" / "products_enriched.parquet"
EVAL = ROOT / "eval"

# accessories/tools and multi-product sets — not a single leave-on/rinse formulation.
# Deliberately NOT matching: "puff" (catches legit "de-puff" claims), "set"/"value"
# (catch the verb: "Set The Stage", "Prep, Set, Glow") — those over-exclude serums.
ACCESSORY_RE = re.compile(r"\b(cotton|sponge|brush(?:es)?|roller|device|cloth|towel|"
                          r"mitt|applicator|spatula|headband|tweezer|tool)\b", re.I)
SET_RE = re.compile(r"\b(kit|duo|trio|bundle|collection)\b", re.I)
TOOL_CATS = {"Facial Rollers", "Facial Cleansing Brushes", "High Tech Tools", "Tools"}

HARD = [
    ("retinoid", "aha"), ("retinoid", "bha"), ("retinoid", "benzoyl_peroxide"),
    ("retinoid", "vitamin_c_laa"), ("retinoid", "exfoliant_physical"), ("retinoid", "retinoid"),
    ("vitamin_c_laa", "aha"), ("vitamin_c_laa", "bha"),
    ("vitamin_c_laa", "copper_peptide"), ("copper_peptide", "aha"),
]


def exclude_reason(row) -> str | None:
    if row["slot"] is None:
        return None
    name = str(row["product_name"])
    if not isinstance(row["ingredients"], str) or not row["ingredients"].strip():
        return "no_ingredients"
    if row.get("tertiary_category") in TOOL_CATS or row.get("secondary_category") in TOOL_CATS:
        return "tool_category"
    m = ACCESSORY_RE.search(name)
    if m:
        return f"accessory_name:{m.group(1).lower()}"
    m = SET_RE.search(name)
    if m:
        return f"set_or_kit:{m.group(1).lower()}"
    return None


def conflicts(pres_list, rules=HARD) -> bool:
    for a, b in rules:
        pa = [i for i, s in enumerate(pres_list) if a in s]
        pb = [i for i, s in enumerate(pres_list) if b in s]
        if any(i != j for i in pa for j in pb):
            return True
    return False


def audit(df: pd.DataFrame) -> pd.DataFrame:
    df["exclude_reason"] = df.apply(exclude_reason, axis=1)
    df["routine_eligible"] = df["slot"].notna() & df["exclude_reason"].isna()

    print("=" * 64)
    print("SLOT EXCLUSION PASS")
    print("=" * 64)
    for slot in ("cleanser", "treatment", "moisturizer", "spf"):
        s = df[df["slot"] == slot]
        excl = s[s["exclude_reason"].notna()]
        print(f"\n{slot}: {len(s)} slotted -> {int(s['routine_eligible'].sum())} eligible "
              f"(-{len(excl)})")
        for reason, grp in excl.groupby("exclude_reason"):
            names = [f"{r.brand_name} — {str(r.product_name)[:40]}" for r in grp.itertuples()]
            print(f"    {reason} ({len(grp)}): " + "; ".join(names[:6]) + ("; ..." if len(grp) > 6 else ""))
    print(f"\ntotal: {int(df['slot'].notna().sum())} slotted -> "
          f"{int(df['routine_eligible'].sum())} eligible")
    return df


def setsize_curve(df: pd.DataFrame) -> None:
    elig = df[df["routine_eligible"]]
    pres15 = {pid: present_classes(ing, 15) for pid, ing in zip(elig["product_id"], elig["ingredients"])}
    ids = set(pres15)

    user_prods = defaultdict(set)
    for f in sorted((ROOT / "data" / "raw").glob("reviews_*.csv")):
        for ch in pd.read_csv(f, usecols=["author_id", "product_id"], chunksize=200_000):
            ch = ch[ch["product_id"].isin(ids)].dropna(subset=["author_id"])
            for a, p in zip(ch["author_id"].astype(str), ch["product_id"]):
                user_prods[a].add(p)

    buckets = [(2, 2), (3, 3), (4, 4), (5, 5), (6, 7), (8, 10**9)]
    rows = []
    overall_n = overall_c = 0
    for lo, hi in buckets:
        us = [ps for ps in user_prods.values() if lo <= len(ps) <= hi]
        n = len(us)
        c = sum(1 for ps in us if conflicts([pres15[p] for p in ps]))
        overall_n += n
        overall_c += c
        label = f"{lo}" if lo == hi else (f"{lo}+" if hi > 10**8 else f"{lo}-{hi}")
        rows.append({"set_size": label, "n_users": n, "n_conflict": c,
                     "conflict_rate": round(c / n, 4) if n else 0.0})

    out = pd.DataFrame(rows)
    EVAL.mkdir(exist_ok=True)
    out.to_csv(EVAL / "conflict_by_setsize.csv", index=False)

    print("\n" + "=" * 64)
    print("CONFLICT RATE vs SET SIZE (real co-review, cleaned slots)")
    print("=" * 64)
    print(f"{'set size':>9} {'users':>9} {'conflict':>9} {'rate':>7}")
    for r in rows:
        print(f"{r['set_size']:>9} {r['n_users']:>9,} {r['n_conflict']:>9,} {r['conflict_rate']:>7.1%}")
    print(f"{'overall':>9} {overall_n:>9,} {overall_c:>9,} {overall_c/overall_n:>7.1%}")
    print(f"\nsaved {(EVAL / 'conflict_by_setsize.csv').relative_to(ROOT)}")


def main() -> None:
    df = pd.read_parquet(PARQUET)
    df["slot"] = df["slot"].where(df["slot"].notna(), None)
    df = audit(df)
    df.to_parquet(PARQUET, index=False)
    setsize_curve(df)


if __name__ == "__main__":
    main()
