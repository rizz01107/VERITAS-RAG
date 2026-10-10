"""Claim contract. Enforces that support is never asserted without evidence."""

from __future__ import annotations

from pydantic import Field, model_validator

from app.schemas.base import IdStr, StrictModel
from app.schemas.enums import CitationStatus, ClaimType, VerificationStatus
from app.schemas.verification import EvidencePassage


class ConfidenceComponents(StrictModel):
    """Inputs that a confidence value is computed from (all optional, all traceable)."""

    retrieval_score: float | None = None
    rerank_score: float | None = None
    entailment_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    n_independent_sources: int | None = Field(default=None, ge=0)
    citation_status: CitationStatus | None = None


class ClaimRecord(StrictModel):
    """One claim extracted from a generated answer and its verification state."""

    claim_id: IdStr
    claim_text: str = Field(min_length=1)
    claim_type: ClaimType
    source_answer: str
    citation_ids: tuple[str, ...] = ()
    verification_status: VerificationStatus = VerificationStatus.NOT_VERIFIED
    evidence_passages: tuple[EvidencePassage, ...] = ()
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_components: ConfidenceComponents | None = None
    verification_notes: str = ""

    @model_validator(mode="after")
    def _enforce_invariants(self) -> ClaimRecord:
        decided = {VerificationStatus.SUPPORTS, VerificationStatus.CONTRADICTS}
        if self.verification_status in decided and not self.evidence_passages:
            raise ValueError(f"{self.verification_status.value} requires evidence passages")
        if self.confidence is not None and self.confidence_components is None:
            raise ValueError("confidence must come with the components it was computed from")
        return self
