# Research integrity protocol

## Novelty claims
No component, result or sentence may be called "novel" because we implemented it. Every manuscript statement is tagged:

| Tag | Meaning |
|---|---|
| EXISTING COMPONENT | published method/metric/dataset we reuse (with verified citation) |
| OUR INTEGRATION | how we combine existing components |
| OUR EMPIRICAL FINDING | measured by our reproducible experiments (experiment ids cited) |
| POTENTIAL CONTRIBUTION | hypothesis not yet supported by our own evidence |

## Literature search (REQUIRED before any novelty claim; status: NOT STARTED)
Topics: scientific RAG; citation verification; citation correctness; claim-level verification; hallucination detection;
evidence-grounded generation; RAG evaluation; scientific question answering; contradiction-aware RAG; citation-aware RAG.
Protocol: record query, source (e.g. Google Scholar, Semantic Scholar, arXiv, ACL Anthology), date, inclusion decision and
reason in `docs/literature_log.csv` (to be created at the start of the search); verify every reference against the primary page
before it enters the report; cover work from the most recent months; no citation from memory.
Phase 1 mentioned several works marked [VERIFY]; they are leads, not verified references.

## Corpus integrity
Licence/access verification per paper is mandatory before inclusion (manifest rules). Do not assume arXiv content has unrestricted reuse rights.

## Annotation integrity
Single annotator by default; the report must state: "Single-annotator evaluation; inter-annotator agreement was not available."
unless a second annotator labelled a subset (`app/evaluation/annotation.py` computes coverage and the disclosure sentence).
