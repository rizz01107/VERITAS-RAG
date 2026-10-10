# Licensing notes (not legal advice)

## PyMuPDF (the PDF backend)
* Pinned: `PyMuPDF==1.28.2`. The range is `>=1.28.2,<1.29` because the ground-truth tests on a real pdfTeX paper **fail under 1.26.7** (page-1 block order and section assignment differ): extraction results depend on the parser version, which is recorded in every `DocumentMetadata.parser_version`. Re-run the suite before changing the pin.
* Licence, as declared in the installed package metadata: **"Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License"**.
* Implications to decide *before* publishing anything:
  * **Personal/local research use** (running the pipeline on your own machine): no redistribution takes place, so the AGPL's distribution and network-service obligations are not triggered by that use alone.
  * **Publishing this repository** with PyMuPDF as a dependency: the repository itself does not vendor PyMuPDF (it is installed by pip), but a combined work that is distributed, or offered to users over a network (e.g. the Phase 16 API/web app), may need to comply with AGPL-3.0 (offer corresponding source) or use a commercial licence. Choose the repository licence consciously (e.g. AGPL-3.0-compatible) rather than defaulting to MIT/Apache.
  * If that is unacceptable, the parser is isolated behind the `PdfBackend` protocol (`app/ingestion/pipeline.py`) and `app/ingestion/pymupdf_backend.py`; a permissively licensed backend can be written and compared. Parsing quality of any replacement is **unmeasured**.
* Have your supervisor/university confirm AGPL implications for any public or institutional deployment.

## Paper PDFs and extracted text
* The repository must contain only manifests, identifiers, hashes and your own annotations, not PDFs or extracted paper text. `data/raw/*` and `data/processed/*` are git-ignored.
* `ParsedDocument` JSON contains full paper text and therefore lives only in git-ignored `data/processed/`.
* Test PDFs are generated from invented sentences (`tests/pdfgen.py`); no paper text is used in tests.
* An arXiv paper's reuse terms depend on the licence its authors selected (or arXiv's default licence); verify per paper (see `docs/candidate_papers.md`). Short quotations in a report are a separate, citation-based question.
