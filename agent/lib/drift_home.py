"""The single source of truth for ~/.drift — the central home for eval artifacts and
central/demo scan runs. Honors $DRIFT_HOME (used by tests). Does NOT change the plugin's
in-place <folder>/.drift-detector/ outputs."""
from __future__ import annotations

import os


def drift_root() -> str:
    root = os.environ.get("DRIFT_HOME") or os.path.join(os.path.expanduser("~"), ".drift")
    os.makedirs(root, exist_ok=True)
    return root


def reports_home(slug: str) -> str:
    p = os.path.join(drift_root(), "reports", slug)
    os.makedirs(p, exist_ok=True)
    return p


def eval_home() -> str:
    p = os.path.join(drift_root(), "eval")
    os.makedirs(p, exist_ok=True)
    return p
