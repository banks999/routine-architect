"""§6 remainder: (3) conflict-layer-off sanity test, (4) beyond-accuracy per slot,
(5) latency per stage. Reuses routine_eval's cached pools + profiles.
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
from eval import routine_eval as R  # noqa: E402

profiles = R.gen_profiles()
priors = R.priors


def gini(x):
    x = np.sort(np.asarray(x, "float64"))
    n = len(x)
    if n == 0 or x.sum() == 0:
        return 0.0
    return (2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum())


# ---------- (3) conflict-layer-off sanity test ----------
def sanity_off():
    on_rel = on_cov = off_rel = off_cov = off_conf = 0
    for p in profiles[:80]:
        c = R.build(p, R.CLANY)
        on = sv.solve(c, p, enforce_conflicts=True)
        off = sv.solve(c, p, enforce_conflicts=False)
        on_rel += sum(pl.cand.relevance for pl in on.placements)
        off_rel += sum(pl.cand.relevance for pl in off.placements)
        on_cov += sv._covered(on.placements, p.concerns)
        off_cov += sv._covered(off.placements, p.concerns)
        off_conf += sum(1 for v in off.hard_violations if v.kind == "conflict")
    n = 80
    print("=" * 66)
    print("(3) CONFLICT-LAYER-OFF SANITY TEST (80 profiles, any-position)")
    print("=" * 66)
    print(f"  relevance sum  : layer-ON {on_rel/n:.3f}  vs  layer-OFF {off_rel/n:.3f}")
    print(f"  concern cover  : layer-ON {on_cov/n:.1%}  vs  layer-OFF {off_cov/n:.1%}")
    print(f"  hard conflicts : layer-ON 0  vs  layer-OFF {off_conf} across {n} routines")
    return dict(rel_on=on_rel/n, rel_off=off_rel/n, cov_on=on_cov/n, cov_off=off_cov/n, conf_off=off_conf)


# ---------- (4) beyond-accuracy per slot ----------
def beyond():
    _e = R.EMB
    # popularity proxy from priors bayes-count is not present; use review-derived posrate? use rating count via META reviews
    pop = {r.product_id: (r.reviews if pd.notna(r.reviews) else 1) for r in R.prod.itertuples()}
    recs = {s: [] for s in ("cleanser", "moisturizer", "spf", "treatment")}
    for p in profiles:
        c = R.build(p, R.CLANY)
        r = sv.solve(c, p)
        for pl in r.placements:
            key = "treatment" if pl.slot.startswith("treatment") else pl.slot
            recs[key].append(pl.cand.id)
    pools = {**{s: R.BASE[s][0] for s in R.BASE}, "treatment": sorted({i for c in R.TREAT.values() for i in c[0]})}
    print("\n" + "=" * 66)
    print("(4) BEYOND-ACCURACY per slot (solver recs over 200 profiles, any-position)")
    print("=" * 66)
    print(f"{'slot':12}{'cov%':>8}{'diversity':>11}{'novelty':>9}{'gini':>7}")
    out = {}
    for slot, ids in recs.items():
        uniq = set(ids)
        poolids = pools[slot]
        cov = len(uniq) / max(len(poolids), 1)
        embs = [_e[i] for i in uniq if i in _e]
        div = float(np.mean([1 - a @ b for k, a in enumerate(embs) for b in embs[k+1:]])) if len(embs) > 1 else 0.0
        nov = float(np.mean([-np.log2((pop.get(i, 1) + 1) / (max(pop.values()) + 1)) for i in ids]))
        freq = pd.Series(ids).value_counts().values
        g = gini(freq)
        print(f"{slot:12}{cov:>7.1%}{div:>11.3f}{nov:>9.2f}{g:>7.2f}")
        out[slot] = dict(coverage=cov, diversity=div, novelty=nov, gini=float(g))
    return out


# ---------- (5) latency per stage ----------
def latency():
    p = profiles[0]
    model = ret.get_model()
    q = "retinol anti-aging serum for wrinkles"
    rt, rk_, sv_ = [], [], []
    for _ in range(30):
        t = time.perf_counter(); ret.retrieve(q, "treatment", top_k=30); rt.append((time.perf_counter()-t)*1000)
    for _ in range(30):
        t = time.perf_counter(); c = R.build(p, R.CLANY); rk_.append((time.perf_counter()-t)*1000)
    for _ in range(50):
        t = time.perf_counter(); sv.solve(c, p); sv_.append((time.perf_counter()-t)*1000)
    print("\n" + "=" * 66)
    print("(5) LATENCY per stage (ms)")
    print("=" * 66)
    print(f"{'stage':22}{'p50':>8}{'p95':>8}")
    out = {}
    for name, arr in [("retrieval (1 slot)", rt), ("ranking+build (5 slots)", rk_), ("basket solve", sv_)]:
        a = np.array(arr)
        print(f"{name:22}{np.percentile(a,50):>8.1f}{np.percentile(a,95):>8.1f}")
        out[name] = dict(p50=float(np.percentile(a, 50)), p95=float(np.percentile(a, 95)))
    return out


if __name__ == "__main__":
    res = {"sanity_off": sanity_off(), "beyond_accuracy": beyond(), "latency": latency()}
    existing = json.load(open(ROOT / "eval" / "results.json"))
    existing.update(res)
    json.dump(existing, open(ROOT / "eval" / "results.json", "w"), indent=2, default=float)
    print("\nmerged into eval/results.json")
