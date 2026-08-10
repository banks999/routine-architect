"""Hard user-exclusion filters (the four checkboxes the UI collects).

These remove products from the candidate pool BEFORE ranking — the constraint binds
by exclusion, never by re-ranking — so they are safety-relevant and run on any-position
INCI. Pure functions, unit-tested without the catalogue (see tests/test_filters.py).

Design note worth a line in the doc: 'alcohol' means DRYING/denatured alcohol only
(alcohol denat., SD alcohol, ethanol, isopropyl). Fatty alcohols (cetearyl/cetyl/
stearyl) are emollients, benzyl alcohol is a preservative — none are excluded. Getting
that distinction right is the difference between an honest filter and a blunt substring.
"""
from __future__ import annotations

from app.core.ingredients import unwrap

_FRAGRANCE = ("parfum", "fragrance")   # the two INCI names for added fragrance
# Named essential oils + the essential-oil-derived fragrance allergens sensitive users avoid.
_ESSENTIAL_OILS = (
    "tea tree", "melaleuca", "lavender", "lavandula", "peppermint", "mentha piperita",
    "spearmint", "eucalyptus", "rosemary", "rosmarinus", "geranium", "pelargonium",
    "ylang", "cananga", "clove", "eugenia caryophyllus", "cinnamon", "cinnamomum",
    "lemongrass", "cymbopogon", "citrus", "bergamot", "sandalwood", "jasmine",
    "rosa damascena", "essential oil",
    "limonene", "linalool", "citronellol", "geraniol", "eugenol", "citral")


def has_drying_alcohol(text_lower: str) -> bool:
    """True iff a DRYING alcohol is a distinct INCI token. Token-level, so
    'cetearyl alcohol' (fatty, emollient) never trips it."""
    for t in (tok.strip(" .") for tok in text_lower.split(",")):
        if t in ("alcohol", "ethanol", "isopropyl alcohol"):
            return True
        if t.startswith(("alcohol denat", "sd alcohol", "denatured alcohol")):
            return True
    return False


def reason_for(flags, inci: str, classes) -> str | None:
    """Which exclusion filter (if any) removes a product. `inci` is a raw INCI field
    (list-wrapped or plain); `classes` is its any-position functional-class set."""
    text = unwrap(inci).lower()
    if "pregnancy-safe only" in flags and "retinoid" in classes:
        return "pregnancy-safe"          # retinoids are contraindicated in pregnancy
    if "fragrance" in flags and any(k in text for k in _FRAGRANCE):
        return "fragrance-free"
    if "essential oils" in flags and any(k in text for k in _ESSENTIAL_OILS):
        return "essential-oils"
    if "alcohol" in flags and has_drying_alcohol(text):
        return "alcohol-free"
    return None


def filter_cautions(flags) -> list:
    out = []
    if "pregnancy-safe only" in flags:
        out.append("Pregnancy-safe filter: retinoids removed (contraindicated in pregnancy). "
                   "Salicylic acid (BHA) is NOT auto-removed — low-dose topical BHA is generally "
                   "considered acceptable while oral is not (ACOG guidance); use sparingly and "
                   "confirm with your OB-GYN. Not medical advice.")
    return out
