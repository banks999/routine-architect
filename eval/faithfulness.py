"""BUILD_PLAN §6.5 — explanation faithfulness.

Does every claim in a generated explanation trace to its evidence (a mined review
theme, a retrieved review snippet, or a flagged active)? Or did the model add
something the grounding never said?

Judge = Groq llama-3.3-70b-versatile — a DIFFERENT model family from the Gemini
generator, so we avoid the self-preference bias of grading a model with itself.

Runs the same check on TEMPLATE explanations (faithful by construction) as a control:
the contrast quantifies what readability via the LLM costs in faithfulness.

    source eval/../keys ; GEMINI_API_KEY=.. GROQ_API_KEY=.. python eval/faithfulness.py
"""
import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.core import pipeline as P
from app.core import solver as sv
from app.db.store import store

ROOT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
GROQ_MODEL = "llama-3.3-70b-versatile"

PROFILES = [
    sv.Profile(concerns=["acne", "aging"], budget=14000, skin="oily"),
    sv.Profile(concerns=["aging", "texture"], budget=12000, skin="combination"),
    sv.Profile(concerns=["dark_spots", "dullness"], budget=14000, skin="dry"),
    sv.Profile(concerns=["dryness", "redness"], budget=12000, skin="dry"),
    sv.Profile(concerns=["oiliness", "acne"], budget=9000, skin="oily"),
    sv.Profile(concerns=["texture", "dullness"], budget=12000, skin="normal"),
    sv.Profile(concerns=["aging", "dark_spots"], budget=16000, skin="combination"),
    sv.Profile(concerns=["redness", "dryness"], budget=15000, skin="combination"),
    sv.Profile(concerns=["dark_spots", "acne"], budget=13000, skin="oily"),
    sv.Profile(concerns=["dullness", "aging"], budget=11000, skin="normal"),
    sv.Profile(concerns=["texture", "acne"], budget=10000, skin="dry"),
    sv.Profile(concerns=["oiliness", "dark_spots"], budget=12000, skin="oily"),
    sv.Profile(concerns=["aging", "dryness"], budget=17000, skin="dry"),
    sv.Profile(concerns=["redness", "dullness"], budget=14000, skin="normal"),
    sv.Profile(concerns=["redness", "aging"], budget=15000, skin="dry"),
    sv.Profile(concerns=["oiliness", "texture"], budget=12000, skin="combination"),
    sv.Profile(concerns=["dark_spots", "redness"], budget=13000, skin="normal"),
    sv.Profile(concerns=["acne", "dryness"], budget=11000, skin="combination"),
    sv.Profile(concerns=["dullness", "redness"], budget=14000, skin="oily"),
    sv.Profile(concerns=["texture", "dark_spots"], budget=13000, skin="dry"),
    sv.Profile(concerns=["aging", "oiliness"], budget=16000, skin="oily"),
    sv.Profile(concerns=["dryness", "dullness"], budget=12000, skin="combination"),
    sv.Profile(concerns=["acne", "redness"], budget=10000, skin="oily"),
    sv.Profile(concerns=["texture", "dryness"], budget=13000, skin="normal"),
]

JUDGE_SYS = (
    "You audit AI-written skincare product explanations for FAITHFULNESS to their evidence. "
    "The evidence is the ONLY thing the writer was allowed to use: a list of active-ingredient "
    "CLASSES, mined review THEMES (short phrases), review SNIPPETS, the user's skin type, and a "
    "matched-review count. A claim is SUPPORTED if it restates or paraphrases something in the "
    "evidence (an active, a theme, a snippet, the skin type, or the count). A claim is UNSUPPORTED "
    "if it introduces a specific ingredient, benefit, or fact that appears nowhere in the evidence. "
    "Generic non-factual filler ('a great fit for your routine') is NOT a violation. "
    "Return ONLY JSON: {\"verdict\":\"faithful\"|\"unfaithful\",\"unsupported\":[\"...\"],\"reason\":\"one line\"}."
)


def groq_judge(evidence: dict, explanation: str, retries=4) -> dict:
    user = ("EVIDENCE:\n" + json.dumps(evidence, ensure_ascii=False) +
            "\n\nEXPLANATION:\n" + explanation + "\n\nAudit it.")
    body = json.dumps({"model": GROQ_MODEL, "temperature": 0,
                       "messages": [{"role": "system", "content": JUDGE_SYS},
                                    {"role": "user", "content": user}],
                       "response_format": {"type": "json_object"}}).encode()
    for attempt in range(retries):
        req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", data=body,
                                     headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
                                              "Content-Type": "application/json", "User-Agent": UA})
        try:
            r = json.load(urllib.request.urlopen(req, timeout=40))
            return json.loads(r["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(5 * (attempt + 1)); continue
            return {"verdict": "error", "unsupported": [], "reason": f"http {e.code}"}
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(3); continue
            return {"verdict": "error", "unsupported": [], "reason": str(e)[:80]}
    return {"verdict": "error", "unsupported": [], "reason": "retries exhausted"}


async def collect(target=30):
    """Return [{pid,name,skin,evidence,llm,template}] — one per product, until target."""
    await store.connect()
    from app.core.retrieval import get_model
    get_model()
    items, seen = [], set()
    for prof in PROFILES:
        if len(items) >= target:
            break
        cands = P.build_candidates(prof)
        routine = sv.solve(cands, prof, enforce_conflicts=True)
        context, tmpl, ev = [], {}, {}
        for pl in routine.placements:
            _, snip = await store.review_snippets(pl.cand.id, prof.skin, k=3)
            themes, fallback, n_skin = P._themes_for(pl.cand.id, prof.skin, prof.concerns, k=3)
            actives = sorted(pl.cand.classes & sv._active_classes())
            snips = [s["text"][:200] for s in snip]
            ev[pl.cand.id] = {"actives": actives, "themes": themes, "skin_type": prof.skin,
                              "matched_skin_reviews": n_skin, "snippets": snips}
            tmpl[pl.cand.id] = P._template_explain(prof.skin, themes, fallback, n_skin, pl.cand.classes)
            context.append({"product_id": pl.cand.id, "name": pl.cand.name, "actives": actives,
                            "themes": themes, "matched_skin_reviews": n_skin, "snippets": snips})
        gem = await P._gemini_explain(context)          # 1 batched Gemini call / profile
        src = "gemini" if gem else "template"
        print(f"  profile {prof.skin}/{prof.concerns}: explanation_source={src}")
        for pl in routine.placements:
            pid = pl.cand.id
            if pid in seen:
                continue
            seen.add(pid)
            items.append({"pid": pid, "name": pl.cand.name, "skin": prof.skin,
                          "evidence": ev[pid], "template": tmpl[pid],
                          "llm": (gem.get(pid) if gem else None)})
            if len(items) >= target:
                break
        time.sleep(6)   # Gemini free tier 10 RPM
    return items


def main():
    items = asyncio.run(collect(30))
    n_llm = sum(1 for it in items if it["llm"])
    print(f"\ncollected {len(items)} products; {n_llm} have an LLM explanation\n")

    rows = []
    for i, it in enumerate(items):
        row = {"pid": it["pid"], "name": it["name"], "skin": it["skin"],
               "evidence": it["evidence"], "llm": it["llm"], "template": it["template"]}
        if it["llm"]:
            row["judge_llm"] = groq_judge(it["evidence"], it["llm"]); time.sleep(2)  # Groq 30 RPM
        row["judge_template"] = groq_judge(it["evidence"], it["template"]); time.sleep(2)
        rows.append(row)
        v = row.get("judge_llm", {}).get("verdict", "-")
        print(f"[{i+1:2}/{len(items)}] llm={v:11} template={row['judge_template']['verdict']:11} {it['name'][:42]}")

    def rate(key):
        judged = [r for r in rows if key in r and r[key]["verdict"] in ("faithful", "unfaithful")]
        ok = [r for r in judged if r[key]["verdict"] == "faithful"]
        return len(ok), len(judged)

    lo, ln = rate("judge_llm")
    to, tn = rate("judge_template")
    summary = {
        "judge_model": GROQ_MODEL, "generator_model": "gemini-flash-lite-latest",
        "n_products": len(rows),
        "llm": {"faithful": lo, "judged": ln, "rate": round(lo / ln, 3) if ln else None},
        "template": {"faithful": to, "judged": tn, "rate": round(to / tn, 3) if tn else None},
        "llm_failure_modes": [{"name": r["name"], "why": r["llm"],
                               "unsupported": r["judge_llm"]["unsupported"], "reason": r["judge_llm"]["reason"]}
                              for r in rows if r.get("judge_llm", {}).get("verdict") == "unfaithful"],
    }
    out = ROOT / "eval" / "faithfulness_results.json"
    json.dump({"summary": summary, "rows": rows}, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("\n=== FAITHFULNESS ===")
    print(f"  LLM (gemini):   {lo}/{ln} = {summary['llm']['rate']}")
    print(f"  TEMPLATE:       {to}/{tn} = {summary['template']['rate']}")
    print(f"  unfaithful LLM cases: {len(summary['llm_failure_modes'])}")
    for fm in summary["llm_failure_modes"]:
        print(f"    - {fm['name'][:40]}: {fm['reason']}  unsupported={fm['unsupported']}")
    print(f"\nwrote {out}")
    # 5 for hand-check
    print("\n=== HAND-CHECK SAMPLE (first 5 with LLM) ===")
    for r in [r for r in rows if r["llm"]][:5]:
        print(f"\n• {r['name']}  [{r['skin']}]")
        print(f"  evidence: actives={r['evidence']['actives']} themes={r['evidence']['themes']} n={r['evidence']['matched_skin_reviews']}")
        print(f"  LLM: {r['llm']}")
        print(f"  judge_llm: {r['judge_llm']['verdict']} — {r['judge_llm']['reason']}")


if __name__ == "__main__":
    main()
