"""Evaluation-validity checks (split leakage)."""

from __future__ import annotations

from collections.abc import Iterable

from app.core.errors import EvaluationDataError
from app.schemas.enums import ManifestStatus, Split
from app.schemas.evaluation import EvalItem
from app.schemas.manifest import CorpusManifest


def check_split_consistency(items: Iterable[EvalItem], manifest: CorpusManifest) -> None:
    """Require every gold paper of an item to be included and in the item's own split.

    The retrieval index contains all included papers (others act as distractors); the
    split constrains which papers a question's *gold* evidence may come from, so that
    dev-time tuning cannot see test-cluster evidence.

    Raises:
        EvaluationDataError: listing every violation.
    """
    by_id = {p.paper_id: p for p in manifest.papers}
    problems: list[str] = []
    for item in items:
        for paper_id in item.relevant_paper_ids:
            paper = by_id.get(paper_id)
            if paper is None:
                problems.append(f"{item.question_id}: paper {paper_id!r} not in manifest")
            elif paper.status != ManifestStatus.INCLUDED:
                problems.append(f"{item.question_id}: paper {paper_id!r} is not included")
            elif paper.split != item.split:
                problems.append(
                    f"{item.question_id}: paper {paper_id!r} is in split "
                    f"{paper.split.value if paper.split else None!r}, item is {item.split.value!r}"
                )
    if problems:
        raise EvaluationDataError("; ".join(problems))


def contradiction_clusters(
    manifest: CorpusManifest, planned: bool = False
) -> dict[str, set[Split]]:
    """Clusters holding both a ``claim`` and a ``qualifies`` paper, mapped to their split(s).

    With ``planned=False`` only *included* papers and their real ``split`` count; with
    ``planned=True`` all non-excluded papers and their ``planned_split`` count (a design
    check for candidates, never evidence that the corpus is ready).
    """
    roles: dict[str, set[str]] = {}
    splits: dict[str, set[Split]] = {}
    for paper in manifest.papers:
        if paper.cluster_id is None or paper.evidence_role == "none":
            continue
        if planned:
            if paper.status == ManifestStatus.EXCLUDED:
                continue
            split = paper.planned_split
        else:
            if paper.status != ManifestStatus.INCLUDED:
                continue
            split = paper.split
        roles.setdefault(paper.cluster_id, set()).add(paper.evidence_role)
        if split is not None:
            splits.setdefault(paper.cluster_id, set()).add(split)
    return {c: splits.get(c, set()) for c, r in roles.items() if {"claim", "qualifies"} <= r}


def contradiction_coverage_problems(
    manifest: CorpusManifest,
    required: tuple[Split, ...] = (Split.DEV, Split.TEST),
    planned: bool = False,
) -> list[str]:
    """Problems if any required split lacks its own independent contradiction cluster.

    Each required split needs at least one contradiction cluster that lies entirely in that
    split, and no cluster may be shared between two required splits (that would be leakage).
    """
    clusters = contradiction_clusters(manifest, planned)
    problems = [
        f"contradiction cluster {c!r} spans several splits"
        for c, s in clusters.items()
        if len(s) > 1
    ]
    for split in required:
        if not any(s == {split} for s in clusters.values()):
            problems.append(f"no contradiction cluster is wholly in split {split.value!r}")
    return problems
