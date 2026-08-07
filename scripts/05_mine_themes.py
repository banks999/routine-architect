"""Mine the top review themes per product (BUILD_PLAN §3.4 deferred item), with
per-skin_type counts so explanations can weight toward the user's skin.

Theme = a bigram/trigram phrase, ranked by DOCUMENT frequency (how many distinct
reviews mention it — one gushing review can't dominate), after stopword/boilerplate
removal. Writes data/processed/product_themes.parquet.

    python scripts/05_mine_themes.py            # mine + write
    python scripts/05_mine_themes.py --sample   # just print samples to eyeball
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MAX_PER_PRODUCT = 500
MIN_DF = 3            # a theme must appear in >= this many reviews
TOP_THEMES = 6

HARD = set("the a an and or but is are was were be been being it its this that these those i my me we our "
           "you your he she they them to of for with on in at by from as so if not no do does did have has had "
           "will can just very too then than there here up out all any some more most when what which who how "
           "because about into over after before only own same such both each we've i've it's don't didn't was "
           "im ive get got go going".split())
FILLER = set("product products skin face use used using love loved really would recommend highly great good "
             "amazing nice well also feel feels felt make makes made tried buy bought star stars review reviews "
             "definitely absolutely super thing things stuff bit lot okay ok yes "
             # review-platform boilerplate + sponsored-review disclaimers
             "honest received complimentary exchange gifted influenser influenster voxbox tester testing sample "
             "sent free pr purchased".split())
_WORD = re.compile(r"[a-z]+")
# platform / sponsorship tokens -> drop the WHOLE n-gram if any appears (unlike FILLER,
# which only drops all-filler grams). NOT including "free" — oil-free/fragrance-free are real.
SPONSOR = set("sample samples freeproduct pinchme trywithtopbox topbox bzzagent crowdtap smiley voxbox "
              "influenster influenser complimentary freebie pinch received gifted "
              # sponsored-review disclaimer fragments ("opinions are completely my own", etc.)
              "opinions opinion unbiased compensated disclosure honest".split())


def phrases(text: str, banned: set) -> set:
    toks = _WORD.findall(str(text).lower())
    out = set()
    for n in (2, 3):
        for i in range(len(toks) - n + 1):
            g = toks[i:i + n]
            if g[0] in HARD or g[-1] in HARD:
                continue
            if all(t in HARD or t in FILLER for t in g):
                continue
            if any(len(t) < 3 for t in g):
                continue
            if any(t in banned or t in SPONSOR for t in g):  # name echoes + sponsorship, drop
                continue
            out.add(" ".join(g))
    return out


def _dedupe(ranked: list) -> list:
    """Drop a bigram if it's fully contained in an already-kept higher-ranked trigram."""
    kept = []
    for ph, df, skins in ranked:
        if any(ph != k[0] and ph in k[0] for k in kept):
            continue
        kept.append((ph, df, skins))
    return kept


def mine(reviews: pd.DataFrame, banned: set) -> dict:
    df_count = Counter()
    skin_count = defaultdict(Counter)
    for row in reviews.itertuples():
        for ph in phrases(row.review_text, banned):
            df_count[ph] += 1
            if isinstance(row.skin_type, str):
                skin_count[ph][row.skin_type] += 1
    ranked = [(ph, c, dict(skin_count[ph])) for ph, c in df_count.most_common(40) if c >= MIN_DF]
    ranked = _dedupe(ranked)[:TOP_THEMES]
    return [{"phrase": ph, "df": c, "skins": s} for ph, c, s in ranked]


def main(sample_only=False):
    prod = pd.read_parquet(ROOT / "data" / "processed" / "products_enriched.parquet")
    elig = set(prod[prod["routine_eligible"]]["product_id"])
    name = dict(zip(prod["product_id"], prod["brand_name"] + " — " + prod["product_name"]))

    cols = ["product_id", "skin_type", "review_text", "rating"]
    frames = []
    for f in sorted((ROOT / "data" / "raw").glob("reviews_*.csv")):
        for ch in pd.read_csv(f, usecols=cols, chunksize=200_000):
            ch = ch[ch["product_id"].isin(elig) & (ch["rating"] >= 4) & ch["review_text"].notna()]
            frames.append(ch)
    rev = pd.concat(frames, ignore_index=True)
    rev = rev.groupby("product_id", group_keys=False).head(MAX_PER_PRODUCT)
    print(f"mining themes over {len(rev):,} reviews for {rev['product_id'].nunique()} products")

    # per-product banned tokens = its own brand + product name words (kills circular
    # "reviewers mention drunk elephant" themes)
    banned_by = {}
    for pid in rev["product_id"].unique():
        banned_by[pid] = {t for t in _WORD.findall(str(name.get(pid, "")).lower()) if len(t) >= 3}
    themes = {}
    for pid, g in rev.groupby("product_id"):
        themes[pid] = {"themes": mine(g, banned_by.get(pid, set())),
                       "skin_totals": {k: int(v) for k, v in g["skin_type"].value_counts().items()}}

    # eyeball a few well-reviewed products
    top_by_vol = rev["product_id"].value_counts().head(8).index
    print("\n=== SAMPLE THEMES (judge quality) ===")
    for pid in top_by_vol:
        ts = themes.get(pid, {}).get("themes", [])
        print(f"\n{name.get(pid, pid)[:55]}")
        for t in ts:
            top_skin = max(t["skins"], key=t["skins"].get) if t["skins"] else "-"
            print(f"    '{t['phrase']}'  (df={t['df']}, top skin={top_skin})")

    if not sample_only:
        out = pd.DataFrame({"product_id": list(themes), "themes": [json.dumps(v) for v in themes.values()]})
        out.to_parquet(ROOT / "data" / "processed" / "product_themes.parquet", index=False)
        print(f"\nwrote product_themes.parquet ({len(out)} products)")


if __name__ == "__main__":
    main(sample_only="--sample" in sys.argv)
