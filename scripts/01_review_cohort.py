"""Check 1 — leave-one-out eval cohort size across ALL review shards.

Counts, per author, how many reviews they wrote across every reviews_*.csv, then
reports how many authors clear the >=5 / >=3 / >=2 thresholds. This sizes the LOO
eval cohort (§6.1, needs >=5) and the co-review CF signal (§4 ranking).
"""
from collections import Counter
from pathlib import Path

import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"


def main() -> None:
    counts: Counter = Counter()
    total_rows = 0
    for f in sorted(RAW.glob("reviews_*.csv")):
        # only the id column -> cheap even at ~1M rows/shard
        for chunk in pd.read_csv(f, usecols=["author_id"], chunksize=200_000):
            counts.update(chunk["author_id"].dropna().astype(str))
            total_rows += len(chunk)
        print(f"  scanned {f.name}: running unique authors = {len(counts):,}")

    n = len(counts)
    ge5 = sum(1 for c in counts.values() if c >= 5)
    ge3 = sum(1 for c in counts.values() if c >= 3)
    ge2 = sum(1 for c in counts.values() if c >= 2)
    print("\n" + "=" * 60)
    print(f"total review rows        : {total_rows:,}")
    print(f"unique authors           : {n:,}")
    print(f"authors with >=5 reviews : {ge5:,}  ({ge5/n:.1%})  <- LOO eval cohort")
    print(f"authors with >=3 reviews : {ge3:,}  ({ge3/n:.1%})")
    print(f"authors with >=2 reviews : {ge2:,}  ({ge2/n:.1%})  <- CF-usable")
    print("=" * 60)


if __name__ == "__main__":
    main()
