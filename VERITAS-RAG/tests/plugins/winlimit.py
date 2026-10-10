"""Pytest plugin that emulates the Windows limit on environment-variable values.

Windows rejects values longer than 32767 characters (``ValueError: the environment
variable is longer than 32767 characters``). pytest stores the current test id in
``PYTEST_CURRENT_TEST``, so an over-long node id breaks setup and teardown there but not
on Linux. Load with ``-p tests.plugins.winlimit`` to reproduce that failure anywhere.
"""

from __future__ import annotations

import os
from typing import Any

WINDOWS_ENV_VALUE_LIMIT = 32767


def check_env_value_length(value: str) -> None:
    """Raise the Windows error for a value longer than ``WINDOWS_ENV_VALUE_LIMIT`` characters.

    Pure function (touches no environment), so the boundary can be tested on any OS.
    Note: real Windows/CPython counts the whole ``NAME=value`` string, so it rejects slightly
    shorter values than this emulation; the project's test-id guard stays far below both.
    """
    if len(value) > WINDOWS_ENV_VALUE_LIMIT:
        raise ValueError(
            f"the environment variable is longer than {WINDOWS_ENV_VALUE_LIMIT} characters"
        )


class LimitedEnviron(os._Environ):  # type: ignore[type-arg]
    """``os.environ`` that refuses over-long values like Windows does."""

    def __setitem__(self, key: Any, value: Any) -> None:
        check_env_value_length(value)
        super().__setitem__(key, value)


def make_limited_environ(env: Any) -> LimitedEnviron:
    """Copy-wrap ``env`` (an ``os._Environ``) into a limited one sharing the same storage."""

    def attr(name: str) -> Any:
        return getattr(env, name)

    return LimitedEnviron(
        attr("_data"),
        attr("encodekey"),
        attr("decodekey"),
        attr("encodevalue"),
        attr("decodevalue"),
    )


def pytest_configure(config: object) -> None:
    os.environ = make_limited_environ(os.environ)  # noqa: B003 - deliberate Windows emulation
