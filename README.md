# docsentry

A developer-support agent over technical documentation.

> **Status — design complete, implementation in progress.**
> Nothing here is measured yet. Final results will replace every blank in
> [Experiments](#experiments). Design spec:
> [`docs/superpowers/specs/`](docs/superpowers/specs/)

---

## The problem

Ask a good LLM how to use a popular framework and it usually answers correctly.
So why build a retrieval system at all?

Because three gaps are not closed by model capability:

| Gap | Why a better model doesn't close it |
|---|---|
| **Freshness** | Training data has a cutoff. MCP's protocol changed substantially in July 2026 — a model without retrieval will confidently describe the *old* handshake protocol. |
| **Private corpora** | Internal APIs, private SDKs, company wikis. Never seen during training, at any model size. |
| **Traceability** | Even a correct answer gives you no way to verify it. |

Chunking is where these systems fail quietly. A chunk cut mid-code-block, or a
passage retrieved from a two-year-old version, produces a **confident wrong answer** —
the worst possible failure mode for a documentation tool.

**docsentry studies that layer.** The research question:

> When the corpus is outside the model's knowledge, what does retrieval need to do?

## Approach

- **Structure-aware chunking** — split along the Markdown heading hierarchy, carry
  the breadcrumb path (`MCP > Server Concepts > Resources`) as chunk metadata, and
  never split a code block or a table.
- **Version-aware retrieval** — every chunk carries its document version; answers
  state which version they rely on. Multiple versions coexist in the index and can
  be filtered at query time.
- **Source registry, not file upload** — uploads produce *snapshots*, and snapshots
  go stale with no way for the system to notice. Sources are *pointers* instead:
  URL sources are re-polled, local directories are re-scanned on every index run.
  Skipping the upload step removes the staleness problem rather than managing it.
- **Provenance** — every answer reports source, version, and index time, and warns
  when retrieved content is older than a threshold.

## Experiments

Three ablations on one 50-question categorized eval set
(`factual` / `api` / `cross_doc` / `version`):

| # | Comparison | Question it answers |
|---|---|---|
| 1 | fixed-size vs semantic vs **structural** chunking | Does structure-aware chunking actually help — and on which question types? |
| 2 | single-pass pipeline vs LangGraph agent loop | Is multi-step retrieval worth its cost in tokens and latency? |
| 3 | model-only vs **stale index** vs fresh index | What is index staleness actually worth, in accuracy points? |

All three chunking strategies target the same chunk size, so differences are
attributable to *where* the split happens, not *how big* the chunks are.
`uv run scripts/check_fairness.py` measures that on the 774-document corpus:

| strategy | chunks | mean | median | total_chars | vs corpus |
|---|---|---|---|---|---|
| fixed | 17,941 | 973 | 1000 | 17,465,289 | 1.24x |
| semantic | 14,682 | 1032 | 910 | 15,155,151 | 1.08x |
| structural | 18,442 | 805 | 642 | 14,840,156 | 1.06x |

Every mean sits inside the target's ±25% band; the worst pair is 1.28x. Indexed
characters are published rather than equalised — `fixed`'s excess is its overlap,
while the other two exceed the source because a forced cut repeats a wide table's
header (an atomic unit over `max_atomic_size` is split, not left unembeddable).

Every number in the results will be reproducible from a committed eval set.

## Stack

Python · MCP & LangGraph docs as corpus · BGE-M3 (local embeddings) ·
Qdrant · BM25 + RRF fusion · BGE-reranker · LangGraph for orchestration

Chunking, retrieval fusion, and evaluation are written from scratch — they are
the experimental variables, so they stay under direct control. Orchestration uses
LangGraph because state management and conditional branching are a configuration
problem, not a research one.

## Progress

- [x] Design document — architecture, module design, experiment design, limitations
- [x] **M1 corpus layer** — `llms_txt` + `local_dir` sources, `content_hash` incremental
      update (insert-then-delete), per-source manifests, fetch report, health check
- [x] **M2 chunking** — fixed / semantic / structural, plus a fairness check that runs
- [ ] Indexing & hybrid retrieval
- [ ] Generation with citations and provenance
- [ ] Eval set (50 questions) + chunking ablation
- [ ] LangGraph orchestration + pipeline-vs-agent ablation
- [ ] Freshness experiment (model-only / stale / fresh)
- [ ] Results, failure analysis, write-up

Corpus today: **774 documents** — MCP 252 (198 dated + 54 draft, **100 % version-labelled**)
and LangChain Python 522 (versionless by nature). 17 upstream pages are *reported* rather than
silently dropped: 16 the site serves as `text/html` instead of Markdown, 1 returning 404.
Re-running the fetch changes nothing (`added=0 updated=0 deleted=0`).

## Design document

[`docs/superpowers/specs/2026-09-18-docsentry-design.md`](docs/superpowers/specs/2026-09-18-docsentry-design.md)

Covers architecture, per-module design, the experiment design, data model,
security boundaries, and — deliberately — a **known limitations** section:
what this does *not* handle, and why each omission was a choice rather than an
oversight.
