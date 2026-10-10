"""Structured (JSON) logging with best-effort secret redaction and bound context.

Redaction is a safety net, not the primary defence: the primary defence is never
passing secrets to loggers. Patterns cover common key/value shapes only.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from app.core.config import LoggingConfig

REDACTED = "[REDACTED]"
ROOT_LOGGER = "veritas"
_HANDLER_MARK = "_veritas_handler"

_SECRET_KEY = re.compile(
    r"(api[_-]?key|secret|passw(or)?d|authorization|auth[_-]?token|access[_-]?token"
    r"|bearer|credential|^token$)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|hf_[A-Za-z0-9]{8,}|Bearer\s+[A-Za-z0-9._~+/\-]{8,}=*)"
)

_CONTEXT: contextvars.ContextVar[Mapping[str, Any] | None] = contextvars.ContextVar(
    "veritas_log_context", default=None
)


def redact(value: Any, key: str | None = None) -> Any:
    """Return ``value`` with secret-looking keys and token-looking strings masked."""
    if key is not None and _SECRET_KEY.search(key):
        return REDACTED
    if isinstance(value, SecretStr):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub(REDACTED, value)
    return value


@contextmanager
def bind_context(**fields: Any) -> Iterator[None]:
    """Attach fields (e.g. ``experiment_id``, ``request_id``) to every log line in scope."""
    token = _CONTEXT.set({**(_CONTEXT.get() or {}), **fields})
    try:
        yield
    finally:
        _CONTEXT.reset(token)


class JsonFormatter(logging.Formatter):
    """One JSON object per line; message, context, fields and tracebacks are redacted."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for key, value in redact(dict(_CONTEXT.get() or {})).items():
            payload.setdefault(key, value)
        fields = getattr(record, "fields", None)
        if isinstance(fields, Mapping):
            payload["fields"] = redact(fields)
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


class RedactingFormatter(logging.Formatter):
    """Plain-text formatter that masks secrets in the rendered line."""

    def format(self, record: logging.LogRecord) -> str:
        return str(redact(super().format(record)))


def reset_logging() -> None:
    """Remove handlers installed by :func:`configure_logging` (idempotency/test helper)."""
    logger = logging.getLogger(ROOT_LOGGER)
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            logger.removeHandler(handler)
            handler.close()
    logger.propagate = True


def configure_logging(cfg: LoggingConfig, log_file: Path | None = None) -> None:
    """Install stderr (and optional file) handlers on the ``veritas`` logger. Idempotent."""
    reset_logging()
    logger = logging.getLogger(ROOT_LOGGER)
    logger.setLevel(cfg.level)
    logger.propagate = False
    formatter: logging.Formatter = (
        JsonFormatter()
        if cfg.json_format
        else RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if cfg.log_to_file:
        if log_file is None:
            raise ValueError("log_to_file is enabled but no log_file path was provided")
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    for handler in handlers:
        handler.setFormatter(formatter)
        setattr(handler, _HANDLER_MARK, True)
        logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a logger in the ``veritas`` namespace."""
    return logging.getLogger(f"{ROOT_LOGGER}.{name}")
