"""Build + persist per-slot dense/sparse indexes (BUILD_PLAN §2). Reports the
embedding-text token-length distribution vs the MiniLM 256 cap.

    python scripts/03_build_indexes.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.retrieval import INDEX_DIR, build_indexes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
stats = build_indexes(ROOT / "data" / "processed" / "products_enriched.parquet")

print("\n" + "=" * 60)
print("EMBEDDING-TEXT TOKEN LENGTH (MiniLM cap = 256)")
print("=" * 60)
print(f"{'slot':12} {'n':>5} {'p50':>5} {'p95':>5} {'max':>5} {'>256':>6}")
for slot, s in stats.items():
    print(f"{slot:12} {s['n']:>5} {s['tok_p50']:>5} {s['tok_p95']:>5} {s['tok_max']:>5} {s['over_256']:>6}")
print(f"\npersisted to {INDEX_DIR}")
