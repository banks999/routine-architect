# Project Context

Building a technical assignment submission for the **orbo.ai GenAI Intern** role (BeautyTech, Mumbai).
Deadline: ~12 working hours. Deliverable: **document (PDF) + working demo + source**.

**Read `BUILD_PLAN.md` first.** It contains the full architecture, hour-by-hour schedule,
conflict rule base, eval tables to fill in, and document outline. Follow it.

## The thesis (don't lose this)

Recommenders rank items independently. But nobody buys one skincare product — they build a
routine, and skincare products chemically interact. Ranking is the wrong abstraction; routine
construction is a **constrained set-selection problem**.

Corollary that makes the design elegant: ingredient conflicts are **per time-of-day**, not per
routine. So the solver *schedules around* conflicts (AM/PM) rather than excluding products.

## Priorities, in order

1. **The document is the primary deliverable.** The founders/recruiters will read it closely and
   may not read the code. The code exists to make the document's numbers true.
2. **It must run from a clean clone with one command.** The testing UI is mandatory and will be
   clicked. A broken demo poisons the document.
3. Code quality matters but is third. Trade *polish* for document time — never *correctness*.

## Hard rules

- **Never make a safety claim on LLM-inferred ingredient data.** Disable conflict checking and say
  so. See BUILD_PLAN §5.5.
- **Rules handle safety; learned models handle preference.** The conflict engine is a constraint
  layer on top of a learned ranker, not a substitute for one. If disabling the conflict layer makes
  recommendations bad, we built an expert system — that's a failure.
- **Report standard metrics (Recall/NDCG/MAP) as well as the novel routine-level ones.** The brief
  lists them explicitly; don't lose points for non-standard-only evaluation.
- **LLM must degrade gracefully** — free-tier quota will die, likely while evaluators are testing.
  Rule-based fallback for parsing and explanations.
- Ship a committed sample dataset so the project runs without a Kaggle account.
- Not-medical-advice disclaimer in both UI and document.

## Sequencing discipline

Get a complete, submittable single-slot recommender working and evaluated by ~hour 6 *before*
layering on basket construction. Always have a working fallback. If the clever layer breaks at
hour 10, delete it and ship the hour-6 version.

Eval runs **before** the UI (hour 5–6.5) — if the headline number is weak, there's still time to
adjust the story.

## Step zero

`BUILD_PLAN.md` §1 is a go/no-go gate on dataset ingredient coverage. Run it before writing
anything else. If coverage <40%, switch to the fallback plan in §10.

## Running log — MANDATORY, not optional

`DECISIONS.md` is the raw material for the final document. It is assembled from this log, **not**
reconstructed from memory at hour 10. A document written from a live log sounds like someone who
reasoned through tradeoffs; one written from memory sounds generic. This is the highest-leverage
five minutes of each hour.

**Claude: you are responsible for keeping this current. Do not wait to be asked.**

Append an entry to `DECISIONS.md` immediately after any of the following:

- Finishing a numbered section of `BUILD_PLAN.md`
- **Choosing between two or more viable approaches** (this is the most valuable kind of entry —
  record the option *not* taken and why)
- Discovering something surprising in the data
- Hitting a limitation, dead end, or bug worth remembering
- Producing any number that will appear in the document (eval results, latency, coverage)
- Deviating from `BUILD_PLAN.md` for any reason

Use the entry format defined at the top of `DECISIONS.md`. Keep entries terse — 3–6 lines. Capture
**why**, not what the code does; the code already says what it does.

Two rules that make the log actually useful:

- **Record rejected options.** "Chose RRF over weighted score fusion because there was no
  validation budget to tune weights" is document-ready. "Used RRF" is not.
- **Record the numbers as you get them**, including bad ones. Numbers that got worse after a change
  are the most credible thing you can put in a limitations section.

If more than one hour of work has happened with no new entry, stop and write one before continuing.

## Stack (chosen to mirror the job description)

Python · FastAPI (async) · MongoDB · Redis · FAISS · sentence-transformers (all-MiniLM-L6-v2) ·
BM25 (rank_bm25) · Gemini (free tier) · Docker Compose · single-file HTML+Tailwind UI
