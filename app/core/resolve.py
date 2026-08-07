"""Open-world resolution ladder (BUILD_PLAN §5.5). Turns a free-text "product I
already own" into a function vector the engine can reason about — WITHOUT requiring
it to be in the catalogue. The engine is catalogue-agnostic; the catalogue is just
one convenient source of function vectors.

Ladder (first hit wins):
  1 fuzzy name+brand match (rapidfuzz)        -> verified, full conflict checking
  2 semantic match on product embeddings      -> verified, full conflict checking
  3 user pastes the INCI list from the box    -> user_supplied, full conflict checking
  4 LLM/name inference of likely actives       -> INFERRED, conflict checking DISABLED
  5 user selects functional classes manually  -> manual, partial (flagged)

Hard rule (§5.5): NEVER make a safety claim on LLM-inferred ingredients. At Tier 4
`conflict_checkable` is False and the engine treats the product as conflict-neutral.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from rapidfuzz import fuzz, process

from app.core.ingredients import present_classes

# A confident wrong match produces confident wrong safety advice (the §6.3b failure).
# token_sort_ratio (not WRatio) is used deliberately: WRatio's token-set component gives
# ~85 to ANY product sharing a word (e.g. Nivea -> a random "Curl Cream"), so it can't
# separate a real match from garbage. token_sort_ratio scores off-catalogue names 56-70
# and real matches 81-97 — a clean gap — so a cutoff of 80 rejects the spurious ones.
SCORER = fuzz.token_sort_ratio
FUZZY_CUTOFF = 80       # 0-100
SEMANTIC_CUTOFF = 0.72  # cosine

# name-keyword inference for Tier 4 (used when there's no Gemini key). Deliberately
# crude — its output is LOW confidence and never used for conflict checking.
_NAME_ACTIVE = {
    "retinoid": ["retinol", "retinal", "retinoid", "granactive"],
    "vitamin_c_laa": ["vitamin c", "ascorbic", "l-aa", "15% c", "c serum"],
    "vitamin_c_derivative": ["ascorbyl", "ethyl ascorb"],
    "aha": ["glycolic", "lactic", "mandelic", "aha", "peeling"],
    "bha": ["salicylic", "bha"],
    "niacinamide": ["niacinamide"],
    "azelaic_acid": ["azelaic"],
    "benzoyl_peroxide": ["benzoyl"],
    "peptide": ["peptide", "matrixyl"],
    "hydroquinone": ["hydroquinone"],
    "uv_filter_mineral": ["mineral sunscreen", "zinc"],
    "humectant": ["hyaluronic", "hydrating"],
}


@dataclass
class Ctx:
    names: list           # [(product_id, "brand — name")]
    classes: dict         # id -> frozenset
    price: dict           # id -> float|None
    slot: dict            # id -> str|None
    ingredients: dict     # id -> raw ingredient string (for full-fidelity classes)


@dataclass
class Resolved:
    query: str
    name: str
    tier: int
    method: str
    confidence: str          # verified | user_supplied | inferred | manual
    conflict_checkable: bool
    classes: frozenset
    price: float | None
    slot: str | None
    matched_id: str | None = None
    note: str = ""
    score: float = 0.0


def _infer_slot(name: str, classes: frozenset) -> str:
    n = name.lower()
    if "cleanser" in n or "wash" in n or "cleansing" in n:
        return "cleanser"
    if any(w in n for w in ("spf", "sunscreen", "sun ")) or (classes & {"uv_filter_mineral", "uv_filter_chemical"}):
        return "spf"
    if any(w in n for w in ("moistur", "cream", "lotion", "gel-cream", "hydrator")):
        return "moisturizer"
    return "treatment"


def _name_infer(name: str) -> frozenset:
    n = name.lower()
    return frozenset(c for c, kws in _NAME_ACTIVE.items() if any(k in n for k in kws))


def resolve(query: str, ctx: Ctx, pasted: str | None = None, manual: list | None = None,
            emb=None, model=None) -> Resolved:
    q = query.strip()

    # Tier 3 — user pasted INCI (authoritative, full checking)
    if pasted and pasted.strip():
        cls = present_classes(pasted, None)
        return Resolved(q, q or "pasted product", 3, "ingredients", "user_supplied", True,
                        cls, None, _infer_slot(q, cls), note="Resolved from your pasted ingredient list.")

    # Tier 5 — manual class selection (flagged, partial)
    if manual:
        cls = frozenset(manual)
        return Resolved(q, q, 5, "manual", "manual", True, cls, None, _infer_slot(q, cls),
                        note="Using the functional classes you selected — partial, unverified.")

    # Tier 1 — fuzzy name+brand
    if ctx.names:
        choices = {pid: nm for pid, nm in ctx.names}
        best = process.extractOne(q, choices, scorer=SCORER)
        if best and best[1] >= FUZZY_CUTOFF:
            nm, sc, pid = best[0], best[1], best[2]
            cls = present_classes(ctx.ingredients.get(pid, ""), None)
            return Resolved(q, nm, 1, "fuzzy", "verified", True, cls, ctx.price.get(pid),
                            ctx.slot.get(pid) or _infer_slot(nm, cls), pid,
                            f"Matched to catalogue product (fuzzy {sc:.0f}%).", sc)

    # Tier 2 — semantic match on embeddings
    if emb is not None and model is not None and ctx.names:
        qv = model.encode([q], normalize_embeddings=True)[0]
        ids = [pid for pid, _ in ctx.names if pid in emb]
        sims = np.array([qv @ emb[pid] for pid in ids])
        j = int(sims.argmax())
        if sims[j] >= SEMANTIC_CUTOFF:
            pid = ids[j]
            nm = dict(ctx.names)[pid]
            cls = present_classes(ctx.ingredients.get(pid, ""), None)
            return Resolved(q, nm, 2, "semantic", "verified", True, cls, ctx.price.get(pid),
                            ctx.slot.get(pid) or _infer_slot(nm, cls), pid,
                            f"Matched to catalogue product (semantic {sims[j]:.2f}).", float(sims[j]))

    # Tier 4 — name inference (LOW confidence, conflict checking DISABLED)
    cls = _name_infer(q)
    return Resolved(q, q, 4, "inferred", "inferred", False, cls, None, _infer_slot(q, cls),
                    note="We couldn't verify this product's ingredients. Conflict checking is "
                         "unavailable for it — please check manually.")
