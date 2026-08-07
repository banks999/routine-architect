"""INCI ingredient parsing + functional-class vectors (BUILD_PLAN §3.2/§3.3).

Pipeline for one raw ingredient field:
  1. unwrap the stringified single-element Python list -> one comma-joined string
  2. TRUNCATE at "+/-" or "May Contain" (colourant/CI section is not
     concentration-ordered; keeping it corrupts the positional potency proxy)
  3. split on comma
  4. normalise each token: strip organic '*' markers, parenthetical common names,
     backslash synonyms (Water\\Aqua\\Eau)
  5. positional weight w_i = 1/log2(i+2)  (INCI is descending-concentration ordered
     above 1%, so list position is a free relative-potency proxy)
  6. sum weights per functional class -> sparse function vector

This module is deliberately catalogue-agnostic: it turns ANY INCI string into a
function vector, whether the source is the Sephora catalogue or a user pasting the
list off the box (open-world Tier 3, §5.5).
"""
from __future__ import annotations

import ast
import math
import re
from functools import lru_cache
from pathlib import Path

import yaml

_CLASSES_PATH = Path(__file__).resolve().parent.parent / "config" / "functional_classes.yaml"

# Everything from these markers onward is the "+/- (may contain)" colourant list.
_TRUNCATE_RE = re.compile(r"\+/[-‐‑]|\bmay contain\b", re.IGNORECASE)
_PARENS_RE = re.compile(r"\([^)]*\)")
_ALPHA_RE = re.compile(r"[a-z]", re.IGNORECASE)


@lru_cache(maxsize=1)
def _load_classes() -> dict:
    with open(_CLASSES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def unwrap(raw: str) -> str:
    """Turn the stored `['Water, Glycerin*, ...']` into a plain comma string."""
    s = str(raw).strip()
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, (list, tuple)):
                return ", ".join(str(x) for x in parsed)
        except (ValueError, SyntaxError):
            s = s[1:-1]  # malformed quotes/backslashes -> strip brackets by hand
    return s.strip().strip("'\"")


def _normalise(token: str) -> str:
    """Canonical token for identity/display: parens + '*' + backslash synonyms out."""
    t = _PARENS_RE.sub(" ", token)
    t = t.replace("*", " ").replace("\\", " ")
    return re.sub(r"\s+", " ", t).strip()


def parse(raw: str) -> list[str]:
    """Raw ingredient field -> ordered list of normalised ingredient tokens.

    Truncates the colourant section BEFORE returning, so index == concentration rank.
    """
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return []
    text = unwrap(raw)
    text = _TRUNCATE_RE.split(text, maxsplit=1)[0]
    tokens = []
    for part in text.split(","):
        norm = _normalise(part)
        if len(norm) >= 3 and _ALPHA_RE.search(norm):  # drop empties / stray symbols
            tokens.append(norm)
    return tokens


def _match_classes(token_lower: str, classes: dict) -> list[str]:
    hits = []
    for name, spec in classes.items():
        inc = spec.get("include", [])
        if not any(kw in token_lower for kw in inc):
            continue
        if any(bad in token_lower for bad in spec.get("exclude", [])):
            continue
        hits.append(name)
    return hits


def function_vector(raw: str) -> dict[str, float]:
    """Ingredient field -> {functional_class: summed positional weight}."""
    classes = _load_classes()
    tokens = parse(raw)
    vec: dict[str, float] = {}
    for i, tok in enumerate(tokens):
        w = 1.0 / math.log2(i + 2)  # position 0 -> 1.0, decays down the list
        for cls in _match_classes(tok.lower(), classes):
            vec[cls] = vec.get(cls, 0.0) + w
    return vec


def present_classes(raw: str, max_pos: int | None = None) -> set[str]:
    """Functional classes present, optionally only within the first `max_pos`
    ingredients. `max_pos` is the "meaningful dose" cutoff: INCI ordering is only
    reliable above ~1%, so a conflict-relevant active should sit near the top of
    the list, not as a trace at position 40.
    """
    classes = _load_classes()
    toks = parse(raw)
    if max_pos is not None:
        toks = toks[:max_pos]
    out: set[str] = set()
    for t in toks:
        out.update(_match_classes(t.lower(), classes))
    return out


def is_parseable(raw: str, min_tokens: int = 5) -> bool:
    """Document-grade coverage: field yields >= min_tokens recognised ingredients."""
    return len(parse(raw)) >= min_tokens


def demo() -> None:
    """Self-check: the safety-critical matches and the truncation must hold."""
    real = ("['Water, Niacinamide, Glycolic Acid, Retinol, Ascorbic Acid, "
            "Salix Alba (Willow) Bark Extract, Ethylhexyl Salicylate, "
            "Zinc Oxide, Phenoxyethanol +/- May Contain: CI 77491, CI 77492']")
    toks = parse(real)
    v = function_vector(real)

    assert "ci 77491" not in " ".join(toks).lower(), "truncation failed: colourants leaked in"
    assert v.get("retinoid", 0) > 0, "missed retinoid"
    assert v.get("aha", 0) > 0, "missed AHA (glycolic)"
    assert v.get("vitamin_c_laa", 0) > 0, "missed L-AA"
    assert v.get("niacinamide", 0) > 0, "missed niacinamide"
    assert v.get("bha", 0) > 0, "missed BHA (willow/salix)"
    assert v.get("uv_filter_chemical", 0) > 0, "missed chemical UV filter"
    assert v.get("uv_filter_mineral", 0) > 0, "missed mineral UV filter"
    # ethylhexyl salicylate must NOT be counted as BHA salicylic acid:
    only_uv = function_vector("['Ethylhexyl Salicylate, Homosalate']")
    assert only_uv.get("bha", 0) == 0, "false positive: UV salicylate counted as BHA"
    # a vitamin-C derivative must NOT count as free L-AA:
    deriv = function_vector("['Water, 3-O-Ethyl Ascorbic Acid']")
    assert deriv.get("vitamin_c_laa", 0) == 0, "false positive: derivative counted as L-AA"
    assert deriv.get("vitamin_c_derivative", 0) > 0, "missed vitamin-C derivative"
    # earlier position must weigh more than later:
    assert function_vector("['Retinol, Water']")["retinoid"] > \
        function_vector("['Water, Glycerin, Retinol']")["retinoid"], "positional weight wrong"

    print("ingredients.demo OK —", len(toks), "tokens, classes:", sorted(v))


if __name__ == "__main__":
    demo()
