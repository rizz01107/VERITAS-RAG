"""Closed vocabularies shared across the pipeline."""

from __future__ import annotations

from enum import Enum


class ClaimType(str, Enum):
    """Kind of statement extracted from an answer."""

    FACTUAL = "factual"
    NUMERICAL = "numerical"
    COMPARATIVE = "comparative"
    CAUSAL = "causal"
    DEFINITIONAL = "definitional"
    METHODOLOGICAL = "methodological"
    OPINION = "opinion"
    SPECULATIVE = "speculative"


class VerificationStatus(str, Enum):
    """Claim-level verdict. ``NOT_VERIFIED`` is the default and is never support."""

    NOT_VERIFIED = "NOT_VERIFIED"
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    DOES_NOT_PROVIDE_ENOUGH_EVIDENCE = "DOES_NOT_PROVIDE_ENOUGH_EVIDENCE"


class CitationStatus(str, Enum):
    """Citation-level verdict."""

    VALID_SUPPORT = "VALID_SUPPORT"
    PARTIAL_SUPPORT = "PARTIAL_SUPPORT"
    CONTRADICTED = "CONTRADICTED"
    IRRELEVANT = "IRRELEVANT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    MISSING_CITATION = "MISSING_CITATION"


class NliLabel(str, Enum):
    """Output label of an entailment model."""

    ENTAILMENT = "entailment"
    CONTRADICTION = "contradiction"
    NEUTRAL = "neutral"


class Split(str, Enum):
    """Evaluation split."""

    TRAIN = "train"
    DEV = "dev"
    TEST = "test"


class ModelRole(str, Enum):
    """Function a registered model serves."""

    GENERATOR = "generator"
    EMBEDDER = "embedder"
    RERANKER = "reranker"
    NLI = "nli"


class ModelProvider(str, Enum):
    """How a model is invoked."""

    HUGGINGFACE_LOCAL = "huggingface_local"
    OPENAI_COMPATIBLE = "openai_compatible"


class ParseStatus(str, Enum):
    """Outcome of parsing a source document."""

    OK = "ok"
    PARTIAL = "partial"
    OCR_FALLBACK = "ocr_fallback"
    FAILED = "failed"


class ManifestStatus(str, Enum):
    """Lifecycle state of a paper in the corpus manifest."""

    CANDIDATE = "candidate"
    VERIFIED = "verified"
    INCLUDED = "included"
    EXCLUDED = "excluded"


class ExperimentStatus(str, Enum):
    """Lifecycle state of an experiment record."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
