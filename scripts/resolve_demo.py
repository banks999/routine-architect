"""§5.5 open-world demo: 5 resolutions across the ladder + one routine built around a
pinned owned product.

    python scripts/resolve_demo.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.core import pipeline as pl  # noqa: E402
from app.core import solver as sv  # noqa: E402
from app.core import resolve as rz  # noqa: E402

TESTS = [
    ("CeraVe Foaming Facial Cleanser", None, None),                    # likely fuzzy/semantic (catalogue-ish)
    ("Paula's Choice 2% BHA Liquid Exfoliant", None, None),           # in catalogue -> fuzzy
    ("Minimalist 10% Niacinamide", "Aqua, Niacinamide, Zinc PCA, Pentylene Glycol, "
     "Hyaluronic Acid, Glycerin, Phenoxyethanol", None),             # Indian D2C, NOT in catalogue -> Tier 3 paste
    ("Deconstruct Retinol 0.3% Face Serum", None, None),              # Indian D2C, NOT in catalogue -> Tier 4 inferred
    ("some random unbranded moisturizer", None, ["humectant", "ceramide_barrier"]),  # Tier 5 manual
]


def main():
    print("=" * 78)
    print("§5.5 RESOLUTION LADDER — 5 test resolutions")
    print("=" * 78)
    for q, pasted, manual in TESTS:
        r = rz.resolve(q, pl.CTX, pasted=pasted, manual=manual, emb=pl.EMB, model=pl.ret.get_model())
        chk = "✓ full conflict checking" if r.conflict_checkable else "✗ conflict checking DISABLED"
        print(f"\n  “{q[:50]}”")
        print(f"    Tier {r.tier} ({r.method}) · confidence={r.confidence} · {chk}")
        print(f"    -> {r.name[:60]}  classes={sorted(r.classes) or '—'}")
        print(f"    {r.note}")

    # ---- one routine built AROUND a pinned owned product ----
    print("\n" + "=" * 78)
    print("ROUTINE BUILT AROUND A PINNED OWNED PRODUCT")
    print("=" * 78)
    asyncio.run(pl.store.connect())
    # user OWNS a retinoid; asks for texture+acne -> the solver must schedule the new acid
    # into a different session from the owned retinoid (retinoid x aha/bha is a hard conflict)
    profile = sv.Profile(concerns=["texture", "acne"], budget=9000, skin="combination")
    res = asyncio.run(pl.recommend(profile, owned=["The Ordinary Granactive Retinoid 2% Emulsion"]))
    print(f"  owned/pinned: {[c['name'] for c in res['am']+res['pm'] if c.get('owned')]}")
    print(f"  AM: {[(c['slot'], c['name'][:34], c.get('owned', False)) for c in res['am']]}")
    print(f"  PM: {[(c['slot'], c['name'][:34], c.get('owned', False)) for c in res['pm']]}")
    print(f"  price ₹{res['total_price_inr']:.0f} (owned excluded) · hard-violations {len(res['hard_violations'])}")
    print(f"  avoided: {[(a['action'], a['rule_id'], a['classes']) for a in res['avoided']]}")


if __name__ == "__main__":
    main()
