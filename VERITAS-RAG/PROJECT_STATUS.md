# PROJECT STATUS

Snapshot at packaging: **2026-10-10**, package version 0.1.0 (`pyproject.toml`).
This file states what exists, what was actually verified, and what is still open. **No research result exists; nothing below claims one.**

## Where the project is
Foundation only: configuration, data contracts, structured logging, experiment records, model registry (Phase 2) and document ingestion with provenance (Phase 3). Phase 3 is **not complete** because it has not been run on real PEFT/LoRA papers. Phases 4-20 (chunking, Chroma, retrieval, reranking, generation, claim/citation/contradiction verification, evaluation, baselines, ablations, API, frontend, security audit) are **not started**. The required literature search has **not** been performed, so no novelty claim is made.

## Test and quality results (actual runs)

| Where | Command | Result |
|---|---|---|
| Linux 6.18, Python 3.12.3, PyMuPDF 1.28.2, pydantic 2.13.5; fresh venv built only from `requirements/dev.txt`, run on a clean `git archive` of this tree | `python -m pytest -q` | **251 passed** |
| same | `python -m pytest -q -p tests.plugins.winlimit` (emulates Windows' 32,767-character env-var limit) | **251 passed** |
| same | `ruff check .` / `ruff format --check .` / `mypy --strict` | pass / pass (88 files reported by ruff) / pass (75 files) |
| Windows 10.0.26200, Python 3.10.0, PyMuPDF 1.28.2 (**run by the project owner, reported to the assistant, not reproduced by it**) | `python -m pytest -q` on Phase 3d | **236 passed, 15 skipped, 0 failed** (14 skipped: `pdflatex` not installed; 1: symlinks not permitted) |

Code, tests, configs and requirements in this package are identical to the commit the owner ran on Windows (checked with `git diff`); only documentation, `README.md`, `.gitignore`, the manifest comments and `reports/` changed afterwards. Windows ruff/format/mypy were reported PASS for the earlier Phase 3c state and were not re-reported for 3d. Not run anywhere: macOS, Python 3.11, the 14 TeX ground-truth tests on Windows.

## Verified / partially verified / not verified
**Verified:** the test suites above; deterministic ingestion output (byte-identical across runs and `PYTHONHASHSEED` values, on Linux); ground-truth checks on a *generated* pdfTeX paper with invented text (reading order, page numbers, sections, references, hyphen repair, ligatures, booktabs table), Linux only; 41 injected defects were caught by the tests (mutation checks, earlier snapshot); LoRA arXiv version v2 (stamp on the PDF).
**Partially verified:** candidate metadata (titles, authors, arXiv ids, DOIs from pages seen; several venues from secondary sources; P-Tuning v2 author list incomplete); contradiction-cluster roles (from abstracts only); real-PDF behaviour (three non-paper PDFs, no ground truth).
**Not verified (UNVERIFIED / PENDING):** every paper's licence and access status; latest versions of 6 of the 8 candidates; PDF URLs for two candidates; SHA-256 of every paper (no PDF has been downloaded); ingestion quality on any real corpus paper; OCR (not implemented); anything about retrieval, verification, hallucination detection or the Evidence Coverage Score formula (not implemented).

## Corpus (candidates only; 0 included)
| paper_id | cluster | planned split | role |
|---|---|---|---|
| arxiv-2106.09685 (LoRA) | lora-family | test | claim |
| arxiv-2305.14314 (QLoRA) | lora-family | test | claim |
| arxiv-2405.09673 (LoRA Learns Less and Forgets Less) | lora-family | test | qualifies |
| arxiv-2410.21228 (LoRA vs Full Fine-tuning: An Illusion of Equivalence) | lora-family | test | qualifies |
| arxiv-2101.00190 (Prefix-Tuning) | soft-prompts | dev | claim |
| arxiv-2104.08691 (Prompt Tuning) | soft-prompts | dev | claim |
| arxiv-2110.07602 (P-Tuning v2) | soft-prompts | dev | qualifies |
| arxiv-1902.00751 (Adapters) | adapters | train | none |

All licences UNVERIFIED; splits are proposals. One contradiction cluster per split, so any contradiction result would be case-study level (`docs/split_policy.md`). Observation dates in the manifest were not recorded exactly (early October 2026): re-verify everything against the source pages.

## Remaining work (details and commands: `docs/phase3_validation.md`)
1. **You:** pick 5-7 dev papers; verify metadata, licence and access from the source pages; record version and exact PDF URL; download outside git; compute SHA-256; mark `included` (the schema refuses otherwise).
2. **You:** run `ingest` and `audit-ingestion` on those PDFs and fill `reports/spot_check.csv`; report concrete failures.
3. **Assistant:** fix real-PDF failures with regression tests; re-run all gates; update this file.
4. **You:** decide the repository software licence (none chosen; PyMuPDF is AGPL-3.0/commercial) before making the repository public; confirm the split policy.
5. Optional: install `pdflatex` on Windows so the 14 skipped tests run.
6. Only then: Phase 4 plan (chunking comparison, Chroma behind an interface). Literature search before any novelty claim.

## Integrity notes
* Strings that look like API keys inside `tests/` (for example `sk-...`) are fake fixtures used to test log redaction. `.env.example` has empty values; no `.env`, key, PDF or virtual environment is in this package.
* The experiment registry is empty; every metric field is NOT RUN / PENDING EXPERIMENT.
* Model entries in `configs/models.yaml` are candidates (unpinned, not downloaded); the generator model and endpoint are intentionally unset.

## Package contents (tracked files: 108)
```
VERITAS-RAG/
├── app/               50 files  source (core, schemas, ingestion, evaluation; other packages = placeholders)
├── configs/            5 files  YAML configs + model registry
├── data/               5 files  candidate manifest + template (no papers)
├── docs/               8 files  design, validation, licensing, split policy
├── experiments/        1 files  empty registry for experiment records
├── frontend/           1 files  placeholder (React + Vite planned)
├── notebooks/          1 files  placeholder
├── reports/            2 files  validation records
├── requirements/       3 files  pinned dependency sets
├── scripts/            1 files  placeholder
├── tests/             25 files  unit / integration / edge / audit tests + synthetic generators
├── .env.example
├── .gitignore
├── Makefile
├── PROJECT_STATUS.md
├── README.md
├── pyproject.toml
```
