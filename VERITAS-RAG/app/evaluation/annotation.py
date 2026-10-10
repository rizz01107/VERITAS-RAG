"""Annotation coverage and the mandatory single-annotator disclosure."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.schemas.evaluation import EvalItem

SINGLE_ANNOTATOR_STATEMENT = (
    "Single-annotator evaluation; inter-annotator agreement was not available."
)


@dataclass(frozen=True)
class AnnotationCoverage:
    """How much of the labelled claim set has two or more independent annotators."""

    n_claims: int
    n_labelled: int
    n_double_annotated: int
    annotators: tuple[str, ...]

    @property
    def double_annotated_fraction(self) -> float | None:
        """Fraction of labelled claims with >= 2 annotators (``None`` if none labelled)."""
        return self.n_double_annotated / self.n_labelled if self.n_labelled else None


def annotation_coverage(items: Iterable[EvalItem]) -> AnnotationCoverage:
    """Compute annotation coverage across evaluation items."""
    n_claims = n_labelled = n_double = 0
    annotators: set[str] = set()
    for item in items:
        n_claims += len(item.claims)
        for labels in item.gold_support_labels.values():
            if not labels:
                continue
            n_labelled += 1
            ids = {label.annotator_id for label in labels}
            annotators |= ids
            if len(ids) >= 2:
                n_double += 1
    return AnnotationCoverage(n_claims, n_labelled, n_double, tuple(sorted(annotators)))


def agreement_statement(coverage: AnnotationCoverage) -> str:
    """Disclosure sentence for reports. Never implies agreement that was not measured."""
    if coverage.n_double_annotated == 0:
        return SINGLE_ANNOTATOR_STATEMENT
    fraction = coverage.double_annotated_fraction or 0.0
    return (
        f"{coverage.n_double_annotated} of {coverage.n_labelled} labelled claims "
        f"({fraction:.0%}) were independently annotated by two or more annotators; "
        "agreement statistics apply to that subset only."
    )
