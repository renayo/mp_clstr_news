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


def has_raw(root: Path, cfg: dict[str, Any], date: dt.date) -> bool:
    """True when at least one verbatim response file for the day is present in this checkout."""
    d = date.isoformat()
    cands = [root / "raw" / "situations" / f"{d}_{s}.jsonl" for s in cfg["api"]["layer_a"]["sorts"]]
    cands += [root / "raw" / "timelines" / f"{d}.jsonl", root / "raw" / "search" / f"{d}.jsonl"]
    return any(c.exists() and c.stat().st_size > 0 for c in cands)


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
TABLE_KEYS = ("N", "A", "S", "N_sit", "E", "E_plus")


def _existing_table(root: Path, key: str, names: list[str]) -> pd.DataFrame | None:
    p = root / "derived" / f"{key}.csv"
    if not p.exists() or p.stat().st_size == 0:
        return None
    try:
        df = pd.read_csv(p, index_col="date")
    except Exception:
        return None
    return df.reindex(columns=names).fillna(0.0)


def derive(root: Path, cfg: dict[str, Any], names: list[str], matcher: NameMatcher | None = None) -> dict[str, pd.DataFrame]:
    """Build the outcome tables. Incremental: days whose raw files are present in this checkout are
    recomputed from them; days whose raw files are elsewhere (the archive) keep their previously
    derived rows, so a fresh checkout that holds only today's responses does not zero the past."""
    matcher = matcher or NameMatcher(names)
    dates = manifest_dates(root)
    if not dates:
        raise SystemExit("no manifests found; run the collector first")
    idx = {n: i for i, n in enumerate(names)}
    T = len(dates)
    tables = {k: np.zeros((T, len(names))) for k in TABLE_KEYS}
    existing = {k: _existing_table(root, k, names) for k in TABLE_KEYS}
    raw_present = {d: has_raw(root, cfg, d) for d, _ in dates}
    carried = 0
    for ti, (date, _) in enumerate(dates):
        if raw_present[date]:
            continue
        for k in TABLE_KEYS:
            ex = existing[k]
            if ex is not None and date.isoformat() in ex.index:
                tables[k][ti] = ex.loc[date.isoformat()].to_numpy(dtype=float)
        carried += 1
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
                              "truncated": len(q.get("layer_c", {}).get("truncated", []) or []),
                              "raw_in_checkout": raw_present[date]})
        if not raw_present[date]:
            continue
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

    # Layer C: assign confirmed search results to days by published_at (only from raw files present;
    # a search made on day d can credit days d-4..d, which are recomputed here when their rows are fresh)
    seen_e: set[tuple[dt.date, str, str]] = set()
    fresh = {d for d, _ in dates if raw_present[d]}
    for date, _ in dates:
        if date not in fresh:
            continue
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
                if d not in fresh:
                    # that day's row was carried from the previous derivation; credits from today's searches
                    # to earlier days are left to the full re-derivation from the archive, which has every
                    # timeline needed to tell E from E_plus exactly
                    continue
                tables["E"][date_row[d], idx[name]] += 1
                if cid not in b_ids.get((d, name), set()):
                    tables["E_plus"][date_row[d], idx[name]] += 1

    dstr = [d.isoformat() for d, _ in dates]
    frames = {k: pd.DataFrame(v, index=pd.Index(dstr, name="date"), columns=names) for k, v in tables.items()}
    frames["complete"] = pd.DataFrame(complete_rows).set_index("date")
    mc_cols = ["date", "cluster_id", "situation_id", "published_at", "significance_score", "sources", "category",
               "countries", "names", "url"]
    new_mc = pd.DataFrame(matched_rows, columns=mc_cols)
    carried_dates = {d.isoformat() for d, _ in dates if not raw_present[d]}
    old_mc_path = root / "derived" / "matched_clusters.csv"
    if carried_dates and old_mc_path.exists() and old_mc_path.stat().st_size > 0:
        try:
            old_mc = pd.read_csv(old_mc_path)
            old_mc = old_mc[old_mc["date"].astype(str).isin(carried_dates)]
            new_mc = pd.concat([old_mc, new_mc], ignore_index=True)
        except Exception:
            pass
    frames["matched_clusters"] = new_mc.sort_values(["date", "cluster_id"]).reset_index(drop=True) if len(new_mc) else new_mc
    text_cols = ["cluster_id", "date", "title", "summary"]
    new_text = pd.DataFrame(text_rows, columns=text_cols).drop_duplicates("cluster_id")
    old_text_path = root / "classified" / "clusters_text.csv"
    if carried_dates and old_text_path.exists() and old_text_path.stat().st_size > 0:
        try:
            old_text = pd.read_csv(old_text_path).fillna("")
            old_text = old_text[old_text["date"].astype(str).isin(carried_dates)]
            new_text = pd.concat([old_text, new_text], ignore_index=True).drop_duplicates("cluster_id")
        except Exception:
            pass
    frames["clusters_text"] = new_text
    frames["_carried_days"] = pd.DataFrame({"carried": [carried]})
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
    carried = int(frames["_carried_days"]["carried"].iloc[0])
    print(f"derived {len(frames['N'])} days ({carried} carried from the previous tables, raw files not in this checkout), "
          f"{int(frames['N'].to_numpy().sum())} matched cluster-name pairs, {len(frames['matched_clusters'])} matched clusters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
