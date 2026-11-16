"""Public-surface hardening: request validation, rate limiter, bounded cache.
Importing app.main loads the catalogue (a few seconds) but needs no Mongo/Redis/network."""
import asyncio

import pytest
from pydantic import ValidationError

from app.main import RoutineRequest, _Cache, _Limiter

OK = {"skin_type": "oily", "concerns": ["acne", "aging"], "budget_inr": 12000}


def test_valid_request_accepted_with_every_ui_exclusion():
    r = RoutineRequest(**OK, exclusions=["fragrance", "essential oils", "pregnancy-safe only", "alcohol"])
    assert len(r.exclusions) == 4


@pytest.mark.parametrize("bad", [
    {"skin_type": "alien"},
    {"concerns": []},
    {"concerns": ["laser"]},
    {"budget_inr": -5},
    {"budget_inr": 10**9},
    {"owned": ["x"] * 6},
    {"owned": ["x" * 3001]},
    {"exclude": ["P" * 41]},
])
def test_invalid_request_rejected(bad):
    with pytest.raises(ValidationError):
        RoutineRequest(**{**OK, **bad})


def test_misspelt_safety_filter_is_rejected_not_ignored():
    # The H+18 bug class: an unrecognised exclusion must fail loudly, never silently mean 'no filter'.
    for typo in ("pregnancy", "pregnancy-safe", "Pregnancy-safe only", "fragrance-free"):
        with pytest.raises(ValidationError):
            RoutineRequest(**OK, exclusions=[typo])


def test_limiter_per_ip_and_global():
    lim = _Limiter(per_ip=3, global_cap=5)
    assert [lim.allow("a") for _ in range(4)] == [True, True, True, False]   # per-IP cap
    assert lim.allow("b") and lim.allow("b")                                  # other IP unaffected
    assert not lim.allow("c")                                                 # global cap (5) reached


def test_limiter_window_expires():
    lim = _Limiter(per_ip=1, global_cap=10, window=0.05)
    assert lim.allow("a") and not lim.allow("a")
    import time; time.sleep(0.06)
    assert lim.allow("a")


def test_memory_cache_is_bounded_lru():
    async def go():
        c = _Cache(); c.MAX_MEM = 3
        for i in range(5):
            await c.set(f"k{i}", i)
        assert list(c.mem) == ["k2", "k3", "k4"]
        assert await c.get("k2") == 2          # touching k2 makes it most-recent
        await c.set("k5", 5)
        assert "k3" not in c.mem and "k2" in c.mem
    asyncio.run(go())
