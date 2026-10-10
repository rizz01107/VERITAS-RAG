# Phase 2 design: repository, configuration, contracts

Status: implemented and tested (see "Verification evidence"). Nothing here reports
experimental results; all experiment fields default to NOT RUN / PENDING EXPERIMENT.

## Deviations from Phase 1 (stated, not hidden)

* Frontend is React + Vite (Phase 1 listed Streamlit only as a fallback). It is not scaffolded yet (Phase 17).
* `retrieval.top_k` is the **final context size for every compared system**; `candidate_k` is the pre-rerank pool. This makes systems B-E comparable.
* Added `app/schemas/`, a `readiness` gate and a cost guard (`budget`), none of which were in the original tree.
* ECS parameters live in config and must be **frozen before test-split evaluation** (pre-registration style).

## A. Repository tree (as implemented)

```
veritas-rag/
├── app/
│   ├── api/
│   │   └── __init__.py
│   ├── claims/
│   │   └── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── budget.py
│   │   ├── config.py
│   │   ├── device.py
│   │   ├── env.py
│   │   ├── errors.py
│   │   ├── experiment.py
│   │   ├── hashing.py
│   │   ├── logconfig.py
│   │   ├── model_registry.py
│   │   ├── readiness.py
│   │   └── seed.py
│   ├── evaluation/
│   │   ├── __init__.py
│   │   ├── annotation.py
│   │   └── validation.py
│   ├── generation/
│   │   └── __init__.py
│   ├── ingestion/
│   │   ├── __init__.py
│   │   └── manifest.py
│   ├── reranking/
│   │   └── __init__.py
│   ├── retrieval/
│   │   └── __init__.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── claims.py
│   │   ├── documents.py
│   │   ├── enums.py
│   │   ├── evaluation.py
│   │   ├── experiments.py
│   │   ├── manifest.py
│   │   ├── models.py
│   │   └── verification.py
│   ├── utils/
│   │   └── __init__.py
│   ├── verification/
│   │   └── __init__.py
│   ├── __init__.py
│   └── cli.py
├── configs/
│   ├── default.yaml
│   ├── dev_cpu.yaml
│   ├── eval_full.yaml
│   ├── models.local.example.yaml
│   └── models.yaml
├── data/
│   ├── evaluation/
│   │   └── .gitkeep
│   ├── processed/
│   │   └── .gitkeep
│   ├── raw/
│   │   └── .gitkeep
│   ├── corpus_manifest.template.yaml
│   └── corpus_manifest.yaml
├── docs/
│   ├── phase2_design.md
│   └── research_integrity.md
├── experiments/
│   └── registry/
│       └── .gitkeep
├── frontend/
│   └── README.md
├── notebooks/
│   └── .gitkeep
├── reports/
│   └── .gitkeep
├── requirements/
│   ├── README.md
│   ├── base.txt
│   └── dev.txt
├── scripts/
│   └── README.md
├── tests/
│   ├── edge/
│   │   └── __init__.py
│   ├── integration/
│   │   ├── __init__.py
│   │   └── test_cli.py
│   ├── regression/
│   │   └── __init__.py
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_config.py
│   │   ├── test_core_misc.py
│   │   ├── test_env_and_logging.py
│   │   ├── test_manifest_registry_eval.py
│   │   └── test_schemas.py
│   ├── __init__.py
│   └── conftest.py
├── .env.example
├── .gitignore
├── Makefile
├── README.md
└── pyproject.toml
```

`scripts/` and `frontend/` contain only README stubs marked IMPLEMENTATION PENDING. Edge-case tests currently sit beside the code they test, marked
`@pytest.mark.edge`; `tests/edge/` and `tests/regression/` are reserved for pipeline-level
edge cases (Phase 18) and metric-regression guards (Phase 13+).

Packages that contain only a docstring (`api`, `claims`, `generation`, `reranking`,
`retrieval`, `verification`, `utils`) are **IMPLEMENTATION PENDING** and say so in their docstring.
Vector-store interface (`app/retrieval/vector_store.py`, Phase 4): abstract `upsert / query / delete /
count` over `ChunkRecord` + embedding; Chroma is the first adapter; metadata goes through
`ChunkRecord.to_store_metadata()` (scalars only, `None` omitted).

## B. Dependency strategy

* `pyproject.toml`: compatible **ranges** (library view). `requirements/*.txt`: **exact pins** that the suite passed on.
* Pins are *tested*, not "newest": base + dev resolved on Python 3.12.3, then a fresh venv built only from `requirements/dev.txt` reproduced the identical package set and passed all tests. The pydantic lower bound (2.7.4) also passes the suite with warnings-as-errors.
* Only Phase-2 dependencies are pinned (pydantic, PyYAML, pytest, ruff, mypy, types-PyYAML). Heavy ML/API/PDF packages are **not pinned yet**: each is pinned in the phase that first uses it, after installation and tests.
* Deliberately avoided: `pydantic-settings`, `python-dotenv`, `structlog` (small in-repo implementations are fully tested and avoid version coupling).
* `requires-python >=3.10` is declared, but only 3.12.3 was exercised. **Not verified on 3.10/3.11 or Windows.**

## C. Configuration schema (`configs/*.yaml`, `app/core/config.py`)

Precedence: code defaults < YAML (`extends:` chains) < `VERITAS_<SECTION>__<KEY>` env. Unknown keys, wrong types and
inconsistent combinations are errors (no silent ignoring).

| Section | Keys (constraint) |
|---|---|
| `run` | mode `dev\|full`, seed, max_eval_items |
| `paths` | raw/processed/eval/index/manifest/experiments/logs dirs, models_config, models_local_config |
| `ingestion` | allowed_extensions (lowercase, dotted), max_file_size_mb, pdf_parser, ocr_enabled, ocr_languages, min_chars_per_page |
| `chunking` | strategy `fixed\|sentence\|section`, chunk_size (words), chunk_overlap (< size) |
| `embedding` | model_ref, batch_size, normalize, device `auto\|cpu\|cuda\|mps` |
| `vector_store` | backend `chroma`, collection_name, distance |
| `retrieval` | mode `dense\|bm25\|hybrid`, top_k, candidate_k (>= top_k), fusion `rrf\|weighted`, rrf_k, dense_weight, similarity_threshold |
| `reranking` | enabled, model_ref, batch_size |
| `generation` | model_ref, temperature, max_tokens, timeout_s, max_retries |
| `claims` | max_claims_per_answer, min_claim_chars |
| `verification` | nli_model_ref, support/contradiction thresholds (**provisional**), evidence_top_k, max_regeneration_rounds, independent_second_pass |
| `ecs` | scored_claim_types, partial_credit (convention, not tuned) |
| `security` | max_query_chars |
| `logging` | level, json_format, log_to_file |
| `budget` | max_llm_calls, max_total_tokens (`null` = unlimited, only in `eval_full.yaml`) |

Profiles: `default.yaml` (baseline), `dev_cpu.yaml` (CPU, 10 items, DEBUG), `eval_full.yaml` (strict mode, unlimited budget).
Config hash = SHA-256 of canonical JSON (sorted keys, POSIX paths, no secrets) so it is stable across key order and OS.

## D. Environment-variable specification

| Variable | Purpose | Notes |
|---|---|---|
| `VERITAS_GENERATOR_API_KEY` | generator provider key | secret; `SecretStr`; never in config hash, logs or records |
| `VERITAS_API_AUTH_TOKEN` | API authentication (Phase 16) | secret |
| `VERITAS_CONFIG` | config file path | optional |
| `VERITAS_<SECTION>__<KEY>` | override any config value | value parsed as YAML (`10`, `false`, `[.pdf]`); unknown path = error |
| other `VERITAS_*` without `__` | none | warning, ignored |

`.env` is loaded only when asked (`check-config --env-file .env`), existing variables win, error messages never echo line content.
Generator model/base URL are **not** env vars: set them in git-ignored `configs/models.local.yaml`.

## E. Data contracts (`app/schemas/`, all immutable, `extra="forbid"`)

| Contract | Key invariants (enforced + tested) |
|---|---|
| `DocumentMetadata`, `ChunkRecord` | provenance fields; `chunk_id` must start with `<document_id>::`; page/section `None` = unknown, never guessed; `to_store_metadata()` yields scalars only |
| `ClaimRecord` | default `NOT_VERIFIED`; `SUPPORTS`/`CONTRADICTS` **require evidence**; `confidence` requires its `ConfidenceComponents` (no free-floating number) |
| `CitationCheck` | support statuses require corpus existence + evidence chunks; `MISSING_CITATION` cannot name a document |
| `EvidenceCoverageResult` | `score` is `None` (with reason) when nothing is scorable, never 1.0/0.0; counts must sum |
| `EvalItem` | per-annotator labels; `NOT_VERIFIED` invalid as gold; gold citations/passages must be inside `relevant_paper_ids`; no repeated annotator per claim |
| `CorpusManifest`/`PaperEntry` | see H |
| `ModelSpec`/`ModelRegistry` | see I |
| `ExperimentRecord` | tz-aware times; `metrics` empty = not run; `None` metric = not computed |

Updates go through `evolve()` (re-validates), so `model_copy(update=...)` cannot bypass an invariant.
The ECS *formula* is deliberately not implemented here (Phase 12); only its result contract.

## F. Logging design

JSON lines on stderr (optional file under `logs/`), logger namespace `veritas.*`. Fields: `ts` (UTC), `level`, `logger`,
`message`, bound context (`experiment_id`, `request_id`, via `bind_context`), `fields`, `exception`.
Redaction is a best-effort safety net (secret-looking keys, `sk-`/`hf_`/`Bearer` token shapes) applied to message, fields,
context and tracebacks; it does **not** catch arbitrary secret formats, so the real rule is: never log secrets.
`max_tokens`/`total_tokens` are intentionally *not* redacted (tested).

## G. Experiment-ID design

`<system>-<YYYYMMDDTHHMMSSZ>-<config_hash[:8]>`, e.g. `exp_e_veritas-20261003T120000Z-3fa9c1d2`.
System slugs: `exp_a_llm_only ... exp_e_veritas`, ablations `abl_no_bm25`, etc.
Record at `experiments/registry/<id>/record.json`: config snapshot + hash, model specs, dataset fingerprint, seed, git commit/dirty,
hardware + package versions, metrics, latency, token usage, errors. Written atomically; never overwritten (same id = error);
RUNNING -> COMPLETED/FAILED exactly once. Known limit: two runs with identical config in the same second collide (by design, loud).

## H. Dataset manifest design (`data/corpus_manifest.yaml`)

Per paper: source, source id, **version**, URL, **licence + licence URL + date verified + date access checked**, local path,
**sha256**, status (`candidate -> verified -> included | excluded`), `duplicate_of`, `cluster_id`, `split`.
Hard rules: a paper cannot be `included` with an UNVERIFIED licence or missing hash/version/URL/split; duplicates (same hash or
normalised title) are rejected unless the copy is `excluded` with `duplicate_of`; a `cluster_id` cannot span splits.
`corpus_fingerprint()` -> `corpus-<12 hex>` is the dataset version stored in experiment records.
**The manifest is currently empty.** No paper has been selected, downloaded or licence-checked. PDFs are git-ignored; publish identifiers + hashes only.
Split semantics: the index contains all included papers (extra papers are distractors); a question's *gold* papers must lie in that question's split (`check_split_consistency`).
Not done here: arXiv/other network access is blocked in the build sandbox, so corpus acquisition needs your machine (Phase 3).

## I. Model registry (`configs/models.yaml`)

Keys referenced by `*_ref` config fields; roles `generator|embedder|reranker|nli` are validated against the referencing field.
Local HF models count as **pinned only with a full 40-hex commit revision**; API models only with an explicit `model_id`.
`models.local.yaml` (git-ignored) deep-merges over the base. The three local models are **candidates, unpinned and not downloaded**;
the generator `model_id`/`base_url` are intentionally unset. Strict `full` mode refuses to start while any model is unpinned
(`check-config --strict` exit code 3). API-model "pinning" cannot guarantee identical provider behaviour; this is a recorded limitation.
Generator, verifier (NLI) and embedder/reranker are separate registry entries by construction.

## J. Test strategy

Markers: `unit`, `integration`, `edge`, `regression`, `adversarial` (`--strict-markers`). Principles: no network, no real API calls,
no downloaded models; synthetic placeholder ids only (no fabricated papers); every invariant has a positive and a failing test.
Quality gate: `ruff check`, `ruff format --check`, `mypy --strict`, `pytest` (warnings as errors checked on both pydantic bounds).
Mutation sanity check (15 deliberate invariant breaks, all caught) was run once manually; it is not automated yet.
Later phases add: unit per module, PDF->index->query->generate->verify integration, adversarial prompt-injection suite (Phase 19),
and metric regression fixtures once real metrics exist.

## K. Reproducibility strategy

Seeds (`random`, optional `numpy`/`torch`) via `set_global_seed`; `PYTHONHASHSEED=0` set in the Makefile and recorded;
exact pins; config hash; dataset fingerprint; git commit + dirty flag; hardware/package snapshot; model pinning gate; cost guard;
atomic immutable experiment records. Known gaps: LLM APIs may be non-deterministic even at temperature 0; CPU/GPU numerical differences;
`git_dirty=true` runs should not be reported as results.

## Verification evidence (Phase 2)

**Phase 2 snapshot (current results: `PROJECT_STATUS.md`).** Run on Python 3.12.3: `ruff check` and `ruff format --check` clean; `mypy --strict` clean on 48 files; 122 tests passing;
fresh-venv rebuild from pins identical; pydantic 2.7.4 and 2.13.5 both pass with `-W error`; importing core/CLI does not import torch.
