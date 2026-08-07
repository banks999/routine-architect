"""Prove the solver never ships a hard conflict, respects budget, and includes SPF
when a photosensitiser is placed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import conflicts as cf  # noqa: E402
from app.core import solver as sv  # noqa: E402


def _c(pid, slot, *classes, price=1000.0, rel=0.0):
    return sv.Candidate(pid, f"{slot}-{pid}", price, frozenset(classes), {}, rel, slot)


def _catalog():
    """A catalogue where the top-relevance picks conflict, forcing the solver to act."""
    return {
        "cleanser": [_c("cl1", "cleanser", "humectant", rel=2.0),
                     _c("cl2", "cleanser", "soothing", rel=1.0)],
        # two most-relevant treatments hard-conflict (retinoid x aha)
        "treatment": [_c("t_ret", "treatment", "retinoid", rel=3.0),
                      _c("t_aha", "treatment", "aha", rel=2.9),
                      _c("t_niac", "treatment", "niacinamide", rel=1.0),
                      _c("t_pep", "treatment", "peptide", rel=0.5)],
        "moisturizer": [_c("m1", "moisturizer", "humectant", "occlusive", rel=2.0),
                        _c("m2", "moisturizer", "ceramide_barrier", rel=1.0)],
        "spf": [_c("s1", "spf", "uv_filter_mineral", price=1500.0, rel=1.0)],
    }


def _profile(budget=8000.0):
    return sv.Profile(concerns=["aging", "texture"], budget=budget)


def test_no_hard_conflict_ever():
    r = sv.solve(_catalog(), _profile())
    assert r.hard_violations == [], r.hard_violations
    # the retinoid+aha pair the naive baseline conflicts on is resolved
    assert any(a.rule_id == "C1" for a in r.avoided)


def test_scheduled_apart_when_both_kept():
    r = sv.solve(_catalog(), _profile())
    # if both conflicting treatments were kept, they must be in different sessions
    ret = [pl for pl in r.placements if pl.cand.id == "t_ret"]
    aha = [pl for pl in r.placements if pl.cand.id == "t_aha"]
    if ret and aha:
        assert ret[0].sessions.isdisjoint(aha[0].sessions)
        assert any(a.action == "scheduled_apart" and a.rule_id == "C1" for a in r.avoided)


def test_budget_respected():
    r = sv.solve(_catalog(), _profile(budget=6000.0))
    assert r.total_price <= 6000.0 * sv.BUDGET_SLACK


def test_spf_present_with_photosensitiser():
    r = sv.solve(_catalog(), _profile())
    prods = [pl.cand for pl in r.placements]
    assert frozenset().union(*(p.classes for p in prods)) & cf.PHOTOSENSITISERS
    assert any(p.classes & cf.UV_FILTERS for pl in r.session("AM") for p in [pl.cand])
    assert not any(v.kind == "spf" for v in r.hard_violations)


def test_retinoid_scheduled_pm():
    r = sv.solve(_catalog(), _profile())
    ret = [pl for pl in r.placements if "retinoid" in pl.cand.classes]
    for pl in ret:
        assert pl.sessions == frozenset({"PM"}), "retinoid must be PM only (P1)"


def test_naive_baseline_does_conflict():
    """The baseline exists to fail: same interface, ships the conflict."""
    n = sv.naive_greedy(_catalog(), _profile())
    assert any(v.severity == "hard" and v.kind == "conflict" for v in n.hard_violations)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"ok  {name}")
    print("all solver tests passed")
