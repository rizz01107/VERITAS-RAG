"""Global seeding for reproducibility (only libraries that are actually installed)."""

from __future__ import annotations

import importlib
import importlib.util
import random

from app.core.device import load_torch


def set_global_seed(seed: int) -> list[str]:
    """Seed ``random`` and, if installed, ``numpy`` and ``torch``. Returns what was seeded.

    ``PYTHONHASHSEED`` cannot be changed after interpreter start; set it in the shell
    (the Makefile does) and it is recorded in experiment hardware info.
    """
    if not 0 <= seed < 2**32:
        raise ValueError("seed must be in [0, 2**32)")
    random.seed(seed)
    seeded = ["random"]
    if importlib.util.find_spec("numpy") is not None:
        importlib.import_module("numpy").random.seed(seed)
        seeded.append("numpy")
    torch = load_torch()
    if torch is not None:
        torch.manual_seed(seed)
        seeded.append("torch")
    return seeded
