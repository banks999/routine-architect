"""Recommendation orchestration: retrieval -> deployed-weight relevance -> solver,
plus grounded explanations. Returns a fully-formed dict so the UI recomputes nothing.
"""
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from app.core import conflicts as cf
from app.core import retrieval as ret
from app.core import solver as sv
from app.core.ingredients import present_classes
from app.db.store import store

ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOYED = {"semantic": 0.3, "cf": 0.5, "rating": 0.1, "skin": 0.1}

_prod = pd.read_parquet(ROOT / "data" / "processed" / "products_enriched.parquet")
_priors = pd.read_parquet(ROOT / "data" / "processed" / "rank_priors.parquet").set_index("product_id")
_e = np.load(ROOT / "data" / "processed" / "emb_all.npz", allow_pickle=True)
EMB = dict(zip(_e["ids"], _e["emb"]))
META = {r.product_id: r for r in _prod.itertuples()}
# safety-side detection: any-position (a deep-listed active still counts)
CLASSES = {p: present_classes(i, None) for p, i in zip(_prod["product_id"], _prod["ingredients"]) if isinstance(i, str)}

CONCERN_QUERY = {
    "aging": "retinol anti-aging serum for wrinkles", "texture": "glycolic acid AHA exfoliating serum",
    "acne": "salicylic acid BHA serum for acne", "dark_spots": "vitamin c serum for dark spots",
    "dullness": "vitamin c brightening serum", "redness": "azelaic acid serum for redness",
    "dryness": "hyaluronic acid hydrating serum", "oiliness": "niacinamide serum for oily skin",
}
BASE_Q = {"cleanser": "gentle cleanser", "moisturizer": "hydrating moisturizer", "spf": "sunscreen spf"}


def _z(a):
    a = np.asarray(a, "float32")
    return (a - a.mean()) / a.std() if a.std() > 1e-9 else np.zeros_like(a)


def _cands(query, slot, skin):
    ids = [h["product_id"] for h in ret.retrieve(query, "treatment" if slot.startswith("treatment") else slot, top_k=30)
           if h["product_id"] in EMB and h["product_id"] in _priors.index]
    qv = ret.get_model().encode([query], normalize_embeddings=True)[0]
    sem = _z([float(qv @ EMB[i]) for i in ids])
    rat = _z([_priors.at[i, "bayes"] for i in ids])
    col = f"aff_{skin}" if f"aff_{skin}" in _priors.columns else "posrate"
    ski = _z([_priors.at[i, col] for i in ids])
    rel = DEPLOYED["semantic"] * sem + DEPLOYED["rating"] * rat + DEPLOYED["skin"] * ski
    out = []
    for i, rv in zip(ids, rel):
        m = META[i]
        # Cleansers are RINSE-OFF: their actives have minimal contact time and don't
        # drive leave-on conflicts (a salicylic cleanser + retinoid is fine, unlike a
        # salicylic serum + retinoid). So they carry no conflict-relevant classes.
        classes = frozenset() if slot == "cleanser" else frozenset(CLASSES.get(i, set()))
        out.append(sv.Candidate(i, f"{m.brand_name} — {m.product_name}",
                                float(m.price_inr) if pd.notna(m.price_inr) else 1e9,
                                classes, json.loads(m.function_vector), float(rv), slot))
    return sorted(out, key=lambda c: c.relevance, reverse=True)


def build_candidates(profile: sv.Profile):
    c1, c2 = profile.concerns[0], profile.concerns[-1]
    return {"cleanser": _cands(BASE_Q["cleanser"], "cleanser", profile.skin),
            "moisturizer": _cands(BASE_Q["moisturizer"], "moisturizer", profile.skin),
            "spf": _cands(BASE_Q["spf"], "spf", profile.skin),
            "treatment_A": _cands(CONCERN_QUERY.get(c1, c1), "treatment_A", profile.skin),
            "treatment_B": _cands(CONCERN_QUERY.get(c2, c2), "treatment_B", profile.skin)}


def _template_explain(skin, concerns, n_rev, snippets, classes):
    bits = []
    if n_rev:
        bits.append(f"{n_rev} reviewers with {skin} skin rated this 4★ or higher.")
    actives = sorted(classes & sv._active_classes())
    if actives:
        bits.append("Active(s): " + ", ".join(a.replace("_", " ") for a in actives) + ".")
    if snippets:
        bits.append(f"One wrote: “{snippets[0][:150].strip()}”")
    return " ".join(bits) or "Matched to your profile on content similarity and rating."


async def _gemini_explain(context: list) -> dict | None:
    """Auto-enabled when GEMINI_API_KEY is set. Falls back to template on missing key,
    quota error, bad output, OR a mid-request timeout (the sync SDK call runs in a
    thread with an 8s deadline so a hang never blocks the request)."""
    import asyncio
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None

    def _call():
        import google.generativeai as genai
        genai.configure(api_key=key)
        prompt = ("For each product, write ONE friendly sentence on why it fits the user, using ONLY the "
                  "provided review snippets and actives. Do NOT invent ingredients or make safety/medical "
                  "claims. Return ONLY JSON {product_id: sentence}.\n" + json.dumps(context)[:6000])
        r = genai.GenerativeModel("gemini-1.5-flash").generate_content(
            prompt, request_options={"timeout": 7})
        txt = r.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(txt)
    try:
        out = await asyncio.wait_for(asyncio.to_thread(_call), timeout=8)
        return out if isinstance(out, dict) else None
    except Exception as e:
        print(f"[llm] Gemini unavailable ({type(e).__name__}: {e}); template fallback")
        return None


async def _explain(placements, profile):
    context = []
    tmpl = {}
    for pl in placements:
        n_rev, snip = await store.review_snippets(pl.cand.id, profile.skin, k=3)
        tmpl[pl.cand.id] = _template_explain(profile.skin, profile.concerns, n_rev, snip, pl.cand.classes)
        context.append({"product_id": pl.cand.id, "name": pl.cand.name,
                        "actives": sorted(pl.cand.classes & sv._active_classes()), "snippets": snip})
    gem = await _gemini_explain(context)
    source = "gemini" if gem else "template"
    return {pid: (gem.get(pid) if gem and gem.get(pid) else tmpl[pid]) for pid in tmpl}, source


def _card(pl, why):
    m = META[pl.cand.id]
    return {"product_id": pl.cand.id, "slot": pl.slot, "name": pl.cand.name,
            "price_inr": pl.cand.price, "sessions": sorted(pl.sessions),
            "actives": sorted(pl.cand.classes & sv._active_classes()),
            "all_classes": sorted(pl.cand.classes), "relevance": round(pl.cand.relevance, 3),
            "highlights": (m.highlights if pd.notna(m.highlights) else None), "why": why}


async def recommend(profile: sv.Profile, enforce_conflicts: bool = True) -> dict:
    t = {}
    t0 = time.perf_counter(); cands = build_candidates(profile); t["retrieval_and_rank_ms"] = (time.perf_counter()-t0)*1000
    t0 = time.perf_counter(); routine = sv.solve(cands, profile, enforce_conflicts=enforce_conflicts); t["solve_ms"] = (time.perf_counter()-t0)*1000
    t0 = time.perf_counter(); whys, src = await _explain(routine.placements, profile); t["explain_ms"] = (time.perf_counter()-t0)*1000

    pls = routine.placements
    decomp = {"relevance_sum": round(sum(p.cand.relevance for p in pls), 3),
              "concern_coverage": round(sv._covered(pls, profile.concerns), 3),
              "function_redundancy": sv._redundancy(pls),
              "budget_overrun": round(max(0.0, routine.total_price - profile.budget) / max(profile.budget, 1), 3),
              "final_score": round(routine.score, 3),
              "weights": {"alpha": sv.ALPHA, "beta": sv.BETA, "gamma": sv.GAMMA}}
    return {
        "profile": {"concerns": profile.concerns, "skin": profile.skin, "budget_inr": profile.budget},
        "constraints_enforced": enforce_conflicts,
        "am": [_card(p, whys[p.cand.id]) for p in sorted(routine.session("AM"), key=lambda x: sv.SLOT_ORDER.index(x.slot))],
        "pm": [_card(p, whys[p.cand.id]) for p in sorted(routine.session("PM"), key=lambda x: sv.SLOT_ORDER.index(x.slot))],
        "total_price_inr": routine.total_price, "within_budget": routine.total_price <= profile.budget * 1.15,
        "hard_violations": [_viol(v) for v in routine.hard_violations],
        "avoided": [{"action": a.action, "rule_id": a.rule_id, "severity": a.severity, "mechanism": a.mechanism,
                     "classes": f"{a.class_a} × {a.class_b}",
                     "products": [a.product_a.split("::")[-1], a.product_b.split("::")[-1]]} for a in routine.avoided],
        "cautions": [_viol(v) for v in routine.cautions],
        "score_decomposition": decomp, "explanation_source": src, "latency_ms": {k: round(v, 1) for k, v in t.items()},
        "backend": store.backend,
    }


def _viol(v):
    return {"kind": v.kind, "severity": v.severity, "rule_id": v.rule_id, "mechanism": v.mechanism,
            "citation": getattr(v, "citation", ""), "classes": f"{v.class_a} × {v.class_b}".strip(" ×"),
            "products": [p.split("::")[-1] for p in (v.product_a, v.product_b) if p]}
