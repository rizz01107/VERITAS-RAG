from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest

from app.core.config import LoggingConfig
from app.core.env import load_dotenv
from app.core.errors import ConfigError
from app.core.logconfig import (
    REDACTED,
    JsonFormatter,
    bind_context,
    configure_logging,
    get_logger,
    redact,
)

pytestmark = pytest.mark.unit


def test_dotenv_parses_and_does_not_override(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text('# c\nA=1\nexport B="two words"\nC=x # inline\nD=keep\n', encoding="utf-8")
    env = {"D": "existing"}
    loaded = load_dotenv(f, env)
    assert env == {"A": "1", "B": "two words", "C": "x", "D": "existing"}
    assert "D" not in loaded


@pytest.mark.edge
def test_dotenv_bad_line_does_not_leak_content(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("SUPERSECRETVALUEWITHOUTEQUALS\n", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_dotenv(f, {})
    assert "SUPERSECRET" not in str(info.value)
    assert "line=1" in str(info.value)


@pytest.mark.edge
def test_dotenv_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_dotenv(tmp_path / "none.env", {})


def test_redact_keys_values_and_nesting() -> None:
    data = {
        "api_key": "abc",
        "Authorization": "Bearer abcdefghijkl",
        "nested": {"password": "p", "ok": "hello sk-abcdefgh12345 world"},
        "max_tokens": 100,
        "total_tokens": 5,
        "list": ["hf_abcdefgh1234", "fine"],
    }
    out = redact(data)
    assert out["api_key"] == REDACTED
    assert out["Authorization"] == REDACTED
    assert out["nested"]["password"] == REDACTED
    assert "sk-abcdefgh12345" not in out["nested"]["ok"]
    assert out["max_tokens"] == 100 and out["total_tokens"] == 5
    assert out["list"] == [REDACTED, "fine"]


def _capture() -> io.StringIO:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("veritas.test")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return buf


def test_json_log_has_context_fields_and_redacts() -> None:
    buf = _capture()
    log = get_logger("test")
    with bind_context(experiment_id="exp-1"):
        log.info("key sk-abcdefgh12345", extra={"fields": {"api_key": "zzz", "n": 3}})
    line = json.loads(buf.getvalue())
    assert line["experiment_id"] == "exp-1"
    assert line["fields"] == {"api_key": REDACTED, "n": 3}
    assert "sk-abcdefgh12345" not in line["message"]
    assert line["level"] == "INFO"


def test_context_does_not_leak_outside_scope() -> None:
    buf = _capture()
    with bind_context(request_id="r1"):
        pass
    get_logger("test").info("after")
    assert "request_id" not in json.loads(buf.getvalue())


def test_exception_traceback_redacted() -> None:
    buf = _capture()
    try:
        raise RuntimeError("failed with Bearer abcdefghijklmnop")
    except RuntimeError:
        get_logger("test").exception("boom")
    assert "abcdefghijklmnop" not in buf.getvalue()


def test_configure_logging_is_idempotent() -> None:
    cfg = LoggingConfig()
    configure_logging(cfg)
    configure_logging(cfg)
    assert len(logging.getLogger("veritas").handlers) == 1


@pytest.mark.edge
def test_file_logging_requires_path() -> None:
    with pytest.raises(ValueError, match="log_file"):
        configure_logging(LoggingConfig(log_to_file=True))


def test_file_logging_writes(tmp_path: Path) -> None:
    configure_logging(LoggingConfig(log_to_file=True), tmp_path / "logs" / "run.log")
    get_logger("x").warning("hello")
    for h in logging.getLogger("veritas").handlers:
        h.flush()
    assert "hello" in (tmp_path / "logs" / "run.log").read_text(encoding="utf-8")
