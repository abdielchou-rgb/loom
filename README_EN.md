# Loom — A Narrative Compiler

> **Idea → Narrative IR → Renderers.**
> Loom does not *generate a story*. It compiles an idea into a structured
> narrative intermediate representation (IR), verifies that representation
> against writing theory, and renders it to any medium. **Text is one view of
> the IR — not the product.**

Loom is built for writers who use AI as a *co-author they can interrogate*, not
as a ghostwriter. Its stance is adversarial and author-side: it tells you what
is structurally wrong with your story, and leaves the writing to you.

---

## Why this exists

The dominant failure mode of LLM writing tools is well known and stated plainly
by narrative theory: *every paragraph is plausible, but taken together they
prove nothing.* A model with no premise will happily produce 50,000 words that
never argue for anything.

Loom attacks that failure at the architecture level, not the prompt level:

- A **premise / controlling idea / logline** (L3 — the author's commitment) is a
  hard constraint, not a suggestion.
- **Character intentions** (L2) are modelled as goal graphs, so conflict is
  "two goals collide", not "the plot needs tension here".
- **Causal plot** (L1) is a POCL-style event/link graph, so "this happens
  because that happened" is checkable.

This three-layer decomposition (L1 causal plot / L2 character intention /
L3 authorial commitment) is the same shape formalised independently by
**Riedl & Young's IPOCL** and by **NCP-Bench (ICML 2026)**, which serialises
the same three layers to YAML. Loom's IR is, in effect, an executable,
writer-facing version of that formalism.

---

## The empty quadrant

Global competitors in AI-assisted writing are, without exception,
**generative-first and verification-free**:

| Tool | Generates prose | Verifies structure | Compliance export | One-screen share |
|---|---|---|---|---|
| Sudowrite | yes | no | no | no |
| NovelAI | yes | no (lorebook only) | no | no |
| ChatGPT / Jasper / Writesonic | yes | no | no | no |
| NovelCrafter / Squibler | yes | light | no | no |
| Loom | optional | **yes (41 deterministic gates)** | **C2PA 2.x** | **yes (`loom glance`)** |

High verifiability **and** low first-minute friction **and** a compliance export
is a quadrant nobody else occupies — globally, not just in China.

---

## Verifiability, not vibes

Loom ships **41 deterministic validators** (32 gating + 9 report-only). Every
gating validator:

1. declares its data requirement (`REQUIRES`) — a validator that can't get its
   data is `SKIPPED`, never silently "passing";
2. ships a **counter-example fixture** proving it catches the defect it claims
   to catch (net-hit-rate test: severity must *escalate* on the mutation, not
   merely "fire");
3. cites its theoretical source in its docstring (McKee / Todorov / Greimas /
   Egri / Barthes / Genette / 李渔 / 毛宗岗 …).

Crucially, **no validator uses an LLM judge.** This is the deliberate
differentiator from [`story-bench`](https://github.com/kevinchi22/story-bench)
(2025), which scores narratives with a 50% LLM-judge ensemble. Loom's gates are
fully programmatic, reproducible, and falsifiable — you can run them offline with
zero API keys.

See `loom bench <ir.json>` to export the full methodology as
`loom-bench` — a ready-to-cite, judge-free writing benchmark.

---

## Compliance is architecture, not a feature flag

AI-generated content faces hard labelling law: China's *Generative AI Content
Labelling Measures* (2025-09-01) and *Micro-Drama Management Measures* (2026-09-01),
the **EU AI Act Article 50** (in force 2026-08-02), the EU Code of Practice
(2026-06-10), and Korea (2026-03). "I think it's mostly human-written" is not a
defensible position.

Loom builds a **provenance ledger** into the pipeline: every scene records its
origin (human / AI-generated / AI-edited / AI-assisted), model, and prompt
version. From that ledger it can export:

- a **participation report** (AI ratio, trace coverage, pass/caution/blocked verdict);
- a **creative-process report** (the *human judgements* — accept/reject decisions
  on AI proposals — that constitute evidence of authorship, for platform appeals);
- a **C2PA 2.x Content Credentials manifest** (`loom c2pa <ir.json>`) mapping
  scene origins to `c2pa.actions` / `c2pa.assetGenAI` / `c2pa.creativeWork`
  assertions — the emerging global standard for provenance metadata.

> The manifest is produced but **not signed**: signing needs a C2PA credential
> (X.509), which is outside Loom's zero-dependency scope (its only hard
> dependency is `pydantic`). Sign and embed with any C2PA-aware tool.

---

## The first minute

A judgement that never reaches the writer is worth zero. Loom's accessibility
surface is a one-screen, shareable card:

```
loom glance out/ir.json        # → glance.html: outline + 3 character cards
                               #   + top-3 health findings + score/coverage chips
```

One command, under 30 seconds, one screen you can forward.

---

## Honest scope

- **Loom eliminates structurally broken stories. It does not predict hits.**
  No audience model, no health score, no validator claims "this will succeed".
  Uncalibrated output is explicitly labelled *a priori*.
- **Structural proposals are never auto-applied.** `CriticLoop` auto-fixes only
  prose/craft issues; structure is left for the author to decide. Auto-rewriting
  structure destroys author intent (and scores ~40% on premise fidelity in
  planning-route studies).
- **Works fully offline.** No API key required to run end-to-end; the LLM is
  optional and lazy-loaded. `MockGenerator` is a reference implementation that
  proves the whole pipeline without any model.

---

## Quick start

```bash
# idea → IR → prose (offline reference generator, no API key)
python -m loom.cli write "一个替人收尸的刀客，发现自己要收的尸体是十年前的自己" \
    --out out/demo

# one-screen shareable card
python -m loom.cli glance out/demo/ir.json

# structural health check (41 deterministic validators, no LLM judge)
python -m loom.cli audit out/demo/ir.json

# export the methodology as a judge-free benchmark
python -m loom.cli bench out/demo/ir.json

# export C2PA 2.x content-credentials manifest
python -m loom.cli c2pa out/demo/ir.json

# render to any medium
python -m loom.cli render out/demo/ir.json -f fountain   # screenplay
python -m loom.cli render out/demo/ir.json -f ink       # interactive fiction
python -m loom.cli render out/demo/ir.json -f renpy      # visual novel
```

Self-verify (zero dependencies, no pytest, no API key):

```bash
.venv/Scripts/python.exe scripts/verify.py
```

---

## Status

- **Core (top-tier):** three-layer IR, 41 deterministic validators with
  counter-example fixtures and net-hit-rate tests, provenance ledger + C2PA export.
- **Accessibility (shipped this pass):** one-screen `glance` card.
- **Renderers:** text / fountain / storyboard / ink / renpy / html.
- **Notable non-goals:** text watermarking (still unreliable), anti-detection
  features (explicitly refused), multimodal generation (1.0 scope).

*Evidence graded A (primary sources / formal methods), B (reproduced benchmarks),
C (expert consensus). See `成为全球顶级项目的路径_2026-09-15.md` for the full
reasoning behind the positioning above.*
