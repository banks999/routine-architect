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
from app.core import resolve as rz
from app.core import retrieval as ret
from app.core import solver as sv
from app.core.ingredients import present_classes
from app.db.store import store

ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOYED = {"semantic": 0.3, "cf": 0.5, "rating": 0.1, "skin": 0.1}

_prod = pd.read_parquet(ROOT / "data" / "processed" / "products_enriched.parquet")
_priors = pd.read_parquet(ROOT / "data" / "processed" / "rank_priors.parquet").set_index("product_id")
_themes_path = ROOT / "data" / "processed" / "product_themes.parquet"
THEMES = ({r.product_id: json.loads(r.themes) for r in pd.read_parquet(_themes_path).itertuples()}
          if _themes_path.exists() else {})
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

# catalogue view for the open-world resolver (§5.5)
CTX = rz.Ctx(
    names=[(r.product_id, f"{r.brand_name} — {r.product_name}") for r in _prod.itertuples()],
    classes=CLASSES,
    price={r.product_id: (float(r.price_inr) if pd.notna(r.price_inr) else None) for r in _prod.itertuples()},
    slot={r.product_id: (r.slot if pd.notna(r.slot) else None) for r in _prod.itertuples()},
    ingredients={r.product_id: (r.ingredients if isinstance(r.ingredients, str) else "") for r in _prod.itertuples()},
)


def _pin_session(slot: str, classes: frozenset) -> frozenset:
    if slot in ("cleanser", "moisturizer"):
        return sv.BOTH
    if slot == "spf":
        return frozenset({"AM"})
    allowed = sv._hard_allowed(classes)
    pref = "PM" if (classes & cf.PHOTOSENSITISERS) else "AM"
    return frozenset({pref if pref in allowed else next(iter(allowed))})


def _resolve_owned(owned: list):
    """Resolve each owned product via the ladder, pin the resolvable ones into the basket."""
    pinned, meta, resolutions = [], {}, []
    t_idx = 0
    for q in owned:
        r = rz.resolve(q, CTX, emb=EMB, model=ret.get_model())
        resolutions.append(r)
        slot = r.slot or "treatment"
        if slot == "treatment":
            if t_idx >= 2:      # only two treatment slots; pin the first two
                continue
            slot = ("treatment_A", "treatment_B")[t_idx]; t_idx += 1
        cls = r.classes if r.conflict_checkable else frozenset()   # Tier 4 -> conflict-neutral
        cid = r.matched_id or f"owned::{q}"
        cand = sv.Candidate(cid, r.name, 0.0, cls, {}, 0.0, slot)   # price 0 = already owned
        pinned.append(sv.Placement(cand, slot, _pin_session(slot, cls)))
        meta[cid] = {"owned": True, "confidence": r.confidence, "tier": r.tier, "method": r.method,
                     "conflict_checkable": r.conflict_checkable, "note": r.note}
    return pinned, meta, resolutions


def _z(a):
    a = np.asarray(a, "float32")
    return (a - a.mean()) / a.std() if a.std() > 1e-9 else np.zeros_like(a)


def _cands(query, slot, skin, exclude=frozenset()):
    ids = [h["product_id"] for h in ret.retrieve(query, "treatment" if slot.startswith("treatment") else slot, top_k=40)
           if h["product_id"] in EMB and h["product_id"] in _priors.index and h["product_id"] not in exclude]
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


def build_candidates(profile: sv.Profile, exclude=frozenset()):
    c1, c2 = profile.concerns[0], profile.concerns[-1]
    return {"cleanser": _cands(BASE_Q["cleanser"], "cleanser", profile.skin, exclude),
            "moisturizer": _cands(BASE_Q["moisturizer"], "moisturizer", profile.skin, exclude),
            "spf": _cands(BASE_Q["spf"], "spf", profile.skin, exclude),
            "treatment_A": _cands(CONCERN_QUERY.get(c1, c1), "treatment_A", profile.skin, exclude),
            "treatment_B": _cands(CONCERN_QUERY.get(c2, c2), "treatment_B", profile.skin, exclude)}


_PHRASE_FIX = {"long way": "a little goes a long way", "little goes": "a little goes a long way",
               "goes long": "a little goes a long way", "little goes long": "a little goes a long way"}
_WEAK = {"skin looks", "skin feeling", "skin care", "skincare routine", "really like", "started using",
         "skin tone", "smells like", "every other", "prone skin", "would recommend", "highly recommend",
         "skin type", "morning and", "night and", "well under", "the day"}
# ALL skin-type words -> dropping these kills both the tautology ("oily" theme for an oily
# user) AND the cross-cohort leak ("dry" theme for an oily user), for everyone. "sensitive"
# included: it's a skin descriptor we don't model as a profile, so a mined "sensitive skin"
# theme has no user to attribute to — and the LLM was converting it into "YOU have sensitive
# skin" for every user (a faithfulness failure surfaced by §6.5).
_SKIN_WORDS = {"oily", "oil", "greasy", "oiliness", "shiny", "dry", "dryness", "flaky", "flaking",
               "combination", "combo", "normal", "sensitive", "sensitivity", "sensitized"}
_CONCERN_ECHO = {
    "acne": {"acne", "breakout", "breakouts", "blemish", "blemishes", "pimple", "pimples"},
    "aging": {"aging", "ageing", "wrinkle", "wrinkles", "fine line", "fine lines", "anti aging"},
    "dark_spots": {"dark spot", "dark spots", "hyperpigmentation", "discoloration"},
    "dullness": {"dull", "dullness"},
    "texture": {"texture", "rough", "bumpy"},
    "redness": {"redness"},
    "dryness": {"dry", "dryness", "flaky"},
    "oiliness": {"oily", "oil", "greasy", "shiny"},
}
THIN_SKIN = 8  # below this many matched-skin reviews, label the all-reviewer fallback


def _echo_words(concerns) -> set:
    e = set(_SKIN_WORDS)
    for c in concerns:
        e |= _CONCERN_ECHO.get(c, set())
    return e


def _themes_for(pid: str, skin: str, concerns, k: int = 3):
    """Returns (themes, fallback, n_matched_skin). Drops themes that restate the user's
    profile (skin type/synonyms + stated concerns) or any skin-type word (no cross-cohort
    leak) or pure filler. When same-skin reviews are thin (<THIN_SKIN), ranks by overall df
    and flags fallback so the explanation can say so honestly."""
    data = THEMES.get(pid) or {}
    ts, totals = data.get("themes", []), data.get("skin_totals", {})
    n_skin = totals.get(skin, 0)
    echo = _echo_words(concerns)

    def ok(ph):
        return ph not in _WEAK and not any(w in ph for w in echo)
    cand = [t for t in ts if ok(t["phrase"])]

    fallback = n_skin < THIN_SKIN
    if fallback:
        ranked = sorted(cand, key=lambda t: t.get("df", 0), reverse=True)
    else:
        ranked = sorted(cand, key=lambda t: (t.get("skins", {}).get(skin, 0), t.get("df", 0)), reverse=True)

    out = []
    for t in ranked:
        p = _PHRASE_FIX.get(t["phrase"], t["phrase"])
        if any(p in q or q in p for q in out):
            continue
        out.append(p)
        if len(out) >= k:
            break
    return out, fallback, n_skin


def _join(xs: list[str]) -> str:
    xs = [f"“{x}”" for x in xs]
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _template_explain(skin, themes, fallback, n_skin, classes):
    bits = []
    if themes:
        if n_skin == 0:
            bits.append(f"Reviewers most often mention {_join(themes)}.")
        elif fallback:
            bits.append(f"Only {n_skin} reviewer{'s' if n_skin != 1 else ''} with {skin} skin, so across "
                        f"all reviewers: most mention {_join(themes)}.")
        else:
            bits.append(f"Reviewers with {skin} skin most often mention {_join(themes)} "
                        f"(from {n_skin} matched 4★+ reviews).")
    actives = sorted(classes & sv._active_classes())
    if actives:
        bits.append("Active(s): " + ", ".join(a.replace("_", " ") for a in actives) + ".")
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
        prompt = ("For each product, write ONE friendly sentence on why it fits this user, grounded ONLY in "
                  "the provided review themes, matched-skin snippets and actives. Reference what reviewers with "
                  "the user's skin type actually said. Do NOT invent ingredients or make safety/medical claims. "
                  "Return ONLY JSON {product_id: sentence}.\n" + json.dumps(context)[:7000])
        r = genai.GenerativeModel("gemini-flash-lite-latest").generate_content(
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
    context, tmpl, ground = [], {}, {}
    for pl in placements:
        _, snip = await store.review_snippets(pl.cand.id, profile.skin, k=3)
        themes, fallback, n_skin = _themes_for(pl.cand.id, profile.skin, profile.concerns, k=3)
        ground[pl.cand.id] = {"themes": themes, "snippets": snip, "n_matched": n_skin, "fallback": fallback}
        tmpl[pl.cand.id] = _template_explain(profile.skin, themes, fallback, n_skin, pl.cand.classes)
        context.append({"product_id": pl.cand.id, "name": pl.cand.name,
                        "actives": sorted(pl.cand.classes & sv._active_classes()),
                        "themes": themes, "matched_skin_reviews": n_skin,
                        "snippets": [s["text"][:200] for s in snip]})
    gem = await _gemini_explain(context)
    source = "gemini" if gem else "template"
    whys = {pid: (gem.get(pid) if gem and gem.get(pid) else tmpl[pid]) for pid in tmpl}
    return whys, ground, source


def _card(pl, why, grounding, owned_meta=None):
    om = (owned_meta or {}).get(pl.cand.id)
    card = {"product_id": pl.cand.id, "slot": pl.slot, "name": pl.cand.name,
            "price_inr": pl.cand.price, "sessions": sorted(pl.sessions),
            "actives": sorted(pl.cand.classes & sv._active_classes()),
            "all_classes": sorted(pl.cand.classes), "relevance": round(pl.cand.relevance, 3),
            "why": why, "themes": grounding.get("themes", []),
            "n_matched_reviews": grounding.get("n_matched", 0), "grounding": grounding.get("snippets", [])}
    if om:  # a product the user already owns, pinned into the routine
        card.update(owned=True, confidence=om["confidence"], tier=om["tier"], method=om["method"],
                    conflict_checkable=om["conflict_checkable"], why=om["note"])
    else:
        m = META[pl.cand.id]
        card["highlights"] = m.highlights if pd.notna(m.highlights) else None
    return card


async def recommend(profile: sv.Profile, enforce_conflicts: bool = True, owned: list | None = None,
                    exclude: list | None = None) -> dict:
    t = {}
    pinned, owned_meta, resolutions = _resolve_owned(owned or [])
    t0 = time.perf_counter(); cands = build_candidates(profile, frozenset(exclude or [])); t["retrieval_and_rank_ms"] = (time.perf_counter()-t0)*1000
    t0 = time.perf_counter(); routine = sv.solve(cands, profile, enforce_conflicts=enforce_conflicts, pinned=pinned); t["solve_ms"] = (time.perf_counter()-t0)*1000
    t0 = time.perf_counter(); whys, ground, src = await _explain(routine.placements, profile); t["explain_ms"] = (time.perf_counter()-t0)*1000

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
        "am": [_card(p, whys[p.cand.id], ground[p.cand.id], owned_meta) for p in sorted(routine.session("AM"), key=lambda x: sv.SLOT_ORDER.index(x.slot))],
        "pm": [_card(p, whys[p.cand.id], ground[p.cand.id], owned_meta) for p in sorted(routine.session("PM"), key=lambda x: sv.SLOT_ORDER.index(x.slot))],
        "total_price_inr": routine.total_price, "within_budget": routine.total_price <= profile.budget * 1.15,
        "hard_violations": [_viol(v) for v in routine.hard_violations],
        "avoided": [_avoided(a, {pl.cand.id for pl in routine.placements}) for a in routine.avoided],
        "cautions": [_viol(v) for v in routine.cautions],
        "score_decomposition": decomp, "explanation_source": src, "latency_ms": {k: round(v, 1) for k, v in t.items()},
        "backend": store.backend,
        "resolutions": [{"query": r.query, "name": r.name, "tier": r.tier, "method": r.method,
                         "confidence": r.confidence, "conflict_checkable": r.conflict_checkable,
                         "classes": sorted(r.classes), "note": r.note} for r in resolutions],
    }


def _avoided(a, routine_ids: set) -> dict:
    """Action-typed, truthful wording for the 'conflicts avoided' panel. product_swapped
    products are NOT in the routine (that's the point of the swap), so name the avoided
    product and, when one of the pair survived in the routine, the surviving 'your' one."""
    pa_id, pa_name = a.product_a.split("::", 1)[0], a.product_a.split("::")[-1]
    pb_id, pb_name = a.product_b.split("::", 1)[0], a.product_b.split("::")[-1]
    d = {"action": a.action, "rule_id": a.rule_id, "severity": a.severity,
         "mechanism": a.mechanism, "classes": f"{a.class_a} × {a.class_b}"}
    if a.action == "scheduled_apart":
        d["detail"] = "Both kept — split across AM/PM."
        d["products"] = [pa_name, pb_name]
    elif a.action == "product_swapped":
        if pb_id in routine_ids:      # the surviving product is 'yours'; the other was avoided
            x, y = pa_name, pb_name
        elif pa_id in routine_ids:
            x, y = pb_name, pa_name
        else:
            x, y = pa_name, None
        d["detail"] = (f"We avoided {x} because it conflicts with your {y}." if y
                       else f"We avoided {x} — it conflicts with the top pick for another concern.")
    else:  # excluded_no_alternative
        d["detail"] = "No safe alternative found for this slot."
    return d


def _viol(v):
    return {"kind": v.kind, "severity": v.severity, "rule_id": v.rule_id, "mechanism": v.mechanism,
            "citation": getattr(v, "citation", ""), "classes": f"{v.class_a} × {v.class_b}".strip(" ×"),
            "products": [p.split("::")[-1] for p in (v.product_a, v.product_b) if p]}
