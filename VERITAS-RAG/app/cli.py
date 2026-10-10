"""Command-line entry point: ``python -m app.cli <command>`` (no frontend/API needed)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.core.config import load_settings, resolve_path
from app.core.device import hardware_info
from app.core.env import load_dotenv
from app.core.envreport import run_report, write_report
from app.core.errors import IngestionFailureError, VeritasError
from app.core.model_registry import load_registry, validate_references
from app.core.readiness import full_evaluation_problems
from app.evaluation.validation import (
    contradiction_clusters,
    contradiction_coverage_problems,
)
from app.ingestion.audit import audit_document, write_spot_check_sheet
from app.ingestion.download import download_pdf
from app.ingestion.io import write_parsed_document
from app.ingestion.manifest import corpus_fingerprint, load_manifest, sha256_file, verify_files
from app.ingestion.pipeline import ingest_file
from app.schemas.manifest import CorpusManifest


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _load_manifest_if_present(path: Path) -> CorpusManifest | None:
    return load_manifest(path) if path.is_file() else None


def _check_config(args: argparse.Namespace) -> int:
    if args.env_file:
        load_dotenv(Path(args.env_file))
    settings = load_settings(args.config)
    registry = load_registry(settings)
    resolved = validate_references(settings, registry)
    manifest = _load_manifest_if_present(resolve_path(settings.paths.manifest_path))
    problems = full_evaluation_problems(settings, registry, manifest)
    _emit(
        {
            "config_hash": settings.config_hash(),
            "run_mode": settings.run.mode,
            "models": {
                key: {
                    "role": spec.role.value,
                    "provider": spec.provider.value,
                    "model_id": spec.model_id,
                    "pinned": spec.is_pinned,
                }
                for key, spec in sorted(resolved.items())
            },
            "dataset_version": corpus_fingerprint(manifest) if manifest else None,
            "full_evaluation_ready": not problems,
            "full_evaluation_problems": problems,
        }
    )
    return 3 if (args.strict and problems) else 0


def _validate_manifest(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    path = Path(args.manifest) if args.manifest else resolve_path(settings.paths.manifest_path)
    manifest = load_manifest(path)
    file_problems = (
        verify_files(manifest, resolve_path(settings.paths.raw_dir)) if args.check_files else []
    )
    _emit(
        {
            "manifest": str(path),
            "n_papers": len(manifest.papers),
            "dataset_version": corpus_fingerprint(manifest),
            "file_problems": file_problems,
            "contradiction_coverage": {
                "planned": {
                    "clusters": {
                        c: sorted(x.value for x in v)
                        for c, v in contradiction_clusters(manifest, planned=True).items()
                    },
                    "problems": contradiction_coverage_problems(manifest, planned=True),
                },
                "actual": {"problems": contradiction_coverage_problems(manifest)},
            },
        }
    )
    return 4 if file_problems else 0


def _select_papers(manifest: CorpusManifest, ids: list[str]) -> list[Any]:
    by_id = {p.paper_id: p for p in manifest.papers}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise IngestionFailureError("file_not_found", f"unknown paper ids: {unknown}", "select")
    return [by_id[i] for i in ids]


def _download(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    manifest = load_manifest(
        Path(args.manifest) if args.manifest else resolve_path(settings.paths.manifest_path)
    )
    raw_root = resolve_path(settings.paths.raw_dir)
    max_bytes = int(settings.ingestion.max_file_size_mb * 1024 * 1024)
    results = []
    for index, paper in enumerate(_select_papers(manifest, args.paper_id)):
        if not paper.pdf_url or paper.local_path is None:
            results.append(
                {"paper_id": paper.paper_id, "status": "skipped", "reason": "no pdf_url/local_path"}
            )
            continue
        if index:
            time.sleep(args.delay)
        try:
            digest = download_pdf(
                paper.pdf_url,
                raw_root / paper.local_path,
                raw_root,
                max_bytes,
                overwrite=args.overwrite,
            )
            results.append({"paper_id": paper.paper_id, "status": "downloaded", "sha256": digest})
        except IngestionFailureError as exc:
            results.append(
                {
                    "paper_id": paper.paper_id,
                    "status": "failed",
                    "reason": exc.failure_code,
                    "message": exc.message,
                }
            )
    _emit(
        {
            "note": "manifest NOT modified; copy sha256 values in after checking each file",
            "results": results,
        }
    )
    return 0 if all(r["status"] != "failed" for r in results) else 5


def _hashes(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    manifest = load_manifest(
        Path(args.manifest) if args.manifest else resolve_path(settings.paths.manifest_path)
    )
    raw_root = resolve_path(settings.paths.raw_dir)
    rows = []
    for paper in manifest.papers:
        if paper.local_path is None:
            continue
        file_path = raw_root / paper.local_path
        rows.append(
            {
                "paper_id": paper.paper_id,
                "file": file_path.name,
                "sha256": sha256_file(file_path) if file_path.is_file() else None,
                "manifest_sha256": paper.sha256,
            }
        )
    _emit({"hashes": rows})
    return 0


def _ingest(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    raw_root = resolve_path(settings.paths.raw_dir)
    out_dir = (
        Path(args.out) if args.out else resolve_path(settings.paths.processed_dir) / "documents"
    )
    jobs: list[tuple[Path, Any]] = []
    if args.file:
        jobs.append((Path(args.file), None))
    if args.paper_id:
        manifest = load_manifest(resolve_path(settings.paths.manifest_path))
        for paper in _select_papers(manifest, args.paper_id):
            jobs.append((raw_root / (paper.local_path or f"{paper.paper_id}.pdf"), paper))
    if not jobs:
        raise IngestionFailureError("file_not_found", "give --file or --paper-id", "select")
    summaries = []
    failed = False
    for path, paper in jobs:
        result = ingest_file(path, settings.ingestion, paper=paper, raw_root=raw_root)
        entry: dict[str, Any] = {
            "file": path.name,
            "status": result.status.value,
            "sha256": result.sha256,
        }
        if result.document is not None:
            doc = result.document
            written = write_parsed_document(doc, out_dir)
            entry.update(
                document_id=doc.metadata.document_id,
                output=written.name,
                pages=len(doc.pages),
                text_layer_pages=sum(p.has_text_layer for p in doc.pages),
                stats=doc.stats,
                warnings=sorted({w.code for w in doc.warnings}),
                headings=[
                    {"page": u.page_number, "level": u.section_level, "title": u.text}
                    for u in doc.units
                    if u.kind.value == "heading"
                ],
            )
        else:
            failed = True
            entry["failure"] = result.failure.model_dump(mode="json") if result.failure else None
        summaries.append(entry)
    _emit({"documents": summaries})
    return 6 if failed else 0


def _audit(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    raw_root = resolve_path(settings.paths.raw_dir)
    docs = []
    reports: list[dict[str, Any]] = []
    for name in args.file:
        path = Path(name)
        result = ingest_file(path, settings.ingestion, raw_root=raw_root)
        if result.document is None:
            reports.append(
                {
                    "file": path.name,
                    "status": "failed",
                    "failure": result.failure.model_dump(mode="json") if result.failure else None,
                }
            )
            continue
        docs.append(result.document)
        reports.append({"file": path.name, **audit_document(result.document)})
    if args.sheet and docs:
        _ = write_spot_check_sheet(docs, Path(args.sheet), seed=settings.run.seed)
    _emit({"audit": reports, "sheet": args.sheet})
    return 0


def _validate_env(args: argparse.Namespace) -> int:
    from app.core.config import PROJECT_ROOT

    report = run_report(PROJECT_ROOT)
    write_report(report, Path(args.out))
    _emit(
        {
            "report": args.out,
            "all_passed": report["all_passed"],
            "gates": {g["gate"]: g["passed"] for g in report["gates"]},
            "environment": report["environment"],
        }
    )
    return 0 if report["all_passed"] else 7


def _hardware(args: argparse.Namespace) -> int:
    _emit(hardware_info(args.device))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(prog="veritas", description="VERITAS-RAG command line")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check-config", help="validate config, model registry and readiness")
    check.add_argument("--config", default=None)
    check.add_argument("--env-file", default=None)
    check.add_argument("--strict", action="store_true", help="exit 3 if not full-eval ready")
    check.set_defaults(func=_check_config)

    manifest = sub.add_parser("validate-manifest", help="validate the corpus manifest")
    manifest.add_argument("--config", default=None)
    manifest.add_argument("--manifest", default=None)
    manifest.add_argument("--check-files", action="store_true", help="verify files and hashes")
    manifest.set_defaults(func=_validate_manifest)

    dl = sub.add_parser("download", help="download named manifest PDFs (explicit ids only)")
    dl.add_argument("--config", default=None)
    dl.add_argument("--manifest", default=None)
    dl.add_argument("--paper-id", action="append", required=True)
    dl.add_argument("--delay", type=float, default=3.0, help="seconds between downloads")
    dl.add_argument("--overwrite", action="store_true")
    dl.set_defaults(func=_download)

    hs = sub.add_parser("hashes", help="print sha256 of local files listed in the manifest")
    hs.add_argument("--config", default=None)
    hs.add_argument("--manifest", default=None)
    hs.set_defaults(func=_hashes)

    ing = sub.add_parser("ingest", help="parse PDFs into structured, provenance-tracked JSON")
    ing.add_argument("--config", default=None)
    ing.add_argument("--file", default=None)
    ing.add_argument("--paper-id", action="append", default=[])
    ing.add_argument("--out", default=None)
    ing.set_defaults(func=_ingest)

    au = sub.add_parser("audit-ingestion", help="indicator report + manual spot-check sheet")
    au.add_argument("--config", default=None)
    au.add_argument("--file", action="append", required=True)
    au.add_argument("--sheet", default=None, help="CSV path for the manual review sheet")
    au.set_defaults(func=_audit)

    ve = sub.add_parser("validate-env", help="run pytest/ruff/mypy and record exact versions")
    ve.add_argument("--out", default="reports/env_validation.json")
    ve.set_defaults(func=_validate_env)

    hw = sub.add_parser("hardware", help="print hardware/package info recorded with experiments")
    hw.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "mps"])
    hw.set_defaults(func=_hardware)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI; typed project errors become a clean message and exit code 2."""
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except VeritasError as exc:
        sys.stderr.write(json.dumps({"error": exc.code, "message": str(exc)}) + "\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
