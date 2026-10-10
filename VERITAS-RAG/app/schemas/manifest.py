"""Corpus manifest contract: provenance, licence and split assignment per paper.

PDFs are never committed; the manifest is the versioned, auditable record of what
the corpus is. A paper cannot be ``included`` until its licence and access have
been verified by a human and its file hash recorded.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.base import IdStr, Sha256Str, StrictModel
from app.schemas.enums import ManifestStatus, Split

UNVERIFIED = "UNVERIFIED"
PaperSource = Literal["arxiv", "acl_anthology", "openreview", "publisher", "other"]
AccessStatus = Literal["unchecked", "freely_accessible", "restricted", "unavailable"]
Recommendation = Literal["recommend_include", "recommend_exclude", "undecided"]
EvidenceRole = Literal["none", "claim", "qualifies"]


def normalize_title(title: str) -> str:
    """Casefold and strip punctuation so near-identical titles compare equal."""
    return re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()


class PaperEntry(StrictModel):
    """One paper in the corpus manifest."""

    paper_id: IdStr
    title: str = Field(min_length=1)
    authors: tuple[str, ...] = ()
    year: int | None = Field(default=None, ge=1950, le=2100)
    source: PaperSource
    source_id: str | None = None
    doi: str | None = None
    venue: str | None = None
    version: str | None = None
    source_url: str | None = None
    pdf_url: str | None = None
    license: str = UNVERIFIED
    license_source: str | None = None
    license_url: str | None = None
    access_status: AccessStatus = "unchecked"
    license_verified_on: date | None = None
    access_checked_on: date | None = None
    license_notes: str = ""
    local_path: Path | None = None
    sha256: Sha256Str | None = None
    status: ManifestStatus = ManifestStatus.CANDIDATE
    exclusion_reason: str | None = None
    duplicate_of: IdStr | None = None
    cluster_id: str | None = None
    split: Split | None = None
    planned_split: Split | None = None
    evidence_role: EvidenceRole = "none"
    topic_tags: tuple[str, ...] = ()
    relevance_note: str = ""
    recommendation: Recommendation = "undecided"
    recommendation_reason: str = ""
    verification_todo: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check_status_rules(self) -> PaperEntry:
        if self.duplicate_of is not None:
            if self.duplicate_of == self.paper_id:
                raise ValueError("duplicate_of cannot reference itself")
            if self.status != ManifestStatus.EXCLUDED:
                raise ValueError("a paper marked duplicate_of must have status 'excluded'")
        if self.status == ManifestStatus.EXCLUDED and not (
            self.exclusion_reason or self.duplicate_of
        ):
            raise ValueError("excluded papers need an exclusion_reason or duplicate_of")
        if self.status == ManifestStatus.INCLUDED:
            missing = [
                name
                for name, ok in {
                    "licence (not UNVERIFIED)": self.license != UNVERIFIED,
                    "license_source": bool(self.license_source),
                    "license_verified_on": self.license_verified_on is not None,
                    "access_status freely_accessible": self.access_status == "freely_accessible",
                    "access_checked_on": self.access_checked_on is not None,
                    "source_url": bool(self.source_url),
                    "version": bool(self.version),
                    "sha256": self.sha256 is not None,
                    "local_path": self.local_path is not None,
                    "split": self.split is not None,
                }.items()
                if not ok
            ]
            if missing:
                raise ValueError(
                    f"included paper {self.paper_id!r} is missing: {', '.join(missing)}"
                )
        if (
            self.status == ManifestStatus.INCLUDED
            and self.planned_split is not None
            and self.split != self.planned_split
        ):
            raise ValueError(
                f"{self.paper_id!r}: split {self.split} differs from planned_split "
                f"{self.planned_split}; change planned_split deliberately"
            )
        return self


class CorpusManifest(StrictModel):
    """The full corpus description."""

    manifest_version: str = Field(min_length=1)
    corpus_name: str = Field(min_length=1)
    description: str = ""
    redistribution_policy: str = ""
    papers: tuple[PaperEntry, ...] = ()

    @model_validator(mode="after")
    def _check_cross_paper_rules(self) -> CorpusManifest:
        problems: list[str] = []
        ids = [paper.paper_id for paper in self.papers]
        folded = [i.casefold() for i in ids]
        for pid in sorted({i for i in ids if folded.count(i.casefold()) > 1}):
            problems.append(f"duplicate paper_id {pid!r} (ids are compared case-insensitively)")
        known = set(ids)
        active = [p for p in self.papers if p.status != ManifestStatus.EXCLUDED]

        for paper in self.papers:
            if paper.duplicate_of is not None and paper.duplicate_of not in known:
                problems.append(f"{paper.paper_id!r}: duplicate_of {paper.duplicate_of!r} unknown")

        seen_hash: dict[str, str] = {}
        seen_title: dict[str, str] = {}
        for paper in active:
            if paper.sha256:
                other = seen_hash.setdefault(paper.sha256, paper.paper_id)
                if other != paper.paper_id:
                    problems.append(f"identical file hash: {other!r} and {paper.paper_id!r}")
            other_title = seen_title.setdefault(normalize_title(paper.title), paper.paper_id)
            if other_title != paper.paper_id:
                problems.append(f"same title: {other_title!r} and {paper.paper_id!r}")

        cluster_splits: dict[str, set[Split]] = {}
        for paper in self.papers:
            if paper.status == ManifestStatus.INCLUDED and paper.cluster_id and paper.split:
                cluster_splits.setdefault(paper.cluster_id, set()).add(paper.split)
        for cluster, splits in sorted(cluster_splits.items()):
            if len(splits) > 1:
                names = ", ".join(sorted(s.value for s in splits))
                problems.append(f"cluster {cluster!r} spans multiple splits ({names})")

        planned: dict[str, set[Split]] = {}
        for paper in active:
            if paper.cluster_id and paper.planned_split:
                planned.setdefault(paper.cluster_id, set()).add(paper.planned_split)
        for cluster, splits in sorted(planned.items()):
            if len(splits) > 1:
                names = ", ".join(sorted(s.value for s in splits))
                problems.append(f"cluster {cluster!r} has conflicting planned splits ({names})")

        if problems:
            raise ValueError("; ".join(problems))
        return self
