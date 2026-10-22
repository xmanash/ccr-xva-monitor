"""Locate the repository root for data files and docs."""

import os
from pathlib import Path


def repo_root() -> Path:
    env = os.getenv("CCR_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for candidate in [Path.cwd(), *here.parents]:
        if (candidate / "pyproject.toml").exists() and (candidate / "src" / "ccr_xva").exists():
            return candidate
    return Path.cwd()
