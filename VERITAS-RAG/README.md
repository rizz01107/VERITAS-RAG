# VERITAS-RAG

**Evidence-Aware Scientific RAG with Claim-Level Hallucination and Citation Verification**

> This repository reports experimental results only after reproducible evaluation.
>
> **No experiment has been run yet. All results are `NOT RUN / PENDING EXPERIMENT`.**

VERITAS-RAG is a research project, not a PDF chatbot. The goal is to test whether claim-level evidence retrieval and citation verification reduce unsupported claims and citation errors in RAG-generated answers about scientific papers.

The research domain is deliberately narrow: **parameter-efficient fine-tuning (LoRA, QLoRA, adapters, and soft prompts).**

**Research Question:** *Can claim-level evidence retrieval and citation verification reduce unsupported claims and citation errors in scientific RAG-generated answers?*

**Planned Comparison — Not Yet Implemented:** LLM-only, basic vector RAG, hybrid RAG, hybrid RAG + cross-encoder reranking, and VERITAS-RAG with claim extraction, per-claim evidence retrieval, entailment/contradiction analysis, citation verification, and a transparent Evidence Coverage Score.

---

## 📌 Current Status

Only the foundation exists: configuration, data contracts, and document ingestion with provenance.

See [`PROJECT_STATUS.md`](PROJECT_STATUS.md) for the exact implementation status, test results, and remaining work.

| Area | State |
|---|---|
| Configuration, schemas, logging, experiment records, model registry (Phase 2) | Implemented and tested |
| PDF ingestion with page/section/offset provenance (Phase 3) | Implemented; tested on synthetic and generated-TeX PDFs; **not yet run on real PEFT/LoRA papers** |
| Research corpus | 8 **candidate** papers listed; **0 included**; all licences unverified; no SHA-256 hashes recorded; no PDFs in the repository |
| Chunking, indexing, retrieval, reranking, generation, claim/citation verification, evaluation, API, frontend (Phases 4–19) | **Not started** |
| Experimental results, metrics, human evaluation | **None available** |

---

## 📂 Repository Layout

```text
app/
├── core/          # Configuration, logging, experiments, device utilities
├── schemas/       # Data contracts
├── ingestion/     # PDF pipeline, manifest, download, audit
└── evaluation/    # Split-leakage, contradiction-coverage and annotation checks

configs/           # Default, CPU, evaluation and model registry configs
data/              # Corpus manifest and templates; raw/processed data ignored
docs/              # Design, validation, candidate papers, split policy, licensing
experiments/       # Experiment registry (currently empty)
reports/           # Validation records
requirements/      # Pinned, tested dependency sets
scripts/           # Utility scripts
frontend/          # Planned React + Vite interface
notebooks/         # Research notebook placeholders
tests/             # Unit, integration, edge-case and audit tests
```

Other packages may contain placeholders marked `IMPLEMENTATION PENDING`.

---

## 🚀 Quick Start

**Requirements:** Python 3.10+ (tested with Python 3.12.3 on Linux and Python 3.10.0 on Windows 10).

### 1. Create a virtual environment

```bash
python -m venv .venv
```

### 2. Activate the environment

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# Linux/macOS
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements/dev.txt
pip install -e . --no-deps
```

### 4. Run validation checks

```bash
python -m pytest -q
ruff check .
ruff format --check .
mypy --strict
python -m app.cli check-config --config configs/dev_cpu.yaml
```

A `Makefile` is available for Linux/macOS convenience, but `make` is not required.

Secrets should be stored in a git-ignored `.env` file, based on `.env.example`. No API key is required for the functionality currently implemented.

### Command-Line Tools

```bash
# Validate manifest and dataset rules
python -m app.cli validate-manifest --check-files

# Download a paper using an explicit identifier
python -m app.cli download --paper-id <id>

# Calculate SHA-256 hashes
python -m app.cli hashes

# Ingest a PDF
python -m app.cli ingest --file <pdf>

# Audit PDF ingestion
python -m app.cli audit-ingestion --file <pdf> --sheet reports/spot_check.csv

# Validate the environment
python -m app.cli validate-env
```

Check the CLI help and project documentation for supported options. Verify paper licensing and access before downloading or including documents.

---

## 🔐 Data, Copyright and Licensing

- **No research paper PDFs or extracted paper text are committed.** `.gitignore` excludes PDF files and `data/raw/` and `data/processed/`. Tests also check that PDFs and parsed-document JSON files are not tracked.
- Only metadata, identifiers, hashes, and original annotations belong in Git.
- A paper can be marked `included` only after a human verifies its licence and access conditions.
- **Software licence: not selected yet.** No `LICENSE` file is present, so default copyright restrictions apply.

PyMuPDF is available under AGPL-3.0 or a commercial licence. Review the following documents before choosing a software licence or distributing the repository:

- [`docs/candidate_papers.md`](docs/candidate_papers.md)
- [`docs/SOFTWARE_LICENSE.md`](docs/SOFTWARE_LICENSE.md)
- [`docs/LICENSING.md`](docs/LICENSING.md)

This is not legal advice.

---

## 📚 Documentation

| Document | Content |
|---|---|
| [`PROJECT_STATUS.md`](PROJECT_STATUS.md) | Exact status, actual test results, verified vs. unverified work |
| [`docs/phase2_design.md`](docs/phase2_design.md) | Configuration, contracts, logging, experiment IDs, manifest and registry |
| [`docs/phase3_design.md`](docs/phase3_design.md) | Ingestion design, OCR decisions, Windows notes and limitations |
| [`docs/phase3_validation.md`](docs/phase3_validation.md) | Validation report, Windows testing and remaining Phase 3 work |
| [`docs/candidate_papers.md`](docs/candidate_papers.md) | Eight candidate papers and their verification status |
| [`docs/split_policy.md`](docs/split_policy.md) | Leakage-safe splitting and contradiction-cluster policy |
| [`docs/research_integrity.md`](docs/research_integrity.md) | Novelty-claim rules and literature-search protocol |
| [`docs/LICENSING.md`](docs/LICENSING.md) | Paper, dependency and repository licensing |
| [`docs/SOFTWARE_LICENSE.md`](docs/SOFTWARE_LICENSE.md) | Software licensing considerations |

---

## ⚠️ Known Limitations

The ingestion heuristics—including reading order, heading detection, tables, and hyphen repair—were validated on synthetic PDFs and one generated pdfTeX paper only.

- OCR is not implemented.
- Three-column layouts are not reliably handled.
- Superscript/subscript structure is not fully handled.
- Extraction results depend on the PyMuPDF version (`>=1.28.2,<1.29`).

See [`docs/phase3_validation.md`](docs/phase3_validation.md) for details.

---

## 🗺️ Roadmap

1. Complete Phase 3 validation on real, appropriately licensed research papers.
2. Compare chunking strategies and implement Chroma behind a vector-store interface.
3. Implement hybrid retrieval and reranking.
4. Develop grounded generation and claim extraction.
5. Implement evidence, citation, and contradiction verification.
6. Establish evaluation frameworks, baselines, and ablation studies.
7. Perform error analysis and report reproducible experimental results.
8. Develop an API and React + Vite dashboard.
9. Complete a security audit.

**Nothing beyond Phase 3 has been started.** A literature search is required before making any novelty claims and has not yet been performed.

---

## 📖 Citation

No manuscript or citable research release exists yet. A citation entry will be added if one is produced.

---

**Author:** Muhammad Rizwan

[GitHub](https://github.com/rizz01107) · [LinkedIn](https://www.linkedin.com/in/rizz01107)

---

*VERITAS-RAG is an ongoing research project. Planned features and research goals should not be interpreted as completed functionality or validated experimental results.*
