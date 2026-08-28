"""The five search cohorts (PREREGISTRATION.md §4.4).

The verified names are assigned once, by a seeded random permutation, to five
cohorts of 225, 225, 224, 224 and 224 names. On day *t* of the window the
cohort ``(t - 1) mod 5`` is searched with a five-day window, so every name is
searched every fifth day and every day is covered for every name.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C


def make_cohorts(names: list[str], seed: int, n_cohorts: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(names))
    parts = np.array_split(perm, n_cohorts)
    rows = []
    for k, idx in enumerate(parts):
        for i in idx:
            rows.append({"name": names[i], "cohort": k})
    df = pd.DataFrame(rows)
    # keep registered file order for readability; cohort membership is what matters
    order = {n: i for i, n in enumerate(names)}
    return df.sort_values("name", key=lambda s: s.map(order)).reset_index(drop=True)


def cohort_for_date(cfg: dict, date: dt.date, n_cohorts: int | None = None) -> int:
    n = n_cohorts or cfg["api"]["layer_c"]["n_cohorts"]
    return (C.day_index(cfg, date) - 1) % n


def load_or_build(cfg: dict, root: Path | None = None) -> pd.DataFrame:
    root = Path(root or C.ROOT)
    p = root / "data" / "search_cohorts.csv"
    if p.exists():
        return pd.read_csv(p)
    df = make_cohorts(C.verified_names(root), cfg["seeds"]["cohorts"],
                      cfg["api"]["layer_c"]["n_cohorts"])
    return df


def main() -> None:
    cfg = C.load_config()
    df = make_cohorts(C.verified_names(), cfg["seeds"]["cohorts"], cfg["api"]["layer_c"]["n_cohorts"])
    out = C.ROOT / "data" / "search_cohorts.csv"
    df.to_csv(out, index=False)
    print(f"wrote {out}: {df['cohort'].value_counts().sort_index().tolist()} names per cohort")


if __name__ == "__main__":
    main()
