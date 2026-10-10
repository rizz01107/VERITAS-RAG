# Dependency pins

| File | Contents | Status |
|---|---|---|
| `base.txt` | runtime deps for Phase 2 (config, schemas, CLI) | pinned, tested |
| `dev.txt` | pytest, ruff, mypy, type stubs (+ base) | pinned, tested |
| ML / API / PDF deps | torch, sentence-transformers, chromadb, rank-bm25, pymupdf, fastapi, ... | **IMPLEMENTATION PENDING**: pinned in the phase that first uses them (3-6, 9, 16) after install + tests |

Rules: pin exactly what the test suite passed on; record the Python version; never
bump a pin without rerunning the suite; `pyproject.toml` holds compatible *ranges*,
`requirements/*.txt` holds the exact tested set.
