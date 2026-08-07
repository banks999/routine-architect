"""Conflict engine (BUILD_PLAN §4). Given products and a session assignment,
return the rule violations — with rule id, severity, verbatim mechanism, citation,
and the two products involved.

Operates on functional CLASSES, never raw ingredient strings, and never invents a
safety claim: every message comes verbatim from conflicts.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Protocol

import yaml

_YAML = Path(__file__).resolve().parent.parent / "config" / "conflicts.yaml"

SESSIONS = ("AM", "PM")
PHOTOSENSITISERS = frozenset({"retinoid", "aha", "bha"})
UV_FILTERS = frozenset({"uv_filter_chemical", "uv_filter_mineral"})


class ProductLike(Protocol):
    id: str
    name: str
    price: float
    classes: frozenset  # functional classes present (top-15 INCI)


@dataclass(frozen=True)
class Product:
    """Minimal concrete ProductLike for tests / anchors."""
    id: str
    name: str
    price: float
    classes: frozenset
    function_vector: dict = field(default_factory=dict)


@dataclass
class Rule:
    id: str
    a: str
    b: str
    severity: str
    mechanism: str
    citation: str


@dataclass
class Placement:
    id: str
    classes: frozenset
    allowed: frozenset
    hard: bool
    reason: str
    terminal: bool = False
    mandatory_if_photosensitiser: bool = False


@dataclass
class Violation:
    kind: str            # conflict | placement | spf
    severity: str        # hard | soft | contested
    rule_id: str
    mechanism: str
    citation: str
    class_a: str
    class_b: str
    product_a: str       # "id::name"
    product_b: str
    session: str


@lru_cache(maxsize=1)
def _load():
    raw = yaml.safe_load(open(_YAML, encoding="utf-8"))
    rules = [Rule(**r) for r in raw["rules"]]
    placement = [Placement(id=p["id"], classes=frozenset(p["classes"]),
                           allowed=frozenset(p["allowed"]), hard=p["hard"], reason=p["reason"],
                           terminal=p.get("terminal", False),
                           mandatory_if_photosensitiser=p.get("mandatory_if_photosensitiser", False))
                 for p in raw["placement"]]
    return rules, placement


def rules() -> list[Rule]:
    return _load()[0]


def placement_rules() -> list[Placement]:
    return _load()[1]


def _tag(p: ProductLike) -> str:
    return f"{p.id}::{p.name}"


def rule_between(ca: frozenset, cb: frozenset) -> list[Rule]:
    """Rules fired by two DIFFERENT products carrying class sets ca, cb."""
    hits = []
    for r in rules():
        if (r.a in ca and r.b in cb) or (r.a in cb and r.b in ca):
            hits.append(r)
    return hits


def is_hard_conflict(ca: frozenset, cb: frozenset) -> Rule | None:
    for r in rule_between(ca, cb):
        if r.severity == "hard":
            return r
    return None


def _session_violations(products: list[ProductLike], session: str,
                        severities: tuple) -> list[Violation]:
    out = []
    for i in range(len(products)):
        for j in range(i + 1, len(products)):
            pi, pj = products[i], products[j]
            for r in rule_between(pi.classes, pj.classes):
                if r.severity not in severities:
                    continue
                # orient product_a to the one holding class r.a
                a_holder, b_holder = (pi, pj) if r.a in pi.classes else (pj, pi)
                out.append(Violation("conflict", r.severity, r.id, r.mechanism, r.citation,
                                     r.a, r.b, _tag(a_holder), _tag(b_holder), session))
    return out


def _placement_violations(products: list[ProductLike], assignment: dict) -> list[Violation]:
    out = []
    for p in products:
        sess = assignment[p.id]
        for pl in placement_rules():
            shared = pl.classes & p.classes
            if not shared:
                continue
            bad = {s for s in sess if s not in pl.allowed}
            if bad:
                sev = "hard" if pl.hard else "soft"
                out.append(Violation("placement", sev, pl.id, pl.reason, "",
                                     next(iter(shared)), "", _tag(p), "", ",".join(sorted(bad))))
    return out


def _spf_violation(products: list[ProductLike], assignment: dict) -> list[Violation]:
    all_classes = frozenset().union(*(p.classes for p in products)) if products else frozenset()
    if not (all_classes & PHOTOSENSITISERS):
        return []
    am_has_uv = any(p.classes & UV_FILTERS for p in products if "AM" in assignment[p.id])
    if am_has_uv:
        return []
    p3 = next(pl for pl in placement_rules() if pl.id == "P3")
    return [Violation("spf", "hard", "P3", p3.reason, "", "uv_filter", "", "", "", "AM")]


def check(products: Iterable[ProductLike], assignment: dict,
          severities: tuple = ("hard", "soft", "contested")) -> list[Violation]:
    """products + assignment(pid -> set of sessions) -> all violations."""
    products = list(products)
    out = []
    for s in SESSIONS:
        in_s = [p for p in products if s in assignment[p.id]]
        out += _session_violations(in_s, s, severities)
    out += [v for v in _placement_violations(products, assignment) if v.severity in severities]
    out += [v for v in _spf_violation(products, assignment) if v.severity in severities]
    return out
