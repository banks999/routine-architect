"""Per-slot hybrid retrieval: dense (MiniLM+FAISS) + sparse (BM25) fused via RRF.
Pure functions, no web framework. Indexes persist to disk for fast API startup.

Design notes:
- Retrieves ONLY from routine_eligible products, one index per routine slot.
- Embedding text is ordered most-discriminative-first (name → brand → functional
  classes → category → highlights → top ingredients) so that if the MiniLM 256-token
  window truncates, it drops the least useful tail (deep ingredients), not the name.
- BM25 gets the functional-class KEYS injected as explicit tokens ("retinoid", "aha",
  "vitamin_c_laa"), so a lexical query for a function matches on the function itself
  rather than on "acid", which is a substring of every acid.
"""
from __future__ import annotations

import ast
import json
import pickle
import re
from functools import lru_cache
from pathlib import Path

import faiss
import numpy as np
import pandas as pd
from rank_bm25 import BM25Okapi

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
SLOTS = ("cleanser", "treatment", "moisturizer", "spf")
INDEX_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "processed" / "index"
N_INGREDIENTS = 10          # top-N ingredients in embedding text
RRF_K = 60                  # Cormack et al. 2009 default; no val budget to tune it
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# class key -> natural words for the DENSE text (the semantic model reads words,
# not snake_case). BM25 keeps the raw keys instead (see below).
READABLE = {
    "vitamin_c_laa": "vitamin c ascorbic acid", "vitamin_c_derivative": "vitamin c derivative",
    "uv_filter_chemical": "chemical sunscreen spf", "uv_filter_mineral": "mineral sunscreen zinc titanium",
    "aha": "aha glycolic lactic acid exfoliant", "bha": "bha salicylic acid",
    "pha": "pha gluconolactone", "benzoyl_peroxide": "benzoyl peroxide",
    "copper_peptide": "copper peptide", "exfoliant_physical": "physical scrub exfoliant",
    "ceramide_barrier": "ceramide barrier", "antioxidant_other": "antioxidant",
    "brightening_other": "brightening", "occlusive": "occlusive moisturizing",
}


def _readable(cls: str) -> str:
    return READABLE.get(cls, cls.replace("_", " "))


def _as_list(raw) -> list[str]:
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        v = ast.literal_eval(raw)
        return [str(x) for x in v] if isinstance(v, (list, tuple)) else [raw]
    except (ValueError, SyntaxError):
        return [raw]


def build_product_text(row) -> str:
    """Most-discriminative-first text for embedding."""
    fv = json.loads(row["function_vector"]) if isinstance(row["function_vector"], str) else {}
    classes = sorted(fv, key=fv.get, reverse=True)
    toks = json.loads(row["ingredient_tokens"]) if isinstance(row["ingredient_tokens"], str) else []
    cat = " ".join(str(row.get(c, "")) for c in ("secondary_category", "tertiary_category") if pd.notna(row.get(c)))
    parts = [
        str(row["product_name"]),
        str(row["brand_name"]),
        " ".join(_readable(c) for c in classes),
        cat,
        " ".join(_as_list(row.get("highlights"))),
        " ".join(toks[:N_INGREDIENTS]),
    ]
    return " . ".join(p for p in parts if p.strip())


def _bm25_tokens(row) -> list[str]:
    """Corpus tokens = words of the embedding text PLUS injected class keys."""
    fv = json.loads(row["function_vector"]) if isinstance(row["function_vector"], str) else {}
    return _TOKEN_RE.findall(build_product_text(row).lower()) + list(fv.keys())


@lru_cache(maxsize=1)
def get_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)


# ---------------- build ----------------
def build_indexes(parquet: Path, out: Path = INDEX_DIR) -> dict:
    df = pd.read_parquet(parquet)
    df = df[df["routine_eligible"]].copy()
    model = get_model()
    out.mkdir(parents=True, exist_ok=True)
    tok = model.tokenizer
    stats = {}
    for slot in SLOTS:
        sub = df[df["slot"] == slot].reset_index(drop=True)
        texts = sub.apply(build_product_text, axis=1).tolist()
        n_tokens = [len(tok(t)["input_ids"]) for t in texts]

        emb = model.encode(texts, normalize_embeddings=True, show_progress_bar=False).astype("float32")
        index = faiss.IndexFlatIP(emb.shape[1])
        index.add(emb)
        faiss.write_index(index, str(out / f"{slot}.faiss"))

        corpus = sub.apply(_bm25_tokens, axis=1).tolist()
        with open(out / f"{slot}.bm25.pkl", "wb") as f:
            pickle.dump(BM25Okapi(corpus), f)

        meta = sub[["product_id", "product_name", "brand_name", "price_inr",
                    "function_vector", "slot"]].copy()
        meta["text"] = texts
        meta.to_parquet(out / f"{slot}.meta.parquet", index=False)

        arr = np.array(n_tokens)
        stats[slot] = {"n": len(sub), "tok_p50": int(np.percentile(arr, 50)),
                       "tok_p95": int(np.percentile(arr, 95)), "tok_max": int(arr.max()),
                       "over_256": int((arr > 256).sum())}
    return stats


# ---------------- query ----------------
@lru_cache(maxsize=len(SLOTS))
def load_slot(slot: str, out: str = str(INDEX_DIR)):
    outp = Path(out)
    index = faiss.read_index(str(outp / f"{slot}.faiss"))
    with open(outp / f"{slot}.bm25.pkl", "rb") as f:
        bm25 = pickle.load(f)
    meta = pd.read_parquet(outp / f"{slot}.meta.parquet")
    return index, bm25, meta


def _ranks(order: list[int]) -> dict[int, int]:
    return {idx: r for r, idx in enumerate(order, start=1)}  # 1-based


def retrieve(query: str, slot: str, top_k: int = 10, pool: int = 50, k: int = RRF_K) -> list[dict]:
    index, bm25, meta = load_slot(slot)
    model = get_model()

    q = model.encode([query], normalize_embeddings=True).astype("float32")
    _, I = index.search(q, min(pool, index.ntotal))
    dense_order = [int(i) for i in I[0] if i != -1]
    dense_rank = _ranks(dense_order)

    scores = bm25.get_scores(_TOKEN_RE.findall(query.lower()))
    sparse_order = [int(i) for i in np.argsort(scores)[::-1][:pool] if scores[i] > 0]
    sparse_rank = _ranks(sparse_order)

    fused = {}
    for idx in set(dense_order) | set(sparse_order):
        fused[idx] = (1.0 / (k + dense_rank[idx]) if idx in dense_rank else 0.0) + \
                     (1.0 / (k + sparse_rank[idx]) if idx in sparse_rank else 0.0)
    ordered = sorted(fused, key=fused.get, reverse=True)[:top_k]

    out = []
    for rank, idx in enumerate(ordered, start=1):
        row = meta.iloc[idx]
        fv = json.loads(row["function_vector"])
        out.append({
            "fused_rank": rank,
            "dense_rank": dense_rank.get(idx),
            "bm25_rank": sparse_rank.get(idx),
            "product_id": row["product_id"],
            "name": f"{row['brand_name']} — {row['product_name']}",
            "price_inr": row["price_inr"],
            "classes": sorted(fv, key=fv.get, reverse=True),
        })
    return out
