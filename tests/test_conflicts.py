"""Prove every conflict rule fires, placement is enforced, and SPF is mandated.

    python -m pytest tests/test_conflicts.py -q     (or just run the file)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import conflicts as cf  # noqa: E402


def _prod(pid, *classes, price=1000.0):
    return cf.Product(pid, f"prod-{pid}", price, frozenset(classes))


def test_every_rule_fires():
    """Two products carrying the rule's two classes must produce that rule id."""
    for r in cf.rules():
        a, b = _prod("A", r.a), _prod("B", r.b)
        assign = {"A": {"AM"}, "B": {"AM"}}  # same session
        fired = {v.rule_id for v in cf.check([a, b], assign)}
        assert r.id in fired, f"rule {r.id} ({r.a}x{r.b}) did not fire"


def test_severity_tiers_present():
    sev = {r.severity for r in cf.rules()}
    assert sev == {"hard", "soft", "contested"}, sev
    contested = {(r.a, r.b) for r in cf.rules() if r.severity == "contested"}
    assert ("vitamin_c_laa", "niacinamide") in contested
    # provenance must be in the user-facing mechanism string
    c16 = next(r for r in cf.rules() if r.id == "C16")
    assert "contested" in c16.mechanism.lower() and "1960s" in c16.mechanism


def test_same_class_needs_two_products():
    """retinoid x retinoid: one product with retinoid is NOT a conflict."""
    one = _prod("A", "retinoid")
    assert not [v for v in cf.check([one], {"A": {"PM"}}) if v.kind == "conflict"]
    two = [_prod("A", "retinoid"), _prod("B", "retinoid")]
    fired = {v.rule_id for v in cf.check(two, {"A": {"PM"}, "B": {"PM"}})}
    assert "C6" in fired


def test_scheduling_apart_clears_hard_conflict():
    """The whole thesis: same session = conflict, split AM/PM = clean."""
    ret, aha = _prod("A", "retinoid"), _prod("B", "aha")
    same = cf.check([ret, aha], {"A": {"PM"}, "B": {"PM"}}, ("hard",))
    apart = cf.check([ret, aha], {"A": {"PM"}, "B": {"AM"}}, ("hard",))
    assert any(v.rule_id == "C1" for v in same)
    assert not [v for v in apart if v.kind == "conflict"]


def test_placement_retinoid_pm_only():
    ret = _prod("A", "retinoid")
    assert any(v.rule_id == "P1" and v.severity == "hard"
               for v in cf.check([ret], {"A": {"AM"}}))          # AM -> violation
    assert not any(v.kind == "placement" for v in cf.check([ret], {"A": {"PM"}}))


def test_spf_mandatory_with_photosensitiser():
    ret = _prod("A", "retinoid")
    moist = _prod("M", "humectant")
    # photosensitiser present, no UV filter anywhere -> SPF violation
    assert any(v.kind == "spf" for v in cf.check([ret, moist], {"A": {"PM"}, "M": {"AM", "PM"}}))
    # add a mineral sunscreen in AM -> satisfied
    spf = _prod("S", "uv_filter_mineral")
    assert not any(v.kind == "spf"
                   for v in cf.check([ret, moist, spf], {"A": {"PM"}, "M": {"AM", "PM"}, "S": {"AM"}}))


def test_uv_salicylate_not_bha():
    """Guard against the classic false positive already handled in ingredients.py."""
    uv = _prod("A", "uv_filter_chemical")
    ret = _prod("B", "retinoid")
    fired = {v.rule_id for v in cf.check([uv, ret], {"A": {"AM"}, "B": {"AM"}}, ("hard",))}
    assert "C2" not in fired  # would only fire if uv were misread as bha


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"ok  {name}")
    print("all conflict tests passed")
