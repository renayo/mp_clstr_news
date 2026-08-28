"""Raw archive -> daily outcome tables (PREREGISTRATION.md §4.6, Appendix D).

    python -m mpclstr.derive [--root PATH]

Reads every day that has a manifest, re-applies the name-matching protocol to
the verbatim responses, and writes:

    derived/N.csv, A.csv, S.csv, N_sit.csv, E.csv, E_plus.csv   (date × name)
    derived/N_<label>.csv                                      (if classified/clusters.csv exists)
    derived/complete.csv                                       (per-day completeness and quality)
    derived/matched_clusters.csv                               (metadata of every matched cluster)
    classified/clusters_text.csv                               (text of matched clusters — classifier input;
                                                                gitignored until CLSTR permits publication)

The deriver is idempotent: it rebuilds every table from the archive each time.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd

from . import config as C
from .collect import parse_ts, window_for
from .matching import NameMatcher

LABEL_SHORT = {"positive": "pos", "negative": "neg", "neutral": "neu", "not_applicable": "na"}


def label_column(axis: str, label: str) -> str:
    return "N_" + LABEL_SHORT.get(label, label)


def iter_jsonl(p: Path) -> Iterator[dict[str, Any]]:
    if not p.exists():
        return
    with open(p, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if ln:
                yield json.loads(ln)


def day_of(cfg: dict[str, Any], published: dt.datetime) -> dt.date:
    """The pull date whose window contains ``published``."""
    hh, mm = (int(x) for x in cfg["study"]["pull_time_utc"].split(":"))
    shift = dt.timedelta(hours=24) - dt.timedelta(hours=hh, minutes=mm)
    return (published + shift).date()


def manifest_dates(root: Path) -> list[tuple[dt.date, dict[str, Any]]]:
    out = []
    for p in sorted((root / "manifests").glob("*.json")):
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
            out.append((dt.date.fromisoformat(m["date"]), m))
        except (ValueError, KeyError):
            continue
    return out


# ------------------------------------------------------------------ per-day
def census_situations(root: Path, cfg: dict[str, Any], date: dt.date) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for sort in cfg["api"]["layer_a"]["sorts"]:
        for rec in iter_jsonl(root / "raw" / "situations" / f"{date.isoformat()}_{sort}.jsonl"):
            if rec.get("status") != 200:
                continue
            for s in (rec.get("body") or {}).get("data", []) or []:
                if s.get("id") and s["id"] not in by_id:
                    by_id[s["id"]] = s
    return by_id


def window_clusters(root: Path, cfg: dict[str, Any], date: dt.date) -> dict[str, dict[str, Any]]:
    """Distinct clusters published inside the day's window, from the timelines archive."""
    wstart, wend = window_for(cfg, date)
    out: dict[str, dict[str, Any]] = {}
    from .collect import extract_timeline
    for rec in iter_jsonl(root / "raw" / "timelines" / f"{date.isoformat()}.jsonl"):
        if rec.get("status") != 200:
            continue
        path = rec.get("request", {}).get("path", "")
        sid = path.split("/")[-1] if path else None
        clusters, _ = extract_timeline(rec.get("body"))
        for c in clusters:
            cid = c.get("id")
            ts = parse_ts(c.get("published_at"))
            if not cid or ts is None or not (wstart <= ts < wend):
                continue
            if cid not in out:
                cc = dict(c)
                cc.setdefault("situation_id", sid)
                out[cid] = cc
    return out


# ---------------------------------------------------------------- driver
def derive(root: Path, cfg: dict[str, Any], names: list[str], matcher: NameMatcher | None = None) -> dict[str, pd.DataFrame]:
    matcher = matcher or NameMatcher(names)
    dates = manifest_dates(root)
    if not dates:
        raise SystemExit("no manifests found; run the collector first")
    idx = {n: i for i, n in enumerate(names)}
    T = len(dates)
    tables = {k: np.zeros((T, len(names))) for k in ("N", "A", "S", "N_sit", "E", "E_plus")}
    matched_rows: list[dict[str, Any]] = []
    text_rows: list[dict[str, Any]] = []
    complete_rows: list[dict[str, Any]] = []
    # cluster ids matched per (date, name) from Layer B — needed for E_plus
    b_ids: dict[tuple[dt.date, str], set[str]] = defaultdict(set)
    date_row = {d: i for i, (d, _) in enumerate(dates)}

    for ti, (date, man) in enumerate(dates):
        q = man.get("quality", {})
        complete_rows.append({"date": date.isoformat(), "complete": bool(man.get("complete")),
                              "census_size": q.get("layer_a", {}).get("census_size"),
                              "timeline_coverage": q.get("layer_b", {}).get("coverage"),
                              "clusters_in_window": q.get("layer_b", {}).get("clusters_in_window"),
                              "searched": q.get("layer_c", {}).get("searched"),
                              "truncated": len(q.get("layer_c", {}).get("truncated", []) or [])})
        # situation-level
        for s in census_situations(root, cfg, date).values():
            for n in matcher.match_fields(s.get("title"), s.get("summary_preview"), s.get("latest_cluster_title")):
                tables["N_sit"][ti, idx[n]] += 1
        # cluster-level (primary)
        for cid, c in window_clusters(root, cfg, date).items():
            hits = matcher.match_fields(c.get("title"), c.get("summary"))
            if not hits:
                continue
            sig = float(c.get("significance_score") or 0)
            src = float(c.get("sources") or 0)
            for n in hits:
                tables["N"][ti, idx[n]] += 1
                tables["A"][ti, idx[n]] += src
                tables["S"][ti, idx[n]] += sig
                b_ids[(date, n)].add(cid)
            matched_rows.append({"date": date.isoformat(), "cluster_id": cid, "situation_id": c.get("situation_id"),
                                 "published_at": c.get("published_at"), "significance_score": c.get("significance_score"),
                                 "sources": c.get("sources"), "category": c.get("category"),
                                 "countries": ";".join(c.get("countries") or []), "names": ";".join(hits),
                                 "url": c.get("url")})
            text_rows.append({"cluster_id": cid, "date": date.isoformat(), "title": c.get("title") or "",
                              "summary": c.get("summary") or ""})

    # Layer C: assign confirmed search results to days by published_at
    seen_e: set[tuple[dt.date, str, str]] = set()
    for date, _ in dates:
        for rec in iter_jsonl(root / "raw" / "search" / f"{date.isoformat()}.jsonl"):
            if rec.get("status") != 200:
                continue
            name = rec.get("request", {}).get("params", {}).get("q")
            if name not in idx:
                continue
            for c in (rec.get("body") or {}).get("data", []) or []:
                ts = parse_ts(c.get("published_at"))
                cid = c.get("id")
                if ts is None or not cid:
                    continue
                if name not in matcher.match_fields(c.get("title"), c.get("summary")):
                    continue
                d = day_of(cfg, ts)
                if d not in date_row or (d, name, cid) in seen_e:
                    continue
                seen_e.add((d, name, cid))
                tables["E"][date_row[d], idx[name]] += 1
                if cid not in b_ids.get((d, name), set()):
                    tables["E_plus"][date_row[d], idx[name]] += 1

    dstr = [d.isoformat() for d, _ in dates]
    frames = {k: pd.DataFrame(v, index=pd.Index(dstr, name="date"), columns=names) for k, v in tables.items()}
    frames["complete"] = pd.DataFrame(complete_rows).set_index("date")
    frames["matched_clusters"] = pd.DataFrame(matched_rows)
    frames["clusters_text"] = pd.DataFrame(text_rows).drop_duplicates("cluster_id") if text_rows else pd.DataFrame(
        columns=["cluster_id", "date", "title", "summary"])
    return frames


def quality_tables(frames: dict[str, pd.DataFrame], classified: pd.DataFrame, cfg: dict[str, Any],
                   names: list[str]) -> dict[str, pd.DataFrame]:
    """Quality-weighted presence N^(q): sum of label probabilities over matched clusters."""
    mc = frames["matched_clusters"]
    if mc.empty:
        return {}
    axes = cfg["classification"]["axes"]
    probs = classified.set_index("cluster_id")
    out: dict[str, pd.DataFrame] = {}
    dates = list(frames["N"].index)
    di = {d: i for i, d in enumerate(dates)}
    ni = {n: i for i, n in enumerate(names)}
    for axis, labels in axes.items():
        for label in labels:
            col = f"p_{axis}_{label}"
            if col not in probs.columns:
                continue
            arr = np.zeros((len(dates), len(names)))
            p = mc["cluster_id"].map(probs[col]).fillna(0.0).to_numpy()
            for row, pv in zip(mc.itertuples(index=False), p):
                if row.date not in di:
                    continue
                for n in str(row.names).split(";"):
                    if n in ni:
                        arr[di[row.date], ni[n]] += pv
            out[label_column(axis, label)] = pd.DataFrame(arr, index=frames["N"].index, columns=names)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Derive daily outcome tables from the raw archive")
    ap.add_argument("--root", default=str(C.ROOT))
    args = ap.parse_args(argv)
    root = Path(args.root)
    cfg = C.load_config()
    names = C.verified_names(root)
    frames = derive(root, cfg, names)
    dd = root / "derived"
    dd.mkdir(exist_ok=True)
    for k in ("N", "A", "S", "N_sit", "E", "E_plus"):
        frames[k].to_csv(dd / f"{k}.csv")
    frames["complete"].to_csv(dd / "complete.csv")
    frames["matched_clusters"].to_csv(dd / "matched_clusters.csv", index=False)
    cd = root / "classified"
    cd.mkdir(exist_ok=True)
    frames["clusters_text"].to_csv(cd / "clusters_text.csv", index=False)
    cls = cd / "clusters.csv"
    if cls.exists():
        for k, df in quality_tables(frames, pd.read_csv(cls), cfg, names).items():
            df.to_csv(dd / f"{k}.csv")
    print(f"derived {len(frames['N'])} days, {int(frames['N'].to_numpy().sum())} matched cluster-name pairs, "
          f"{len(frames['matched_clusters'])} matched clusters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
