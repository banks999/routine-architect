"""BUILD_PLAN §3 pipeline — parse catalogue, build function vectors, map slots,
convert price to INR. Writes data/processed/products_enriched.parquet and prints
data checks 2-5 + function-vector coverage.

    python scripts/02_parse_ingredients.py
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.ingredients import function_vector, is_parseable, parse, unwrap  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "product_info.csv"
OUT = ROOT / "data" / "processed" / "products_enriched.parquet"

# Fixed FX assumption — recorded in DECISIONS. A spot rate, not a live feed: keeps
# the demo reproducible and offline. Real deployment would price in a live rate.
USD_TO_INR = 95.21

# Routine-slot mapping over the Sephora skincare taxonomy (checked first-match, most
# specific slot wins: spf > cleanser > moisturizer > treatment).
SLOT_BY_SECONDARY = {
    "Sunscreen": "spf",
    "Cleansers": "cleanser",
    "Moisturizers": "moisturizer",
    "Eye Care": "moisturizer",
    "Treatments": "treatment",
    "Masks": "treatment",
}
SLOT_BY_TERTIARY = {
    "Face Sunscreen": "spf", "Body Sunscreen": "spf",
    "Face Wash & Cleansers": "cleanser", "Makeup Removers": "cleanser", "Face Wipes": "cleanser",
    "Moisturizers": "moisturizer", "Night Creams": "moisturizer", "Face Oils": "moisturizer",
    "Eye Creams & Treatments": "moisturizer", "Decollete & Neck Creams": "moisturizer",
    "BB & CC Creams": "moisturizer",
    "Face Serums": "treatment", "Anti-Aging": "treatment", "Facial Peels": "treatment",
    "Exfoliators": "treatment", "Blemish & Acne Treatments": "treatment",
    "Toners": "treatment", "Mists & Essences": "treatment", "Face Masks": "treatment",
    "Sheet Masks": "treatment", "Eye Masks": "treatment",
}
_WATER_RE = re.compile(r"\bwater\b|\baqua\b", re.IGNORECASE)


def assign_slot(row) -> str | None:
    if row.get("primary_category") != "Skincare":
        return None
    t = SLOT_BY_TERTIARY.get(row.get("tertiary_category"))
    if t:
        return t
    return SLOT_BY_SECONDARY.get(row.get("secondary_category"))


def main() -> int:
    df = pd.read_csv(RAW)
    ing = df["ingredients"]
    non_null = ing.notna()

    # ---- Check 2: parseable coverage (the number for the document) ----
    parseable = ing[non_null].map(is_parseable)
    parse_rate_of_all = parseable.sum() / len(df)
    parse_rate_of_nonnull = parseable.mean()

    # ---- Check 3: multi-shade / colourant artifacts ----
    def unwrapped(x):
        return unwrap(x) if isinstance(x, str) else ""
    uw = ing[non_null].map(unwrapped)
    has_maycontain = uw.str.contains(r"\+/[-‐‑]|may contain", case=False, regex=True).sum()
    second_water = uw.map(lambda s: len(_WATER_RE.findall(s)) >= 2).sum()

    # ---- Build function vectors ----
    df["ingredient_tokens"] = ing.map(parse)
    df["function_vector"] = ing.map(function_vector)
    df["n_classes"] = df["function_vector"].map(len)
    has_fv = (df["n_classes"] > 0).sum()

    # class population (over skincare, where it matters)
    classpop: dict[str, int] = {}
    for fv in df["function_vector"]:
        for c in fv:
            classpop[c] = classpop.get(c, 0) + 1

    # ---- Check 4: slot mapping ----
    df["slot"] = df.apply(assign_slot, axis=1)
    slot_counts = df["slot"].value_counts(dropna=True)

    # ---- Check 5: price -> INR ----
    df["price_inr"] = (df["price_usd"] * USD_TO_INR).round(0)

    # ---- write enriched artifact (json fields serialised) ----
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out["ingredient_tokens"] = out["ingredient_tokens"].map(json.dumps)
    out["function_vector"] = out["function_vector"].map(json.dumps)
    out.to_parquet(OUT, index=False)

    # ---------------- report ----------------
    p = print
    p("=" * 64)
    p("CHECK 2 — parseable ingredient coverage")
    p("=" * 64)
    p(f"non-null ingredient fields     : {non_null.mean():.1%}")
    p(f"parse to >=5 tokens / ALL prod : {parse_rate_of_all:.1%}   <- DOCUMENT number")
    p(f"parse to >=5 / of the non-null : {parse_rate_of_nonnull:.1%}")

    p("\n" + "=" * 64)
    p("CHECK 3 — colourant / multi-shade artifacts (of non-null fields)")
    p("=" * 64)
    p(f"contain '+/-' or 'May Contain' : {has_maycontain:,}  ({has_maycontain/non_null.sum():.1%})")
    p(f"second 'Water/Aqua' occurrence : {second_water:,}  ({second_water/non_null.sum():.1%})")

    p("\n" + "=" * 64)
    p("CHECK 4 — routine-slot product counts (Skincare only)")
    p("=" * 64)
    for slot in ("cleanser", "treatment", "moisturizer", "spf"):
        p(f"  {slot:12s}: {int(slot_counts.get(slot, 0))}")
    p(f"  {'(total)':12s}: {int(slot_counts.sum())} of 2420 skincare products slotted")

    p("\n" + "=" * 64)
    p("CHECK 5 — price")
    p("=" * 64)
    p(f"USD min/median/max : {df['price_usd'].min():.0f} / {df['price_usd'].median():.0f} / {df['price_usd'].max():.0f}")
    p(f"INR @ {USD_TO_INR:.0f}      : {df['price_inr'].min():.0f} / {df['price_inr'].median():.0f} / {df['price_inr'].max():.0f}")

    p("\n" + "=" * 64)
    p("FUNCTION VECTORS")
    p("=" * 64)
    p(f"products with non-empty vector : {has_fv:,} / {len(df)}  ({has_fv/len(df):.1%})")
    p("class population (whole catalogue), ascending:")
    for c, n in sorted(classpop.items(), key=lambda kv: kv[1]):
        flag = "  <-- underpopulated" if n < 100 else ""
        p(f"    {c:24s}: {n:5d}{flag}")
    p(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
