"""BUILD_PLAN §6.1 standard metrics, segmented by cohort (warm >=5 reviews / cold 1-2).
The cold row justifies the deployed weights keeping rating+skin (cf & semantic are 0
for users with no history). Deployed weights [sem .3 / cf .5 / rating .1 / skin .1].
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.core import ranking as rk  # noqa: E402
from eval import rank_eval as re2  # noqa: E402

DEPLOYED = np.array([0.3, 0.5, 0.1, 0.1], "float32")  # sem, cf, rating, skin


def main():
    r = re2.load_reviews()
    prod = pd.read_parquet(ROOT / "data" / "processed" / "products_enriched.parquet")
    slot_of = dict(zip(prod["product_id"], prod["slot"]))
    eligible = set(prod[prod["routine_eligible"]]["product_id"])
    r = r.sort_values("submission_time")
    t1, t2 = r["submission_time"].quantile([0.70, 0.85])
    train, test = r[r["submission_time"] < t1], r[r["submission_time"] >= t2]

    emb = re2.embed_all(prod)
    sig = rk.fit(train, eligible, emb)
    pools = {}
    for slot in prod["slot"].dropna().unique():
        ids = sorted(eligible & set(prod[prod["slot"] == slot]["product_id"]))
        pools[slot] = {"ids": ids, "idx": {p: i for i, p in enumerate(ids)}}

    total = r.groupby("author_id").size()
    warm = set(total[total >= 5].index)
    cold = set(total[(total >= 1) & (total <= 2)].index)

    def positives(cohort):
        p = test[(test["rating"] >= 4) & test["product_id"].isin(eligible)
                 & test["author_id"].isin(cohort)].copy()
        p["slot"] = p["product_id"].map(slot_of)
        return p.dropna(subset=["slot", "skin_type"])

    print("=" * 66)
    print("STANDARD METRICS by cohort — DEPLOYED weights, 100 sampled negatives")
    print("=" * 66)
    print(f"{'cohort':18}{'n':>6}{'NDCG@10':>10}{'Recall@10':>11}{'MAP@10':>9}{'random':>9}")
    for name, coh, mlk in [("warm (>=5 rev)", warm, 2), ("cold (1-2 rev)", cold, 0)]:
        inst = re2.make_instances(positives(coh), pools, sig, 2000, min_liked=mlk)
        if not inst:
            print(f"{name:18}{'0':>6}   (no instances)")
            continue
        nd, rc, ap, n = re2.eval_weights(inst, DEPLOYED)
        rnd = np.mean([re2.ndcg_at(re2.rank_of_true(re2.RNG.standard_normal(M.shape[0]), ti))
                       for M, ti, _ in inst])
        print(f"{name:18}{n:>6}{nd:>10.4f}{rc:>11.4f}{ap:>9.4f}{rnd:>9.4f}")


if __name__ == "__main__":
    main()
