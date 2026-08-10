"""Hard user-exclusion filters (§ audit follow-up). One assertion per filter proving it
removes what it should AND spares what it shouldn't — the sparing half is the point:
the pregnancy-safe gap that shipped a retinoid under a green banner was found here."""
from app.core.filters import filter_cautions, has_drying_alcohol, reason_for

RETINOL = "['Water, Retinol, Glycerin, Phenoxyethanol']"
PEPTIDE = "['Water, Palmitoyl Tripeptide-1, Glycerin, Niacinamide']"
FRAGRANCED = "['Water, Glycerin, Parfum, Phenoxyethanol']"
LAVENDER = "['Water, Glycerin, Lavandula Angustifolia (Lavender) Oil']"
DENAT = "['Alcohol Denat., Water, Salicylic Acid']"
FATTY = "['Water, Glycerin, Cetearyl Alcohol, Cetyl Alcohol']"   # fatty = emollient, keep


def test_pregnancy_removes_retinoid_keeps_peptide():
    # classes are the any-position functional-class set the pipeline passes in
    assert reason_for(["pregnancy-safe only"], RETINOL, {"retinoid"}) == "pregnancy-safe"
    assert reason_for(["pregnancy-safe only"], PEPTIDE, {"peptide"}) is None


def test_fragrance_free():
    assert reason_for(["fragrance"], FRAGRANCED, set()) == "fragrance-free"
    assert reason_for(["fragrance"], PEPTIDE, set()) is None


def test_essential_oils():
    assert reason_for(["essential oils"], LAVENDER, set()) == "essential-oils"
    assert reason_for(["essential oils"], PEPTIDE, set()) is None


def test_alcohol_excludes_drying_spares_fatty():
    # the distinction that matters: denatured alcohol out, cetearyl/cetyl alcohol kept
    assert reason_for(["alcohol"], DENAT, set()) == "alcohol-free"
    assert reason_for(["alcohol"], FATTY, set()) is None
    assert has_drying_alcohol("water, alcohol denat., glycerin")
    assert has_drying_alcohol("aqua, alcohol")            # bare 'Alcohol' = ethanol
    assert not has_drying_alcohol("water, cetearyl alcohol, benzyl alcohol")


def test_no_flags_excludes_nothing():
    assert reason_for([], RETINOL, {"retinoid"}) is None
    assert reason_for([], FRAGRANCED, set()) is None


def test_pregnancy_caution_mentions_salicylic():
    c = filter_cautions(["pregnancy-safe only"])
    assert c and "salicylic" in c[0].lower()
    assert filter_cautions(["fragrance"]) == []
