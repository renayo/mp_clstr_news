"""Synthetic data for tests and dry runs of the analysis (never for inference).

    python -m mpclstr.synthetic --root /tmp/synth --days 200 --bodies 80 --plant 0.3

Writes a complete fake ``data/ephemeris`` and ``derived/`` set with an optional
planted aspect signal: when ``plant`` > 0, each body's daily count is
inflated by ``1 + plant * Σ_n cos(n·θ_Sun)`` so that the Sun's aspect
harmonics carry structure while every other reference point is noise.
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from .angles import harmonic_kernel, separation


def make_synthetic(root: Path, cfg: dict, days: int = 150, bodies: int = 60, pool: int = 80, plant: float = 0.0,
                   seed: int = 7, quality: bool = True, start: str | None = None) -> None:
    rng = np.random.default_rng(seed)
    root = Path(root)
    (root / "data" / "ephemeris").mkdir(parents=True, exist_ok=True)
    (root / "derived").mkdir(parents=True, exist_ok=True)
    start_date = dt.date.fromisoformat(start or cfg["study"]["window_start"])
    dates = [(start_date + dt.timedelta(days=i)).isoformat() for i in range(days)]
    idx = pd.Index(dates, name="date")
    t = np.arange(days)

    all_names = C.verified_names()
    names = all_names[:bodies]
    # asteroids: linear drift 0.15–0.30 deg/day from random phases
    L = (rng.uniform(0, 360, bodies)[None, :] + rng.uniform(0.15, 0.30, bodies)[None, :] * t[:, None]) % 360
    Lu = (rng.uniform(0, 360, pool)[None, :] + rng.uniform(0.15, 0.30, pool)[None, :] * t[:, None]) % 360
    pd.DataFrame(L, index=idx, columns=names).to_csv(root / "data" / "ephemeris" / "named.csv")
    pool_names = [f"{500000 + i} (2010 XX{i})" for i in range(pool)]
    pd.DataFrame(Lu, index=idx, columns=pool_names).to_csv(root / "data" / "ephemeris" / "unnamed.csv")
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "unnamed_pool.txt").write_text("\n".join(pool_names) + "\n")

    refs = pd.DataFrame(index=idx)
    refs["FPOA"] = 0.0
    rates = {"Sun": 0.9856, "Moon": 13.176, "Mercury": 0.9856, "Venus": 0.9856, "Mars": 0.524,
             "Jupiter": 0.083, "Saturn": 0.033, "Uranus": 0.012, "Neptune": 0.006, "Pluto": 0.004}
    for k, v in rates.items():
        refs[k] = (rng.uniform(0, 360) + v * t) % 360
    refs["Rahu"] = (rng.uniform(0, 360) - 0.053 * t) % 360
    refs["Ketu"] = (refs["Rahu"] + 180) % 360
    refs["Rahu_true"] = (refs["Rahu"] + 1.0 * np.sin(t / 5.0)) % 360
    refs["Ketu_true"] = (refs["Rahu_true"] + 180) % 360
    refs.to_csv(root / "data" / "ephemeris" / "references.csv")

    base = rng.poisson(2.0, size=(days, bodies)).astype(float)
    if plant > 0:
        th = separation(L.T, refs["Sun"].to_numpy())            # (B × T) separation from the Sun
        kern = harmonic_kernel(th, cfg["harmonics"]).astype(float).T   # back to (T × B) for the tables
        base = base * np.clip(1.0 + plant * kern, 0.0, None)
        base = np.round(base)
    N = pd.DataFrame(base, index=idx, columns=names)
    N.to_csv(root / "derived" / "N.csv")
    (N * rng.integers(1, 20, size=N.shape)).to_csv(root / "derived" / "A.csv")
    (N * rng.integers(1, 11, size=N.shape)).to_csv(root / "derived" / "S.csv")
    N.to_csv(root / "derived" / "N_sit.csv")
    N.to_csv(root / "derived" / "E.csv")
    (N * 0).to_csv(root / "derived" / "E_plus.csv")
    pd.DataFrame({"date": dates, "complete": True}).set_index("date").to_csv(root / "derived" / "complete.csv")

    if quality:
        axes = cfg["classification"]["axes"]
        from .derive import label_column
        for axis, labels in axes.items():
            p = rng.dirichlet(np.ones(len(labels)), size=N.shape)  # (days, bodies, labels)
            for j, lab in enumerate(labels):
                (N * p[:, :, j]).to_csv(root / "derived" / f"{label_column(axis, lab)}.csv")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--days", type=int, default=150)
    ap.add_argument("--bodies", type=int, default=60)
    ap.add_argument("--pool", type=int, default=80)
    ap.add_argument("--plant", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    make_synthetic(Path(args.root), C.load_config(), args.days, args.bodies, args.pool, args.plant, args.seed)
    print(f"synthetic data written to {args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
