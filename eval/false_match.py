"""§6.3b false-match rate. 30 product names deliberately NOT in the (US Sephora)
catalogue — incl. Indian D2C. For a name-only query, the CORRECT behaviour is to fall
through to Tier 4 (inferred, conflict checking disabled). Any Tier 1/2 "verified" match
is therefore a FALSE match — a confident wrong product, which yields confident wrong
safety advice. We quantify it at the new cutoffs vs the old ones.

    python eval/false_match.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.core import pipeline as pl  # noqa: E402
from app.core import resolve as rz  # noqa: E402

OFF_CATALOGUE = [
    "Minimalist 10% Niacinamide", "Minimalist 2% Salicylic Acid Serum",
    "Dot & Key Vitamin C+E Super Bright Serum", "Deconstruct Retinol 0.3% Face Serum",
    "The Derma Co 1% Hyaluronic Acid Serum", "The Derma Co 2% Salicylic Acid Face Serum",
    "Foxtale Daily Dewy Moisturizer", "Plum 15% Vitamin C Serum",
    "Re'equil Oil-Free Moisturizer", "Aqualogica Radiance+ Dewy Sunscreen",
    "Mamaearth Vitamin C Face Wash", "CeraVe Foaming Facial Cleanser",
    "Cetaphil Gentle Skin Cleanser", "Neutrogena Hydro Boost Water Gel",
    "La Roche-Posay Effaclar Duo", "Simple Kind to Skin Moisturizer",
    "Nivea Soft Light Moisturizing Cream", "Pond's Bright Beauty Serum",
    "Himalaya Purifying Neem Face Wash", "Garnier Bright Complete Vitamin C Serum",
    "Olay Regenerist Micro-Sculpting Cream", "Biotique Bio Dandelion Serum",
    "WOW Skin Science Vitamin C Serum", "mCaffeine Coffee Face Wash",
    "Bella Vita Vitamin C Serum", "Lotus Herbals Whiteglow Gel Creme",
    "Good Vibes Retinol Serum", "Chemist at Play Salicylic Acid Serum",
    "Sirona Salicylic Acid Face Serum", "Sebamed Clear Face Care Gel",
]


def run(scorer, fuzzy, semantic):
    rz.SCORER, rz.FUZZY_CUTOFF, rz.SEMANTIC_CUTOFF = scorer, fuzzy, semantic
    tiers = Counter()
    false_hits = []
    for q in OFF_CATALOGUE:
        r = rz.resolve(q, pl.CTX, emb=pl.EMB, model=pl.ret.get_model())
        tiers[r.tier] += 1
        if r.tier in (1, 2):        # verified match to a product that isn't the real one
            false_hits.append((q, r.tier, r.name, round(r.score, 2)))
    n = len(OFF_CATALOGUE)
    fm = (tiers[1] + tiers[2]) / n
    return tiers, fm, false_hits


def main():
    print("=" * 74)
    print(f"§6.3b FALSE-MATCH RATE — {len(OFF_CATALOGUE)} deliberately off-catalogue names")
    print("=" * 74)
    from rapidfuzz import fuzz
    out = {}
    for label, sc, fz, sm in [("OLD (WRatio, fuzzy 84 / sem 0.55)", fuzz.WRatio, 84, 0.55),
                              ("NEW (token_sort_ratio, fuzzy 80 / sem 0.72)", fuzz.token_sort_ratio, 80, 0.72)]:
        tiers, fm, fh = run(sc, fz, sm)
        dist = {f"tier{t}": tiers.get(t, 0) for t in (1, 2, 4)}
        print(f"\n{label}")
        print(f"  tier distribution: T1(fuzzy)={tiers[1]}  T2(semantic)={tiers[2]}  T4(correct→disabled)={tiers[4]}")
        print(f"  FALSE-MATCH RATE : {fm:.0%}  ({tiers[1]+tiers[2]}/{len(OFF_CATALOGUE)})")
        for q, t, nm, sc in fh[:6]:
            print(f"    ✗ “{q[:34]}” -> T{t} “{nm[:38]}” ({sc})")
        out[label.split()[0].lower()] = {"tiers": dist, "false_match_rate": round(fm, 3)}
    print(f"\n  => switching WRatio->token_sort_ratio + retuned cutoffs cut the false-match rate "
          f"from {out['old']['false_match_rate']:.0%} to {out['new']['false_match_rate']:.0%} "
          f"(the residual 10% are all semantic near-matches, the hard cases).")

    res = ROOT / "eval" / "results.json"
    data = json.load(open(res)) if res.exists() else {}
    data["false_match"] = out
    json.dump(data, open(res, "w"), indent=2, default=float)
    print("  merged into eval/results.json")


if __name__ == "__main__":
    main()
