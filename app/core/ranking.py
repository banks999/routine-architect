"""Preference ranking (BUILD_PLAN §4). Blends four signals:

  1. semantic   — content CF: cosine(user's liked-item centroid, candidate embedding)
  2. cf         — behavioural: item-item co-review co-occurrence (cosine)
  3. rating     — Bayesian-shrunk product quality  (v/(v+m))R + (m/(v+m))C
  4. skin       — skin-type positive rate, Bayesian-shrunk toward the product's
                  own overall positive rate (kills low-n lucky-review products)

Everything here is FIT ON TRAIN ONLY. The eval harness enforces the temporal
split; this module never sees val/test. Weights are tuned externally (grid search)
and passed in — this file just fits the signals and emits raw per-signal scores.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import pandas as pd

POS_THRESHOLD = 4  # a "positive" / "liked" review is rating >= 4
COOC_DEGREE_CAP = 50  # skip pathological power-users when building co-occurrence


@dataclass
class Signals:
    rating: dict            # pid -> bayesian rating score
    posrate_prod: dict      # pid -> overall train positive rate
    skin_pos: dict          # (pid, skin) -> (n_pos, n_total)
    cooc: dict              # pid -> {pid2: co-review count}  (eligible items only)
    pop: dict               # pid -> train reviewer count (eligible)
    emb: dict               # pid -> unit embedding (ALL products)
    user_liked: dict        # user -> list of liked eligible pids (train)
    m: float
    C: float
    k_skin: float


def fit(train: pd.DataFrame, eligible_ids: set, emb: dict,
        m: float | None = None, k_skin: float = 20.0) -> Signals:
    """train: author_id, product_id, rating, skin_type. TRAIN rows only."""
    C = float(train["rating"].mean())
    elig = train[train["product_id"].isin(eligible_ids)]

    g = elig.groupby("product_id")["rating"]
    v = g.count()
    R = g.mean()
    pos = elig.assign(pos=elig["rating"] >= POS_THRESHOLD).groupby("product_id")["pos"]
    posrate_prod = pos.mean().to_dict()
    if m is None:
        m = float(v[v > 0].median())
    rating = ((v / (v + m)) * R + (m / (v + m)) * C).to_dict()

    # skin-type positives per product
    sp = elig.assign(pos=elig["rating"] >= POS_THRESHOLD)
    skin_pos = {}
    for (pid, skin), grp in sp.dropna(subset=["skin_type"]).groupby(["product_id", "skin_type"]):
        skin_pos[(pid, skin)] = (int(grp["pos"].sum()), len(grp))

    # co-review co-occurrence among eligible items + per-user liked lists
    user_items = elig.groupby("author_id")["product_id"].apply(list)
    user_liked = (elig[elig["rating"] >= POS_THRESHOLD]
                  .groupby("author_id")["product_id"].apply(list).to_dict())
    cooc: dict = defaultdict(lambda: defaultdict(int))
    pop = elig.groupby("product_id")["author_id"].nunique().to_dict()
    for items in user_items:
        u = list(set(items))
        if len(u) < 2 or len(u) > COOC_DEGREE_CAP:
            continue
        for i in range(len(u)):
            for j in range(i + 1, len(u)):
                a, b = u[i], u[j]
                cooc[a][b] += 1
                cooc[b][a] += 1

    return Signals(rating=rating, posrate_prod=posrate_prod, skin_pos=skin_pos,
                   cooc={k: dict(v) for k, v in cooc.items()}, pop=pop, emb=emb,
                   user_liked=user_liked, m=m, C=C, k_skin=k_skin)


def _skin_affinity(s: Signals, pid: str, skin) -> float:
    base = s.posrate_prod.get(pid, s.C / 5.0)  # fallback: crude global positive rate
    n_pos, n_tot = s.skin_pos.get((pid, skin), (0, 0))
    if n_tot == 0:
        return base
    raw = n_pos / n_tot
    w = n_tot / (n_tot + s.k_skin)
    return w * raw + (1 - w) * base


def raw_scores(candidate_ids: list, skin, liked_ids: list, s: Signals) -> dict:
    """Four unnormalised score arrays aligned to candidate_ids."""
    cand = np.array(candidate_ids)

    rating = np.array([s.rating.get(c, s.C) for c in cand])
    skin_v = np.array([_skin_affinity(s, c, skin) for c in cand])

    liked_emb = [s.emb[p] for p in liked_ids if p in s.emb]
    if liked_emb:
        u = np.mean(liked_emb, axis=0)
        u = u / (np.linalg.norm(u) + 1e-9)
        sem = np.array([float(u @ s.emb[c]) if c in s.emb else 0.0 for c in cand])
    else:
        sem = np.zeros(len(cand))

    liked_elig = [p for p in liked_ids if p in s.cooc or p in s.pop]
    if liked_elig:
        cf = []
        for c in cand:
            popc = s.pop.get(c, 0)
            tot = 0.0
            for t in liked_elig:
                n = s.cooc.get(t, {}).get(c, 0)
                if n:
                    tot += n / np.sqrt(popc * s.pop.get(t, 1) + 1e-9)
            cf.append(tot)
        cf = np.array(cf)
    else:
        cf = np.zeros(len(cand))

    return {"semantic": sem, "cf": cf, "rating": rating, "skin": skin_v}


def zscore(a: np.ndarray) -> np.ndarray:
    sd = a.std()
    return (a - a.mean()) / sd if sd > 1e-9 else np.zeros_like(a)
