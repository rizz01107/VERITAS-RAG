# Repository software licence (separate from paper licences)

**Status: NOT DECIDED. There is intentionally no `LICENSE` file**, so by default all rights are reserved. Add one only after you decide.

* **What it covers:** the code, tests, configuration and documentation written for this project, and synthetic test data (`tests/pdfgen.py`, `tests/texgen/`; invented text). It does **not** cover the papers: each paper keeps its own licence/copyright (see `data/corpus_manifest.yaml` and `docs/LICENSING.md`).
* **Constraint:** the PDF backend PyMuPDF is AGPL-3.0 or commercial. A public repository that depends on it, and especially a hosted API/web app (Phase 16), needs a licence choice compatible with that. Options: (a) AGPL-3.0 for this repository; (b) buy the commercial PyMuPDF licence; (c) implement and quality-test a permissively licensed `PdfBackend` and keep PyMuPDF optional.
* Ask your supervisor/university; this is not legal advice.
* The repository must never contain PDFs or extracted paper text; `tests/unit/test_split_policy_and_hygiene.py` fails if a `.pdf` or a parsed-document JSON appears outside the git-ignored `data/raw` and `data/processed`.
