from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.core.envreport import collect_environment, run_gate, run_report, write_report

pytestmark = pytest.mark.unit


def test_environment_has_exact_versions() -> None:
    env = collect_environment()
    assert env["python"].startswith(sys.version.split()[0])
    assert env["packages"]["pydantic"] and env["packages"]["pymupdf"]
    assert {"os_platform", "os_version", "machine", "pdflatex_available"} <= set(env)


def test_gate_captures_pass_fail_and_tail(tmp_path: Path) -> None:
    ok = run_gate("ok", ["-c", "print('hello')"], tmp_path)
    bad = run_gate("bad", ["-c", "import sys; print('boom'); sys.exit(3)"], tmp_path)
    assert ok["passed"] and ok["tail"] == ["hello"]
    assert not bad["passed"] and bad["returncode"] == 3 and "boom" in bad["tail"][-1]


@pytest.mark.edge
def test_gate_handles_unicode_output_and_timeout(tmp_path: Path) -> None:
    uni = run_gate(
        "u", ["-c", "import sys; sys.stdout.buffer.write('α∆ \\ufb01'.encode('utf-8'))"], tmp_path
    )
    assert uni["passed"] and "α" in uni["tail"][0]
    slow = run_gate("slow", ["-c", "import time; time.sleep(5)"], tmp_path, timeout_s=0.5)
    assert slow["passed"] is False and slow["error"] == "TimeoutExpired"


def test_report_roundtrip(tmp_path: Path) -> None:
    report = run_report(tmp_path, {"one": ["-c", "pass"], "two": ["-c", "raise SystemExit(1)"]})
    assert report["all_passed"] is False
    target = tmp_path / "sub" / "r.json"
    write_report(report, target)
    assert json.loads(target.read_text(encoding="utf-8"))["gates"][0]["gate"] == "one"
