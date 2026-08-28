"""The single confirmatory run (PREREGISTRATION.md §7).

    python -m mpclstr.analysis [--n-rep 5000] [--seed 42] [--out results]
                               [--series N|A|S|N_sit|N_union] [--node mean|true]
                               [--ephemeris data/ephemeris] [--septile-lag 51]
                               [--exclude-short] [--exclude-top 12] [--exclude-wordlist FILE]
                               [--sidereal] [--year YYYY] [--interim-label LABEL]

Reads derived/*.csv and data/ephemeris/*.csv, computes every registered
statistic on the observed data, draws the two nulls, and writes
results/summary.json plus the null draws. Robustness variants are CLI
options so that the confirmatory call is the bare command.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import config as C
from .angles import separation, sidereal
from .stats import (Kernels, binned_wave, circular_acf, first_harmonic, harmonic_amplitude, harmonic_v,
                    l2_normalize_rows, modulation_percent, monte_carlo, registered_statistics, summarise)

QUALITY_TABLES = ["N_pos", "N_neg", "N_neu", "N_space", "N_air", "N_fire", "N_water", "N_earth",
                  "N_male", "N_female", "N_na", "N_yin", "N_yang", "N_cardinal", "N_fixed", "N_mutable"]


def load_tables(root: Path, primary: str) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], pd.DataFrame]:
    dd = root / "derived"
    if primary == "N_union":
        N = pd.read_csv(dd / "N.csv", index_col="date") + pd.read_csv(dd / "E_plus.csv", index_col="date")
    else:
        N = pd.read_csv(dd / f"{primary}.csv", index_col="date")
    quality = {}
    for k in QUALITY_TABLES:
        p = dd / f"{k}.csv"
        if p.exists():
            quality[k] = pd.read_csv(p, index_col="date")
    complete = pd.read_csv(dd / "complete.csv", index_col="date")
    return N, quality, complete


def load_ephemeris(edir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    named = pd.read_csv(edir / "named.csv", index_col="date")
    unnamed = pd.read_csv(edir / "unnamed.csv", index_col="date")
    refs = pd.read_csv(edir / "references.csv", index_col="date")
    return named, unnamed, refs


def select_days(cfg: dict[str, Any], N: pd.DataFrame, complete: pd.DataFrame, named: pd.DataFrame,
                year: int | None) -> list[str]:
    start, end = cfg["study"]["window_start"], cfg["study"]["window_end"]
    days = [d for d in N.index if start <= d <= end and d in named.index]
    if "complete" in complete.columns:
        ok = set(complete.index[complete["complete"].astype(bool)])
        days = [d for d in days if d in ok]
    if year is not None:
        days = [d for d in days if d.startswith(str(year))]
    return days


def run(cfg: dict[str, Any], root: Path, args: argparse.Namespace) -> dict[str, Any]:
    t0 = time.time()
    N_df, quality, complete = load_tables(root, args.series)
    named, unnamed, refs = load_ephemeris(Path(args.ephemeris) if args.ephemeris else root / "data" / "ephemeris")
    days = select_days(cfg, N_df, complete, named, args.year)
    if len(days) < 30:
        raise SystemExit(f"only {len(days)} complete days available; refusing to run")
    names = [n for n in N_df.columns if n in named.columns and not named.loc[days, n].isna().any()]

    # exclusions (robustness options)
    excluded: dict[str, list[str]] = {}
    if args.exclude_short:
        k = cfg["robustness"]["short_name_max_chars"]
        excluded["short"] = [n for n in names if len(n) <= k]
    if args.exclude_top:
        tot = N_df.loc[days, names].sum(axis=0).sort_values(ascending=False)
        excluded["top"] = tot.index[: args.exclude_top].tolist()
    if args.exclude_wordlist:
        words = {w.strip().casefold() for w in Path(args.exclude_wordlist).read_text().splitlines() if w.strip()}
        excluded["wordlist"] = [n for n in names if n.casefold() in words]
    drop = {n for v in excluded.values() for n in v}
    names = [n for n in names if n not in drop]

    # series — (B × T) layout, time last
    N = N_df.loc[days, names].to_numpy(dtype=float).T
    Nn, norm = l2_normalize_rows(N)
    series: dict[str, np.ndarray] = {"N": Nn}
    for k, df in quality.items():
        series[k] = l2_normalize_rows(df.loc[days, names].to_numpy(dtype=float).T, norm)[0]

    # orbits — (B × T)
    L = np.ascontiguousarray(named.loc[days, names].to_numpy(dtype=float).T)
    Lu = unnamed.loc[days].to_numpy(dtype=float).T
    keep_u = ~np.isnan(Lu).any(axis=1)
    Lu = np.ascontiguousarray(Lu[keep_u])
    R = refs.loc[days]
    node_suffix = "_true" if args.node == "true" else ""
    ref_lon: dict[str, np.ndarray] = {}
    for r in cfg["reference_points"]:
        nm = r["name"]
        col = nm + node_suffix if nm in ("Rahu", "Ketu") and node_suffix else nm
        ref_lon[nm] = R[col].to_numpy(dtype=float)
    indep = C.independent_reference_names(cfg)
    all_refs = [r["name"] for r in cfg["reference_points"]]
    theta_named = {r: separation(L, ref_lon[r]) for r in all_refs}
    theta_unnamed = {r: separation(Lu, ref_lon[r]) for r in all_refs}
    sign_L = sidereal(L, cfg["signs"]["ayanamsa_lahiri_midwindow_deg"]) if args.sidereal else None
    sign_Lu = sidereal(Lu, cfg["signs"]["ayanamsa_lahiri_midwindow_deg"]) if args.sidereal else None
    kdtype = np.float32 if args.float32 else np.float64
    K_named = Kernels.build(indep, theta_named, cfg, L, sign_L, dtype=kdtype)
    K_unnamed = Kernels.build(indep, theta_unnamed, cfg, Lu, sign_Lu, dtype=kdtype, keep_theta=False)
    del theta_unnamed
    planets = {r["name"]: r for r in cfg["reference_points"] if r["kind"] == "major"}
    acf_lags = list(cfg["acf_lags"])
    if args.septile_lag != 51:
        acf_lags = [args.septile_lag if l == 51 else l for l in acf_lags]

    # observed
    obs = registered_statistics(series, K_named, cfg, planets, acf_lags)
    detail: dict[str, Any] = {"per_reference": {}}
    H = cfg["harmonics"]
    for r in all_refs:
        th = theta_named[r]
        w_unc = binned_wave(series["N"], th, centre=False)
        w = w_unc - w_unc.mean()
        fh = first_harmonic(w)
        entry = {"V_n": {str(n): harmonic_v(series["N"], th, n) for n in H},
                 "A_n": {str(n): harmonic_amplitude(series["N"], th, n)[0] for n in H},
                 "phase_n": {str(n): harmonic_amplitude(series["N"], th, n)[1] for n in H},
                 "first_harmonic_peak_deg": fh["peak_deg"], "first_harmonic_amplitude": fh["amplitude"],
                 "modulation_percent": modulation_percent(w_unc),
                 "ACF": dict(zip([str(l) for l in acf_lags], circular_acf(w, acf_lags).tolist())),
                 "independent": r in indep}
        detail["per_reference"][r] = entry

    # nulls
    def progress(i, n):
        print(f"  replicate {i}/{n}  ({time.time() - t0:.0f}s)", flush=True)
    nulls = monte_carlo(series, K_named, K_unnamed, cfg, planets, acf_lags, args.n_rep, args.seed, progress)

    tests: dict[str, Any] = {}
    for stat, val in obs.items():
        tests[stat] = {k: summarise(val, nulls[k][stat]) for k in ("compound", "unnamed")}

    def decision(stat: str, alpha: float) -> dict[str, Any]:
        if stat not in tests:
            return {"status": "not available"}
        pc, pu = tests[stat]["compound"]["p_one_sided"], tests[stat]["unnamed"]["p_one_sided"]
        return {"alpha": alpha, "p_compound": pc, "p_unnamed": pu, "supported": bool(pc < alpha and pu < alpha)}

    inf = cfg["inference"]
    hyp = {"H1": decision("D", inf["alpha_h1"]),
           "H2": {r: decision(f"D_{r}", inf["alpha_h2"]) for r in indep},
           "H3": decision("T_FPOA", inf["alpha_h3"]),
           "H4": decision("Delta_pol", inf["alpha_block2"]),
           "H5": decision("G_elem", inf["alpha_block2"]),
           "H6": decision("G_gen", inf["alpha_block2"]),
           "H7": decision("Y", inf["alpha_block2"]),
           "H8": decision("M", inf["alpha_block2"]),
           "replication_ACF2": decision("ACF2", inf["alpha_h1"])}

    summary = {
        "study": cfg["study"]["name"], "registration_version": cfg["study"]["registration_version"],
        "run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "label": args.interim_label, "variant": vars(args),
        "dataset": {"days": len(days), "date_start": days[0], "date_end": days[-1], "bodies": len(names),
                    "unnamed_pool": int(K_unnamed.n_bodies), "excluded": excluded,
                    "quality_series_available": sorted(quality.keys())},
        "observed": obs, "tests": tests, "hypotheses": hyp, "detail": detail,
        "monte_carlo": {"n_replicates": args.n_rep, "seed": args.seed}, "runtime_s": round(time.time() - t0, 1),
    }
    return summary, nulls


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Confirmatory analysis for mp_clstr_news")
    ap.add_argument("--root", default=str(C.ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--n-rep", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--series", default="N", choices=["N", "A", "S", "N_sit", "N_union"])
    ap.add_argument("--node", default="mean", choices=["mean", "true"])
    ap.add_argument("--ephemeris", default=None)
    ap.add_argument("--septile-lag", type=int, default=51)
    ap.add_argument("--exclude-short", action="store_true")
    ap.add_argument("--exclude-top", type=int, default=0)
    ap.add_argument("--exclude-wordlist", default=None)
    ap.add_argument("--sidereal", action="store_true")
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--interim-label", default="confirmatory")
    ap.add_argument("--float32", action="store_true", help="float32 kernels (halves memory; ~1e-6 relative change)")
    args = ap.parse_args(argv)
    cfg = C.load_config()
    root = Path(args.root)
    args.n_rep = args.n_rep or cfg["monte_carlo"]["n_replicates"]
    args.seed = args.seed if args.seed is not None else cfg["seeds"]["monte_carlo"]
    summary, nulls = run(cfg, root, args)
    out = Path(args.out) if args.out else root / "results"
    out.mkdir(parents=True, exist_ok=True)
    tag = args.interim_label
    (out / f"summary_{tag}.json").write_text(json.dumps(summary, indent=1, default=float), encoding="utf-8")
    np.savez_compressed(out / f"nulls_{tag}.npz", **{f"{k}__{s}": v for k, d in nulls.items() for s, v in d.items()})
    print(json.dumps(summary["hypotheses"], indent=1))
    print(f"wrote {out / f'summary_{tag}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
