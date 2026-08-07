"""Eyeball retrieval quality: dense vs BM25 vs fused rank, side by side.

    python scripts/query.py "gentle hydrating cleanser for dry skin" cleanser
    python scripts/query.py "retinol serum for wrinkles" treatment
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.retrieval import SLOTS, retrieve  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[2] not in SLOTS:
        print(f"usage: python scripts/query.py \"<query>\" <{'|'.join(SLOTS)}>")
        sys.exit(1)
    query, slot = sys.argv[1], sys.argv[2]
    print(f'\nquery: "{query}"   slot: {slot}\n')
    print(f"{'fus':>3} {'dns':>3} {'bm25':>4}  {'classes':<38} product")
    print("-" * 100)
    for r in retrieve(query, slot):
        d = r["dense_rank"] if r["dense_rank"] else "-"
        b = r["bm25_rank"] if r["bm25_rank"] else "-"
        cls = ",".join(r["classes"][:4]) or "—"
        print(f"{r['fused_rank']:>3} {d:>3} {b:>4}  {cls:<38.38} {r['name'][:48]}")


if __name__ == "__main__":
    main()
