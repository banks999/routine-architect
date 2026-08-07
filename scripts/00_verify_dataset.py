"""BUILD_PLAN §1 — dataset go/no-go gate.

Decides whether the routine-architect angle is viable, which hinges entirely on
parseable ingredient lists. Run before writing any application code.

    python scripts/00_verify_dataset.py
"""
import sys
from pathlib import Path

import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
PRODUCTS = RAW / "product_info.csv"
REVIEWS = RAW / "reviews_0-250.csv"  # §1 samples the first shard only


def gate(coverage: float) -> tuple[str, str]:
    """Map ingredient coverage to the §1 decision-gate branch."""
    if coverage > 0.70:
        return "GO", "ingredients >70% — proceed with the full plan"
    if coverage >= 0.40:
        return "GO (scoped)", "ingredients 40-70% — proceed, scope to well-covered categories, document as limitation"
    return "NO-GO", "ingredients <40% — abort to the §10 fallback plan"


def main() -> int:
    for f in (PRODUCTS, REVIEWS):
        if not f.exists():
            print(f"MISSING: {f}", file=sys.stderr)
            return 1

    df = pd.read_csv(PRODUCTS)
    coverage = df["ingredients"].notna().mean()

    print("=" * 60)
    print("PRODUCTS")
    print("=" * 60)
    print(f"product count         : {len(df)}")
    print(f"ingredient coverage   : {coverage:.1%}  <-- decides the gate")
    print(f"columns present       : price_usd={'price_usd' in df} "
          f"category={'primary_category' in df} rating={'rating' in df} reviews={'reviews' in df}")
    print("\n5 raw ingredient strings (judge parseability):")
    for i, s in enumerate(df["ingredients"].dropna().sample(5, random_state=0).tolist(), 1):
        print(f"\n[{i}] {s[:400]}{'...' if len(str(s)) > 400 else ''}")

    r = pd.read_csv(REVIEWS)
    print("\n" + "=" * 60)
    print("REVIEWS (reviews_0-250.csv)")
    print("=" * 60)
    print(f"row count             : {len(r)}")
    print(f"skin_type coverage    : {r['skin_type'].notna().mean():.1%}  (need >50%)")
    print(f"skin_tone coverage    : {r['skin_tone'].notna().mean():.1%}")
    print(f"unique authors        : {r['author_id'].nunique()}")

    verdict, reason = gate(coverage)
    print("\n" + "=" * 60)
    print(f"GATE: {verdict} — {reason}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
