"""Document figures -> eval/figures/*.png (matplotlib, print-safe 200 dpi).

  a. conflict rate vs product-set size        (the 2.5% -> 50% curve, main visual)
  b. three-way baseline comparison            (naive / budget-greedy / solver)
  c. architecture diagram                      (learned vs deterministic, LLM touch)

Colours: Okabe-Ito colourblind-safe palette.  Run: python eval/make_figures.py
"""
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
FIG = ROOT / "eval" / "figures"
FIG.mkdir(parents=True, exist_ok=True)

# Okabe-Ito
BLUE, ORANGE, GREEN, VERM, SKY, YELLOW, PURPLE, GREY = (
    "#0072B2", "#E69F00", "#009E73", "#D55E00", "#56B4E9", "#F0E442", "#CC79A7", "#999999")
plt.rcParams.update({"font.size": 11, "axes.titlesize": 13, "axes.titleweight": "bold",
                     "figure.dpi": 200, "savefig.dpi": 200, "font.family": "DejaVu Sans"})


def fig_a():
    rows = list(csv.DictReader(open(ROOT / "eval" / "conflict_by_setsize.csv")))
    x = [r["set_size"] for r in rows]
    rate = [float(r["conflict_rate"]) * 100 for r in rows]
    n = [int(r["n_users"]) for r in rows]
    xi = list(range(len(x)))

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(xi, rate, "-o", color=VERM, lw=2.5, ms=9, zorder=3)
    ax.fill_between(xi, rate, color=VERM, alpha=0.08, zorder=1)
    for i, (r, c) in enumerate(zip(rate, n)):
        ax.annotate(f"{r:.1f}%", (i, r), textcoords="offset points", xytext=(0, 12),
                    ha="center", fontweight="bold", color=VERM)
        ax.annotate(f"n={c:,}", (i, r), textcoords="offset points", xytext=(0, -18),
                    ha="center", fontsize=9, color=GREY)
    ax.set_xticks(xi); ax.set_xticklabels(x)
    ax.set_xlabel("Products in a user's routine (set size)")
    ax.set_ylabel("Real users with ≥1 ingredient conflict")
    ax.set_title("Ingredient conflicts are a set-size problem, not a per-item one")
    ax.set_ylim(0, 58)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter())
    ax.grid(axis="y", alpha=0.3)
    ax.annotate("A top-K ranker optimises each pick in isolation —\n"
                "but conflict is a property of the SET, and it\n"
                "climbs from 2.5% to ~50% as the set grows.",
                xy=(4.05, 20.65), xytext=(1.4, 41),
                arrowprops=dict(arrowstyle="->", color="black", lw=1.2),
                fontsize=9.5, va="center",
                bbox=dict(boxstyle="round", fc="#FFF6F0", ec=VERM, alpha=0.9))
    fig.tight_layout()
    fig.savefig(FIG / "a_conflict_by_setsize.png", bbox_inches="tight")
    plt.close(fig)
    print("wrote a_conflict_by_setsize.png")


def fig_b():
    d = json.load(open(ROOT / "eval" / "results.json"))["any_position"]
    methods = [("naive", "Naive top-K", GREY), ("greedy", "Budget-greedy", SKY), ("solver", "Solver (ours)", GREEN)]
    metrics = [("budget_adherence", "Budget\nadherence"),
               ("placement_compliance", "AM/PM placement\ncompliance"),
               ("safety_rate", "Safety rate\n(0 hard conflicts)")]
    x = np.arange(len(metrics)); w = 0.26
    fig, ax = plt.subplots(figsize=(8.5, 5))
    for j, (key, label, col) in enumerate(methods):
        vals = [d[key][m] * 100 for m, _ in metrics]
        bars = ax.bar(x + (j - 1) * w, vals, w, label=label, color=col, zorder=3)
        for b, v in zip(bars, vals):
            ax.annotate(f"{v:.0f}", (b.get_x() + b.get_width() / 2, v), textcoords="offset points",
                        xytext=(0, 3), ha="center", fontsize=9, fontweight="bold")
    ax.set_xticks(x); ax.set_xticklabels([m for _, m in metrics])
    ax.set_ylabel("% of 200 synthetic routines")
    ax.set_ylim(0, 125)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter())
    ax.set_title("Budget is a per-item patch; conflict-free scheduling needs the solver", pad=32)
    ax.legend(loc="upper center", ncol=3, framealpha=0.95, bbox_to_anchor=(0.5, 1.02))
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "b_baseline_comparison.png", bbox_inches="tight")
    plt.close(fig)
    print("wrote b_baseline_comparison.png")


def fig_c():
    fig, ax = plt.subplots(figsize=(13.5, 5.2))
    ax.set_xlim(0, 13.5); ax.set_ylim(0, 6); ax.axis("off")
    LEARNED, DETERM, LLM = SKY, GREEN, ORANGE
    stages = [
        ("1. Retrieve", "dense MiniLM+FAISS\n+ BM25 · RRF fuse", LEARNED, "LEARNED"),
        ("2. Rank", "4 signals: semantic·\nCF·rating·skin", LEARNED, "LEARNED"),
        ("3. Conflicts", "rules on functional\nclasses (17 rules)", DETERM, "DETERMINISTIC"),
        ("4. Solve", "beam search ·\nAM/PM schedule", DETERM, "DETERMINISTIC"),
        ("5. Ground", "theme mining +\nreview snippets", DETERM, "DETERMINISTIC"),
        ("6. Phrase", "LLM writes prose\n(template fallback)", LLM, "LLM"),
    ]
    n = len(stages); bw, gap = 1.95, 0.18
    x0 = 0.35
    y = 3.2; bh = 1.7
    centers = []
    for i, (title, sub, col, tag) in enumerate(stages):
        x = x0 + i * (bw + gap)
        box = FancyBboxPatch((x, y), bw, bh, boxstyle="round,pad=0.02,rounding_size=0.12",
                             fc=col, ec="black", lw=1.2, alpha=0.9, mutation_aspect=1)
        ax.add_patch(box)
        ax.text(x + bw / 2, y + bh - 0.32, title, ha="center", va="center", fontsize=10.5, fontweight="bold")
        ax.text(x + bw / 2, y + bh / 2 - 0.18, sub, ha="center", va="center", fontsize=8.5)
        ax.text(x + bw / 2, y - 0.24, tag, ha="center", va="center", fontsize=7.5,
                fontweight="bold", color=col if col != YELLOW else "black")
        centers.append((x + bw / 2, x, x + bw))
        if i:
            ax.add_patch(FancyArrowPatch((centers[i - 1][2], y + bh / 2), (x, y + bh / 2),
                                         arrowstyle="-|>", mutation_scale=16, lw=1.4, color="black"))
    # legend
    for k, (lab, col) in enumerate([("Learned model", LEARNED), ("Deterministic (rules/search)", DETERM),
                                    ("LLM (prose only)", LLM)]):
        ax.add_patch(FancyBboxPatch((0.5 + k * 3.3, 5.35), 0.32, 0.32, boxstyle="round,pad=0.02",
                                    fc=col, ec="black", lw=1))
        ax.text(0.95 + k * 3.3, 5.51, lab, va="center", fontsize=9.5)
    # safety bracket under stages 3-4
    sx0, sx1 = centers[2][1], centers[3][2]
    ax.plot([sx0, sx0, sx1, sx1], [2.55, 2.4, 2.4, 2.55], color=VERM, lw=1.6)
    ax.text((sx0 + sx1) / 2, 2.05, "SAFETY — fully deterministic.\nThe LLM never gates a product.",
            ha="center", va="top", fontsize=9, color=VERM, fontweight="bold")
    # LLM caveat under stage 6
    lx = centers[5][1]
    ax.text(centers[5][0], 2.05, "Mechanism/citation text is\nverbatim from conflicts.yaml,\nNOT model-generated.",
            ha="center", va="top", fontsize=8, color=ORANGE)
    ax.text(6, 5.95, "Routine Architect — six-stage pipeline", ha="center", fontsize=14, fontweight="bold")
    fig.savefig(FIG / "c_architecture.png", bbox_inches="tight")
    plt.close(fig)
    print("wrote c_architecture.png")


if __name__ == "__main__":
    fig_a(); fig_b(); fig_c()
    print("figures in", FIG)
