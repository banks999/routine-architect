"""Precompute the deployable rating + skin-affinity priors (the cf-independent part
of the deployed ranker) for eligible products, so serving/demo needs no review load.

  bayes  = (v/(v+m))R + (m/(v+m))C        (Bayesian rating prior)
  aff_<skin> = shrink(skin positive rate -> product positive rate, k=20)

Writes data/processed/rank_priors.parquet. Fit on ALL reviews (serving uses all).
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

POS, K = 4, 20.0
SKINS = ["dry", "oily", "combination", "normal"]


def main() -> None:
    prod = pd.read_parquet(ROOT / "data" / "processed" / "products_enriched.parquet")
    eligible = set(prod[prod["routine_eligible"]]["product_id"])

    cols = ["product_id", "rating", "skin_type"]
    r = pd.concat([pd.read_csv(f, usecols=cols) for f in sorted((ROOT / "data" / "raw").glob("reviews_*.csv"))],
                  ignore_index=True)
    r = r[r["product_id"].isin(eligible)].dropna(subset=["rating"])
    r["pos"] = r["rating"] >= POS

    C = float(r["rating"].mean())
    g = r.groupby("product_id")
    v, R, posrate = g["rating"].count(), g["rating"].mean(), g["pos"].mean()
    m = float(v.median())
    out = pd.DataFrame({"product_id": v.index})
    out["bayes"] = ((v / (v + m)) * R + (m / (v + m)) * C).values
    out["posrate"] = posrate.reindex(v.index).values

    sk = r.dropna(subset=["skin_type"]).groupby(["product_id", "skin_type"])["pos"].agg(["sum", "count"])
    pr = out.set_index("product_id")["posrate"]
    for skin in SKINS:
        aff = {}
        for pid in out["product_id"]:
            base = pr.get(pid, C / 5.0)
            if (pid, skin) in sk.index:
                n_pos, n_tot = sk.loc[(pid, skin), "sum"], sk.loc[(pid, skin), "count"]
                w = n_tot / (n_tot + K)
                aff[pid] = w * (n_pos / n_tot) + (1 - w) * base
            else:
                aff[pid] = base
        out[f"aff_{skin}"] = out["product_id"].map(aff)

    out.to_parquet(ROOT / "data" / "processed" / "rank_priors.parquet", index=False)
    print(f"wrote rank_priors.parquet: {len(out)} products, m={m:.1f}, C={C:.3f}")


if __name__ == "__main__":
    main()
