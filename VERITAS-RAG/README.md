# VERITAS-RAG

**Evidence-Aware Scientific RAG with Claim-Level Hallucination and Citation Verification**

> This repository reports experimental results only after reproducible evaluation.
> **No experiment has been run yet. All results are NOT RUN / PENDING EXPERIMENT.**

VERITAS-RAG is a research project, not a PDF chatbot. The goal is to test whether claim-level evidence retrieval and citation verification reduces unsupported claims and citation errors in RAG-generated answers about scientific papers. The domain is deliberately narrow: parameter-efficient fine-tuning (LoRA, QLoRA, adapters, soft prompts).

**Research question:** *Can claim-level evidence retrieval and citation verification reduce unsupported claims and citation errors in scientific RAG-generated answers?*

Planned comparison (not yet implemented): LLM-only, basic vector RAG, hybrid RAG, hybrid RAG + cross-encoder reranking, and VERITAS-RAG (claim extraction, per-claim evidence retrieval, entailment/contradiction analysis, citation verification, and a transparent Evidence Coverage Score).

## Current status

Only the foundation exists: configuration, data contracts, and document ingestion with provenance. See [`PROJECT_STATUS.md`](PROJECT_STATUS.md) for the exact state, test results and open work.

| Area | State |
|---|---|
| Config, schemas, logging, experiment records, model registry (Phase 2) | implemented and tested |
| PDF ingestion with page/section/offset provenance (Phase 3) | implemented; tested on synthetic and generated-TeX PDFs; **not yet run on real PEFT/LoRA papers** |
| Corpus | 8 **candidate** papers listed; **0 included**; every licence UNVERIFIED; no SHA-256 recorded; no PDFs in this repository |
| Chunking, indexing, retrieval, reranking, generation, claim/citation verification, evaluation, API, frontend (Phases 4-19) | **not started** |
| Experimental results, metrics, human evaluation | **none** |

## Repository layout

```
app/            core/ (config, logging, experiments, device), schemas/ (data contracts),
                ingestion/ (PDF pipeline, manifest, download, audit), evaluation/ (split-leakage
                and contradiction-coverage checks, annotation coverage); other packages are
                placeholders marked IMPLEMENTATION PENDING
configs/        default.yaml, dev_cpu.yaml, eval_full.yaml, models.yaml (model registry)
data/           corpus_manifest.yaml (candidates only), template; raw/ and processed/ are git-ignored
docs/           design notes, validation report, candidate papers, split policy, licensing
experiments/    registry/ for immutable experiment records (empty)
reports/        validation records
requirements/   pinned, tested dependency sets
scripts/ frontend/ notebooks/   placeholders (frontend: React + Vite planned, independent of the pipeline)
tests/          unit, integration, edge-case and audit tests; synthetic PDF generators
```

## Quick start

Requires Python 3.10+ (tested: 3.12.3 on Linux, 3.10.0 on Windows 10).

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1      Linux/macOS: source .venv/bin/activate
pip install -r requirements/dev.txt
pip install -e . --no-deps
python -m pytest -q
ruff check . && ruff format --check . && mypy --strict
python -m app.cli check-config --config configs/dev_cpu.yaml
```

No `make` is needed (a `Makefile` exists for Linux/macOS convenience). Secrets go in a git-ignored `.env` (copy `.env.example`); no API key is needed for anything that exists today.

### Command-line tools

```
python -m app.cli validate-manifest [--check-files]   # manifest rules, dataset version, split policy report
python -m app.cli download --paper-id <id>            # explicit ids only; you verify licences first
python -m app.cli hashes                              # SHA-256 of local files listed in the manifest
python -m app.cli ingest --paper-id <id> | --file <pdf>
python -m app.cli audit-ingestion --file <pdf> --sheet reports/spot_check.csv
python -m app.cli validate-env                        # versions + pytest/ruff/mypy gates -> JSON
```

## Data, copyright and licences

* **No paper PDFs or extracted paper text are committed.** `.gitignore` excludes `*.pdf`, `data/raw/*` and `data/processed/*`, and a test fails if a PDF or a parsed-document JSON appears in a tracked location. Only metadata, identifiers, hashes and your own annotations belong in git.
* A paper becomes `included` only after a human verifies its licence and access; the manifest schema refuses otherwise. See [`docs/candidate_papers.md`](docs/candidate_papers.md).
* **Software licence: not chosen yet.** There is intentionally no `LICENSE` file (all rights reserved by default). The PDF backend PyMuPDF is AGPL-3.0 or commercial, which constrains the choice: read [`docs/SOFTWARE_LICENSE.md`](docs/SOFTWARE_LICENSE.md) and [`docs/LICENSING.md`](docs/LICENSING.md) before making the repository public. This is not legal advice.

## Documentation

| File | Content |
|---|---|
| [`PROJECT_STATUS.md`](PROJECT_STATUS.md) | exact status, actual test results, verified vs unverified, remaining work |
| [`docs/phase2_design.md`](docs/phase2_design.md) | configuration, contracts, logging, experiment ids, manifest and registry design |
| [`docs/phase3_design.md`](docs/phase3_design.md) | ingestion design, OCR decision, Windows notes, limitations |
| [`docs/phase3_validation.md`](docs/phase3_validation.md) | validation report incl. actual Windows run and remaining Phase 3 work |
| [`docs/candidate_papers.md`](docs/candidate_papers.md) | 8 candidate papers, what was and was not verified |
| [`docs/split_policy.md`](docs/split_policy.md) | leakage-safe split and contradiction-cluster policy |
| [`docs/research_integrity.md`](docs/research_integrity.md) | novelty-claim rules and literature-search protocol (search not started) |
| [`docs/LICENSING.md`](docs/LICENSING.md), [`docs/SOFTWARE_LICENSE.md`](docs/SOFTWARE_LICENSE.md) | PyMuPDF, paper and repository licensing |

## Known limitations

Ingestion heuristics (reading order, headings, tables, hyphen repair) were validated on synthetic PDFs and one generated pdfTeX paper only; OCR is not implemented; three-column layouts and sub/superscript structure are not handled; extraction results depend on the PyMuPDF version (`>=1.28.2,<1.29`). Details: `docs/phase3_validation.md`.

## Roadmap

Finish Phase 3 on real papers, then chunking comparison and Chroma behind a vector-store interface, hybrid retrieval and reranking, grounded generation, claim extraction, evidence/citation/contradiction verification, evaluation framework and baselines, ablations, error analysis, API, React + Vite dashboard, security audit. Nothing past Phase 3 has been started. A literature search (required before any novelty claim) has not been performed.

## Citation

No manuscript or citable release exists yet. A citation entry will be added only if one is produced.
