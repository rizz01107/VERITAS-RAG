# Phase 3 validation report (post-review)

**Latest status (early October 2026): Phase 3d. Windows pytest verified by the project owner. Phase 3 is NOT complete: real PEFT/LoRA PDF ingestion, metadata/licence verification, SHA-256 hashes and `audit-ingestion` validation are still outstanding (see "Remaining Phase 3 work"). Phase 4 has not started.**

Work done in early October 2026 (exact dates not recorded). Sandbox: Python 3.12.3, Linux, PyMuPDF 1.28.2; Windows result reported by the owner (below). **No real corpus paper, no licence check and no SHA-256 has been obtained by anyone yet.** Experiment fields remain NOT RUN / PENDING EXPERIMENT.

## Actual Windows result (Phase 3d) - recorded as reported by the project owner
Machine: Windows 10.0.26200, Python 3.10.0, PyMuPDF 1.28.2, pytest 8.4.2, mypy 2.4.0, ruff 0.16.10 (raw record: `reports/windows_validation_phase3d.json`).

`python -m pytest -q` -> **236 passed, 15 skipped, 0 failed, 0 errors** in 21.28 s. Skipped: 14 tests because `pdflatex` is not installed, 1 because symlinks are not permitted on that Windows setup. 236 + 15 = 251, the same test count as the Linux run.

History on Windows: the first run exposed two real test defects, both in tests and not in production code, both fixed and re-verified: (1) bytes passed to `parametrize` produced a 181,673-character node id and broke pytest's `PYTEST_CURRENT_TEST` variable (Windows limit 32,767); (2) the regression test for (1) wrote a 32,767-character value into the real `os.environ`, which Windows rejects because it counts `NAME=value`. The suite is now green on both OSes.

What this verifies on Windows: the Windows-path and filename rules, Unicode/space paths, the "file is not locked after ingestion" test (the file is deleted right after parsing), malformed/encrypted/scanned/zero-page PDF handling, size/page limits, deterministic output, the local-server download tests, the manifest/split-policy/hygiene tests, and Python 3.10.0 (the declared lower bound) with PyMuPDF 1.28.2.

What it does NOT verify:
* The 14 real-pdfTeX ground-truth tests did not run on Windows (no `pdflatex`). Reading order, section/reference separation, hyphen repair, ligatures, the `\Delta` fix and booktabs-table reconstruction are verified on Linux only. Install MiKTeX or TeX Live and rerun to cover them.
* The symlink-escape test did not run on Windows.
* `ruff check`, `ruff format --check` and `mypy --strict` were reported PASS for the earlier 3c state; they were not re-reported for 3d (re-run `python -m app.cli validate-env` to record all four gates in one JSON).
* Python 3.11/3.12 on Windows, macOS, and a Windows run with a different PyMuPDF version.
* Nothing here says anything about real PEFT/LoRA PDFs.

## VERIFIED (evidence exists)
* 246 tests pass; `ruff check`, `ruff format --check`, `mypy --strict` clean (71 files), also in a fresh venv built only from `requirements/dev.txt` (identical package set).
* Ground truth on a **real pdfTeX paper with invented text** (5 pages, two-column; variants: 1-col/10pt, 2-col/12pt, 1-col/12pt): all 38 markers in source order; page numbers equal an independent PyMuPDF search; sections and the reference/appendix split equal the LaTeX source; running header and page numbers removed; ligature words and four hyphen-prone words occur exactly as often as in the source; booktabs table rebuilt row by row; title from layout; output JSON byte-identical across runs and across `PYTHONHASHSEED` 0/1/12345.
* 41 deliberate defects injected one at a time (24 earlier + 17 new, after a green baseline): all caught by the tests (one hygiene mutation is equivalent while the repo holds no PDFs; the guard was verified separately by planting a PDF and a JSON with `full_text`: both failed the test).
* Metadata verified from the pages seen: LoRA latest version v2 (stamp on the unversioned PDF: `arXiv:2106.09685v2 [cs.CL] 16 Oct 2021`); P-Tuning v2 submission history v1/v2/v3 with dates; arXiv ids/titles/DOIs of the 8 candidates (see `docs/candidate_papers.md`).

## PARTIALLY VERIFIED
* Real-PDF behaviour: one generated TeX paper plus three non-paper real PDFs found in the sandbox (two font-specimen glyph tables, one design showcase). They exposed warnings and counts only (PUA/U+FFFD characters flagged -> `partial`; heading loss without structured headings -> fixed); no ground truth exists for them.
* Candidate roles (claim/qualifies) and relevance notes come from abstracts, not full texts. P-Tuning v2 author list is incomplete (only the first author observed). Venue/year come from secondary pages for several papers.
* Windows: pytest verified on Windows (see above); the TeX ground-truth tests and the symlink test were skipped there, and lint/format/mypy were not re-reported for 3d.

## NOT VERIFIED (remain UNVERIFIED / PENDING)
* Windows lint/format/mypy for the 3d code and the TeX ground-truth tests on Windows -> run `python -m app.cli validate-env` (writes `reports/env_validation.json`) with `pdflatex` installed, and send the JSON.
* All licences and access status; the exact PDF URL for papers 6, 7; SHA-256 of every paper; whether any paper's text layer is clean; extraction accuracy on real papers (reading order, sections, references, tables, math) -> use `python -m app.cli audit-ingestion --file ... --sheet reports/spot_check.csv` and fill the sheet.
* Parser sensitivity: under PyMuPDF 1.26.7 five ground-truth tests fail (block order differs), so the range is `>=1.28.2,<1.29`.

## Remaining Phase 3 work (all outstanding; owner = you unless stated)
Phase 3 is complete only when every item below is done and recorded. None has been done yet.

| # | Work | How | Done when |
|---|---|---|---|
| R1 | **Choose 5-7 dev papers** from the 8 candidates | e.g. the two clusters you intend for dev/test plus a singleton; confirm cluster roles after skimming | list agreed |
| R2 | **Metadata + licence + access verification** per chosen paper | open the arXiv abs page; record licence shown, `license_source`, `license_url`, `license_verified_on`, `access_checked_on`, `access_status`; confirm title/authors/year/DOI/venue; P-Tuning v2: complete the author list | manifest fields filled from the pages, nothing guessed; unknown stays UNVERIFIED |
| R3 | **Exact PDF URL + version pin** | record latest version from "Submission history"; pin `pdf_url` to it (papers 6 and 7 still have no PDF URL); decide arXiv vs proceedings text for paper 3 | `version` and `pdf_url` set |
| R4 | **Download** (outside the repo) | `python -m app.cli download --paper-id <id>` per paper (explicit ids, 3 s delay); files land in git-ignored `data/raw/` | files present |
| R5 | **SHA-256 hashes** | `python -m app.cli hashes`, copy into `sha256`; then `python -m app.cli validate-manifest --check-files` | hashes match; no duplicate hashes/versions |
| R6 | **Mark inclusion** | only after R2-R5: `status: included`, `split` = `planned_split` (or change `planned_split` deliberately) | `validate-manifest` passes; the schema refuses `included` otherwise |
| R7 | **Real-PDF ingestion** | `python -m app.cli ingest --paper-id <id>` for each included paper | every paper `ok` or explained `partial`; no `failed` |
| R8 | **audit-ingestion validation** | `python -m app.cli audit-ingestion --file data/raw/<file>.pdf --sheet reports/spot_check.csv`; review indicators (page/column counts, headings vs the PDF, reference fraction, residual hyphens, U+FFFD/PUA, duplicates, tables) and fill the spot-check sheet (5 random units + all tables/headings per paper: text fidelity, reading order, page, section) | sheet complete; concrete failures listed, not "looks good" |
| R9 | **Fix real-PDF bugs** (assistant) | each fix with a regression test; no speculative features | failures from R8 resolved or documented as limitations |
| R10 | **Re-run gates** | `python -m pytest -q` (Linux and Windows, ideally with `pdflatex` installed), ruff, format, mypy strict; mutation and determinism re-checks (assistant) | all green; this report updated |
| R11 | **Decisions** | repository software licence (`docs/SOFTWARE_LICENSE.md`, undecided); confirm split policy | recorded |
| R12 | **Windows TeX coverage (optional)** | install MiKTeX/TeX Live so the 14 skipped ground-truth tests run | skips drop to symlink only |

Not part of Phase 3 and not started: chunking comparison, Chroma indexing, retrieval, any benchmark or metric. All experiment fields remain NOT RUN / PENDING EXPERIMENT.

## Defects found on real TeX/PDF output and fixed (each has a regression test)
| # | Concrete failure | Fix |
|---|---|---|
| 1 | Title "A Synthetic Study ..." was read as a letter-numbered appendix heading; title fell back to the file name | title exclusion uses digit numbering only |
| 2 | Author line "Ada Example / Bob Sample" became a section heading | style-only headings need a prior numbered/known heading (unless the document has none; measured on real PDFs: otherwise every heading of such documents was lost) |
| 3 | `\Delta` extracted as U+2206 (increment) instead of U+0394 | normalised and counted (`symbols_normalized`) |
| 4 | Words split by a hyphen across a column/page break stayed broken (3 on 5 pages) | repair across blocks; merged unit gets `page_end` |
| 5 | Booktabs table collapsed to one text line; the library's column guess cut words ("Me\|thod") and failed in other layouts | detect equal-width horizontal rules, rebuild rows from word positions |
| 6 | Audit: stale "observed" dates and ids that differ only by case | dates corrected; manifest ids unique case-insensitively |

## Measured but not fixed (limitations)
* Superscript/subscript structure is flattened ("Rd×r", "W0x"); footnote markers fuse with the preceding word ("MK0011") and the footnote becomes its own unit at the column bottom; the paragraph continuing across a column break without a hyphen stays two units.
* Three-column layouts, rotated pages (flagged), unruled non-rule tables, right-to-left text are untested or unsupported.
* Automated indicators (`audit-ingestion`) detect defect classes, not accuracy; only the manual sheet measures quality.
