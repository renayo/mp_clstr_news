"""Load the registered study parameters.

Everything the pipeline needs to know about the study comes from
``config/study.yaml`` (parameters) and ``config/rubric.yaml`` (classifier text).
The repository root is located from this file's position so that every entry
point works regardless of the current working directory.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "study.yaml"
RUBRIC_PATH = ROOT / "config" / "rubric.yaml"


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    with open(path or CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_rubric(path: Path | str | None = None) -> dict[str, Any]:
    with open(path or RUBRIC_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def rubric_hash(path: Path | str | None = None) -> str:
    """SHA-256 of the rubric file, byte for byte — the registered prompt hash."""
    return hashlib.sha256(Path(path or RUBRIC_PATH).read_bytes()).hexdigest()


def window_dates(cfg: dict[str, Any]) -> list[dt.date]:
    start = dt.date.fromisoformat(cfg["study"]["window_start"])
    end = dt.date.fromisoformat(cfg["study"]["window_end"])
    n = (end - start).days + 1
    assert n == cfg["study"]["window_days"], (n, cfg["study"]["window_days"])
    return [start + dt.timedelta(days=i) for i in range(n)]


def day_index(cfg: dict[str, Any], date: dt.date) -> int:
    """1-based day number inside the confirmatory window (may be <1 or >N outside it)."""
    start = dt.date.fromisoformat(cfg["study"]["window_start"])
    return (date - start).days + 1


def verified_names(root: Path | str | None = None) -> list[str]:
    """The analysis set: names with verified == 1, in registered file order."""
    p = Path(root or ROOT) / "data" / "body_names.csv"
    df = pd.read_csv(p)
    return df.loc[df["verified"] == 1, "name"].tolist()


def all_names(root: Path | str | None = None) -> pd.DataFrame:
    return pd.read_csv(Path(root or ROOT) / "data" / "body_names.csv")


def unnamed_pool(root: Path | str | None = None) -> list[str]:
    p = Path(root or ROOT) / "data" / "unnamed_pool.txt"
    return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def reference_points(cfg: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(cfg["reference_points"])


def independent_reference_names(cfg: dict[str, Any]) -> list[str]:
    return [r["name"] for r in cfg["reference_points"] if r["independent"]]
