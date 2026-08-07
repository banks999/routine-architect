"""Routine solver (BUILD_PLAN §5). Beam search over 5 slots
(cleanser, treatment_A, treatment_B, moisturizer, spf) allocated across AM/PM.

Objective:  Σ relevance + α·concern_coverage − β·function_redundancy − γ·budget_overrun
Constraints: no HARD conflict within a session · placement rules · budget ceiling ·
             SPF mandatory if a photosensitiser is present.

The thesis in one function: conflicting products are not excluded, they are
SCHEDULED into separate AM/PM sessions. Every returned routine reports what it did
about each conflict a naive recommender would have shipped.

The naive greedy baseline is callable from the same interface (§6 comparison).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.core import conflicts as cf

# Base essentials first so budget is reserved for them (SPF is mandatory and must not
# be starved by an expensive serum); the two treatment slots then compete for the rest.
SLOT_ORDER = ("cleanser", "moisturizer", "spf", "treatment_A", "treatment_B")
BOTH = frozenset({"AM", "PM"})

# objective weights — heuristic (no validation budget to tune; the constraints do
# the safety work, these only shape preference among *safe* routines).
ALPHA, BETA, GAMMA, SOFT_PEN = 1.0, 0.5, 1.0, 0.3
BUDGET_SLACK = 1.15

# concern -> functional classes that address it (shared with the eval profiles)
CONCERN_CLASSES = {
    "acne": {"bha", "benzoyl_peroxide", "sulfur", "azelaic_acid"},
    "aging": {"retinoid", "peptide"},
    "dark_spots": {"vitamin_c_laa", "vitamin_c_derivative", "brightening_other", "azelaic_acid"},
    "texture": {"aha", "bha", "pha"},
    "dullness": {"vitamin_c_laa", "vitamin_c_derivative", "aha"},
    "redness": {"azelaic_acid", "soothing"},
    "dryness": {"humectant", "ceramide_barrier", "occlusive"},
}


@lru_cache(maxsize=1)
def _active_classes() -> frozenset:
    y = yaml.safe_load(open(Path(__file__).resolve().parent.parent / "config" /
                             "functional_classes.yaml", encoding="utf-8"))
    return frozenset(k for k, v in y.items() if v.get("group") == "actives")


@dataclass(frozen=True)
class Candidate:
    id: str
    name: str
    price: float
    classes: frozenset
    function_vector: dict
    relevance: float
    slot: str  # 'cleanser' | 'treatment' | 'moisturizer' | 'spf'


@dataclass(frozen=True)
class Placement:
    cand: Candidate
    slot: str          # cleanser | treatment_A | treatment_B | moisturizer | spf
    sessions: frozenset


@dataclass
class AvoidedConflict:
    action: str        # scheduled_apart | product_swapped | excluded_no_alternative
    rule_id: str
    severity: str
    mechanism: str
    class_a: str
    class_b: str
    product_a: str
    product_b: str


@dataclass
class Profile:
    concerns: list
    budget: float
    skin: str | None = None


@dataclass
class Routine:
    placements: list
    total_price: float
    score: float
    hard_violations: list = field(default_factory=list)
    cautions: list = field(default_factory=list)   # soft + contested, surfaced not blocked
    avoided: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def assignment(self) -> dict:
        return {pl.cand.id: set(pl.sessions) for pl in self.placements}

    def session(self, s: str) -> list:
        return [pl for pl in self.placements if s in pl.sessions]


# ---------------- feasibility ----------------
def _hard_allowed(classes: frozenset) -> set:
    allowed = {"AM", "PM"}
    for pl in cf.placement_rules():
        if pl.hard and (pl.classes & classes):
            allowed &= pl.allowed
    return allowed


def feasible_sessions(cand: Candidate, slot: str) -> list:
    """Which session-sets this candidate may occupy in this slot (placement-hard)."""
    allowed = _hard_allowed(cand.classes)
    if slot in ("cleanser", "moisturizer"):
        return [BOTH] if BOTH <= allowed else []      # applied AM+PM; must clear both
    if slot == "spf":
        return [frozenset({"AM"})] if "AM" in allowed else []
    return [frozenset({s}) for s in ("AM", "PM") if s in allowed]  # treatment: single session


def _hard_conflict(basket: list, new: Placement) -> bool:
    for s in new.sessions:
        for pl in basket:
            if s in pl.sessions and cf.is_hard_conflict(pl.cand.classes, new.cand.classes):
                return True
    return False


# ---------------- objective ----------------
def _covered(placements: list, concerns: list) -> float:
    if not concerns:
        return 0.0
    present = frozenset().union(*(pl.cand.classes for pl in placements)) if placements else frozenset()
    hit = sum(1 for c in concerns if CONCERN_CLASSES.get(c, set()) & present)
    return hit / len(concerns)


def _redundancy(placements: list) -> int:
    tx = [pl for pl in placements if pl.slot.startswith("treatment")]
    if len(tx) < 2:
        return 0
    return len(tx[0].cand.classes & tx[1].cand.classes & _active_classes())


def _soft_penalty(placements: list) -> int:
    assign = {pl.cand.id: set(pl.sessions) for pl in placements}
    n = 0
    for pl in placements:
        for prule in cf.placement_rules():
            if not prule.hard and (prule.classes & pl.cand.classes):
                if any(s not in prule.allowed for s in pl.sessions):
                    n += 1
    # soft/contested within-session conflicts
    for s in cf.SESSIONS:
        in_s = [pl.cand for pl in placements if s in pl.sessions]
        for v in cf._session_violations(in_s, s, ("soft", "contested")):
            n += 1
    return n


def _total_price(placements: list) -> float:
    return sum(pl.cand.price for pl in placements)


def objective(placements: list, profile: Profile, include_soft: bool = True) -> float:
    over = max(0.0, _total_price(placements) - profile.budget) / max(profile.budget, 1e-9)
    score = (sum(pl.cand.relevance for pl in placements)
             + ALPHA * _covered(placements, profile.concerns)
             - BETA * _redundancy(placements)
             - GAMMA * over)
    # soft penalties re-run conflict checks — the beam-search hotspot. They only nudge
    # preference among already-safe routines, so compute them once at final selection.
    if include_soft:
        score -= SOFT_PEN * _soft_penalty(placements)
    return score


# ---------------- solve ----------------
def _pool(candidates_by_slot: dict, slot: str) -> list:
    """Prefer a slot-specific pool (e.g. concern-specific treatment_A / treatment_B);
    fall back to the shared 'treatment' pool."""
    if slot in candidates_by_slot:
        return candidates_by_slot[slot]
    return candidates_by_slot["treatment" if slot.startswith("treatment") else slot]


def _finalize(placements: list, profile: Profile) -> Routine:
    prods = [pl.cand for pl in placements]
    assign = {pl.cand.id: set(pl.sessions) for pl in placements}
    hard = [v for v in cf.check(prods, assign, ("hard",))]
    cautions = [v for v in cf.check(prods, assign, ("soft", "contested"))]
    notes = []
    if frozenset().union(*(p.classes for p in prods)) & cf.PHOTOSENSITISERS:
        notes.append("SPF is mandatory here: the routine contains a photosensitising active "
                     "(retinoid/AHA/BHA). Included as the final AM step.")
    return Routine(placements, _total_price(placements), objective(placements, profile),
                   hard_violations=hard, cautions=cautions, notes=notes)


def solve(candidates_by_slot: dict, profile: Profile,
          beam_width: int = 20, cand_k: int = 20, enforce_conflicts: bool = True,
          pinned: list | None = None) -> Routine:
    """enforce_conflicts=False disables the constraint layer (the §6 sanity test:
    recommendations must still be good/personalised without it — the ranker, not the
    conflict engine, is what makes them good).

    pinned = products the user already owns (as Placements). They pre-seed every beam:
    the solver builds AROUND them (schedules its picks to avoid conflicting with them in
    a session, and its redundancy penalty discourages duplicating their function). Their
    price is not charged to the budget (already owned) and their slot is not re-filled."""
    pinned = pinned or []
    filled = {pl.slot for pl in pinned}
    beams = [list(pinned)]
    for slot in SLOT_ORDER:
        if slot in filled:
            continue
        pool = _pool(candidates_by_slot, slot)[:cand_k]
        nxt = []
        for basket in beams:
            used = {pl.cand.id for pl in basket}
            for cand in pool:
                if cand.id in used:
                    continue
                for sess in feasible_sessions(cand, slot):
                    pl = Placement(cand, slot, sess)
                    if enforce_conflicts and _hard_conflict(basket, pl):
                        continue
                    if _total_price(basket) + cand.price > profile.budget * BUDGET_SLACK:
                        continue
                    nxt.append(basket + [pl])
        if not nxt:  # slot could not be filled under constraints
            break
        beams = sorted(nxt, key=lambda b: objective(b, profile, include_soft=False),
                       reverse=True)[:beam_width]

    best = max(beams, key=lambda b: objective(b, profile))  # full objective (with soft)
    routine = _finalize(best, profile)
    routine.avoided = _classify_avoidance(routine, naive_greedy(candidates_by_slot, profile))
    return routine


def naive_greedy(candidates_by_slot: dict, profile: Profile) -> Routine:
    """Baseline: top-relevance per slot, BOTH treatments defaulted to AM, no scheduling."""
    placements = []
    tA = _pool(candidates_by_slot, "treatment_A")[0]
    tB_pool = _pool(candidates_by_slot, "treatment_B")
    tB = next((c for c in tB_pool if c.id != tA.id), tB_pool[0])
    picks = {
        "cleanser": (candidates_by_slot["cleanser"][0], BOTH),
        "treatment_A": (tA, frozenset({"AM"})),
        "treatment_B": (tB, frozenset({"AM"})),
        "moisturizer": (candidates_by_slot["moisturizer"][0], BOTH),
        "spf": (candidates_by_slot["spf"][0], frozenset({"AM"})),
    }
    for slot, (cand, sess) in picks.items():
        placements.append(Placement(cand, slot, sess))
    prods = [pl.cand for pl in placements]
    assign = {pl.cand.id: set(pl.sessions) for pl in placements}
    return Routine(placements, _total_price(placements), objective(placements, profile),
                   hard_violations=cf.check(prods, assign, ("hard",)),
                   cautions=cf.check(prods, assign, ("soft", "contested")))


def _tag(c: Candidate) -> str:
    return f"{c.id}::{c.name}"


def budget_greedy(candidates_by_slot: dict, profile: Profile) -> Routine:
    """Stronger baseline: what a competent engineer builds WITHOUT a solver. Split the
    budget evenly across the 5 slots, take the top-ranked product that fits each slot's
    share (cheapest available if none fits). No conflict awareness, no AM/PM scheduling
    (both treatments default to AM) — isolates budget (a per-item patch) from conflict
    scheduling (a joint constraint that needs the search)."""
    share = profile.budget / 5.0
    sessions = {"cleanser": BOTH, "treatment_A": frozenset({"AM"}), "treatment_B": frozenset({"AM"}),
                "moisturizer": BOTH, "spf": frozenset({"AM"})}
    placements, used = [], set()
    for slot in SLOT_ORDER:
        pool = [c for c in _pool(candidates_by_slot, slot) if c.id not in used]
        cand = next((c for c in pool if c.price <= share), None) or (min(pool, key=lambda c: c.price) if pool else None)
        if cand is None:
            continue
        used.add(cand.id)
        placements.append(Placement(cand, slot, sessions[slot]))
    prods = [pl.cand for pl in placements]
    assign = {pl.cand.id: set(pl.sessions) for pl in placements}
    return Routine(placements, _total_price(placements), objective(placements, profile),
                   hard_violations=cf.check(prods, assign, ("hard",)),
                   cautions=cf.check(prods, assign, ("soft", "contested")))


def _classify_avoidance(solver_r: Routine, naive_r: Routine) -> list:
    """What the solver DID about each hard conflict a naive picker would ship.

    Reported from the SOLVER's own routine (product identities can legitimately
    differ from naive's, so comparing IDs alone is misleading):
      scheduled_apart  — both conflicting actives kept, put in separate AM/PM sessions
      product_swapped  — that active-pair conflict is gone from the routine because the
                         solver chose a different, non-conflicting product for a concern
      excluded_no_alternative — a treatment slot left unfilled (no safe/affordable option)
    """
    pls = solver_r.placements
    out, scheduled_pairs = [], set()

    # (a) latent hard conflicts inside the solver's routine -> scheduled apart
    for i in range(len(pls)):
        for j in range(i + 1, len(pls)):
            r = cf.is_hard_conflict(pls[i].cand.classes, pls[j].cand.classes)
            if r and not (pls[i].sessions & pls[j].sessions):
                scheduled_pairs.add(frozenset((r.a, r.b)))
                out.append(AvoidedConflict("scheduled_apart", r.id, r.severity, r.mechanism,
                                           r.a, r.b, _tag(pls[i].cand), _tag(pls[j].cand)))

    # (b) hard conflicts the naive routine shipped that are NOT in the solver routine
    n_treat = sum(1 for pl in pls if pl.slot.startswith("treatment"))
    seen = set()
    for v in naive_r.hard_violations:
        if v.kind != "conflict":
            continue
        cpair = frozenset((v.class_a, v.class_b))
        if cpair in scheduled_pairs or cpair in seen:
            continue
        seen.add(cpair)
        action = "excluded_no_alternative" if n_treat < 2 else "product_swapped"
        out.append(AvoidedConflict(action, v.rule_id, v.severity, v.mechanism,
                                   v.class_a, v.class_b, v.product_a, v.product_b))
    return out
