"""The daily collector (PREREGISTRATION.md §4).

Run once per day at the registered pull time::

    CLSTR_API_KEY=... python -m mpclstr.collect --date 2026-09-16

Layer A  census of situations in two sort orders (≤ 81 pages each)
Layer B  cluster timelines of every census situation, in relevance order
Layer C  embedding search for the day's cohort of names (+ second pages)
then the quality log and the hash-chained manifest.

Every response is written verbatim to ``raw/`` as one JSON line carrying the
request path, parameters, status and timestamp. Nothing is interpreted here
beyond what is needed to page, to stop at the window edge, and to decide on
second search pages; all interpretation happens in ``derive.py`` from the
archive.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import config as C
from . import cohorts as CO
from .clstr_client import ClstrClient, ClstrError, RequestRecord
from .matching import NameMatcher

TIMELINE_KEYS = ("timeline", "events", "clusters", "data")
TIMELINE_CURSOR_KEYS = ("next_timeline_before", "timeline_next_before", "next_before", "next_cursor")


# ----------------------------------------------------------------- helpers
def parse_ts(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def window_for(cfg: dict[str, Any], date: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """[12:00 UTC of the previous day, 12:00 UTC of the pull day)."""
    hh, mm = (int(x) for x in cfg["study"]["pull_time_utc"].split(":"))
    end = dt.datetime(date.year, date.month, date.day, hh, mm, tzinfo=dt.timezone.utc)
    return end - dt.timedelta(days=1), end


def extract_timeline(body: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Return (clusters newest-first, cursor for the next older page or None)."""
    if not isinstance(body, dict):
        return [], None
    clusters: list[dict[str, Any]] = []
    for k in TIMELINE_KEYS:
        v = body.get(k)
        if isinstance(v, list):
            clusters = [c for c in v if isinstance(c, dict)]
            break
    cursor = None
    for k in TIMELINE_CURSOR_KEYS:
        v = body.get(k)
        if isinstance(v, str) and v:
            cursor = v
            break
    if cursor is None and clusters and clusters[-1].get("id"):
        cursor = None  # no explicit cursor: the caller may fall back to the oldest id
    return clusters, cursor


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class RawWriter:
    """Append verbatim response records to one JSONL file per (layer, date[, sort])."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")
        self.n = 0

    def write(self, rec: RequestRecord, layer: str, date: str) -> None:
        self._fh.write(json.dumps(rec.as_raw_line(layer, date), ensure_ascii=False) + "\n")
        self.n += 1

    def close(self) -> None:
        self._fh.close()


@dataclass
class Budget:
    requests_per_day: int
    searches_per_day: int
    layer_b: int
    reserve: int
    spent_b: int = 0
    spent_searches: int = 0

    def can_request(self, client_attempts: int) -> bool:
        return client_attempts < self.requests_per_day - self.reserve

    def can_timeline(self, client_attempts: int) -> bool:
        return self.spent_b < self.layer_b and self.can_request(client_attempts)

    def can_search(self, client_attempts: int) -> bool:
        return self.spent_searches < self.searches_per_day and self.can_request(client_attempts)


@dataclass
class DayResult:
    date: str
    census: list[dict[str, Any]] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)
    files: list[Path] = field(default_factory=list)
    complete: bool = False
    manifest_path: Path | None = None


# ------------------------------------------------------------------ layers
def layer_a(client, cfg, date: dt.date, root: Path, res: DayResult) -> None:
    la = cfg["api"]["layer_a"]
    d = date.isoformat()
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    q: dict[str, Any] = {"pages": {}, "situations": {}, "ok": {}}
    for sort in la["sorts"]:
        w = RawWriter(root / "raw" / "situations" / f"{d}_{sort}.jsonl")
        cursor, pages, ok = None, 0, False
        try:
            while pages < la["max_pages"]:
                rec = client.list_situations(limit=la["limit"], days=la["days"], sort=sort,
                                             category=la["category"], country=la["country"], cursor=cursor)
                w.write(rec, "A", d)
                pages += 1
                data = rec.body.get("data", []) if isinstance(rec.body, dict) else []
                for s in data:
                    sid = s.get("id")
                    if sid and sid not in by_id:
                        by_id[sid] = s
                        order.append(sid)
                cursor = rec.body.get("next_cursor") if isinstance(rec.body, dict) else None
                if not cursor or not data:
                    ok = True
                    break
            else:
                ok = True  # hit the documented ceiling: still a complete pull by protocol
        except ClstrError as exc:
            q.setdefault("errors", []).append(f"A/{sort}: {exc}")
        finally:
            w.close()
            res.files.append(w.path)
        q["pages"][sort] = pages
        q["ok"][sort] = ok
        q["situations"][sort] = len(by_id)
    res.census = [by_id[s] for s in order]
    q["census_size"] = len(res.census)
    res.quality["layer_a"] = q


def layer_b(client, cfg, date: dt.date, root: Path, res: DayResult, budget: Budget) -> None:
    lb = cfg["api"]["layer_b"]
    d = date.isoformat()
    wstart, wend = window_for(cfg, date)
    w = RawWriter(root / "raw" / "timelines" / f"{d}.jsonl")
    fetched, clusters_in_window, pages_total = 0, 0, 0
    errors: list[str] = []
    try:
        for sit in res.census:
            if not budget.can_timeline(client.n_attempts):
                break
            sid = sit["id"]
            before, pages, done = None, 0, False
            while pages < lb["max_pages_per_situation"] and budget.can_timeline(client.n_attempts):
                try:
                    rec = client.situation(sid, timeline_limit=lb["timeline_limit"], timeline_before=before)
                except ClstrError as exc:
                    errors.append(f"B/{sid}: {exc}")
                    break
                w.write(rec, "B", d)
                budget.spent_b += 1
                pages += 1
                pages_total += 1
                clusters, cursor = extract_timeline(rec.body)
                stamps = [parse_ts(c.get("published_at")) for c in clusters]
                stamps = [s for s in stamps if s]
                clusters_in_window += sum(1 for s in stamps if wstart <= s < wend)
                oldest = min(stamps) if stamps else None
                if not clusters or oldest is None or oldest < wstart:
                    done = True
                    break
                before = cursor or clusters[-1].get("id")
                if not before:
                    done = True
                    break
            if pages:
                fetched += 1
    finally:
        w.close()
        res.files.append(w.path)
    n = len(res.census)
    res.quality["layer_b"] = {"situations_fetched": fetched, "census_size": n,
                              "coverage": (fetched / n) if n else 1.0, "pages": pages_total,
                              "clusters_in_window": clusters_in_window, "errors": errors}


def layer_c(client, cfg, date: dt.date, root: Path, res: DayResult, budget: Budget,
            cohort_names: Iterable[str], matcher: NameMatcher) -> None:
    lc = cfg["api"]["layer_c"]
    d = date.isoformat()
    w = RawWriter(root / "raw" / "search" / f"{d}.jsonl")
    names = list(cohort_names)
    truncated: list[str] = []
    second_pages = 0
    errors: list[str] = []
    searched = 0
    pending_second: list[tuple[str, str]] = []
    try:
        for name in names:
            if not budget.can_search(client.n_attempts):
                break
            try:
                rec = client.search(name, days=lc["days"], limit=lc["limit"])
            except ClstrError as exc:
                errors.append(f"C/{name}: {exc}")
                continue
            budget.spent_searches += 1
            searched += 1
            w.write(rec, "C", d)
            data = rec.body.get("data", []) if isinstance(rec.body, dict) else []
            confirmed = sum(1 for c in data if name in matcher.match_fields(c.get("title"), c.get("summary")))
            cursor = rec.body.get("next_cursor") if isinstance(rec.body, dict) else None
            if confirmed >= lc["second_page_threshold"] and cursor:
                pending_second.append((name, cursor))
        # second pages in cohort order, within the spare allowance
        for name, cursor in pending_second:
            if second_pages >= lc["spare_searches"] or not budget.can_search(client.n_attempts):
                truncated.append(name)
                continue
            try:
                rec = client.search(name, days=lc["days"], limit=lc["limit"], cursor=cursor)
            except ClstrError as exc:
                errors.append(f"C2/{name}: {exc}")
                truncated.append(name)
                continue
            budget.spent_searches += 1
            second_pages += 1
            w.write(rec, "C", d)
            data = rec.body.get("data", []) if isinstance(rec.body, dict) else []
            confirmed = sum(1 for c in data if name in matcher.match_fields(c.get("title"), c.get("summary")))
            if confirmed >= lc["second_page_threshold"]:
                truncated.append(name)
    finally:
        w.close()
        res.files.append(w.path)
    res.quality["layer_c"] = {"cohort_size": len(names), "searched": searched, "second_pages": second_pages,
                              "truncated": truncated, "errors": errors}


# ------------------------------------------------------------- manifest
def previous_manifest(root: Path, date: dt.date) -> tuple[str | None, str | None]:
    mdir = root / "manifests"
    if not mdir.exists():
        return None, None
    cands = sorted(p for p in mdir.glob("*.json") if p.stem < date.isoformat())
    if not cands:
        return None, None
    return cands[-1].name, sha256_file(cands[-1])


def write_manifest(root: Path, date: dt.date, res: DayResult, client) -> Path:
    prev_name, prev_hash = previous_manifest(root, date)
    files = {str(p.relative_to(root)): sha256_file(p) for p in res.files if p.exists()}
    res.quality["requests"] = {"attempts": getattr(client, "n_attempts", None),
                               "searches": getattr(client, "n_searches", None)}
    manifest = {
        "date": date.isoformat(),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "registration_version": C.load_config()["study"]["registration_version"],
        "complete": res.complete,
        "files": files,
        "prev_manifest": prev_name,
        "prev_manifest_sha256": prev_hash,
        "quality": res.quality,
    }
    mdir = root / "manifests"
    mdir.mkdir(parents=True, exist_ok=True)
    out = mdir / f"{date.isoformat()}.json"
    out.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    res.manifest_path = out
    return out


def completeness(cfg: dict[str, Any], res: DayResult) -> bool:
    qa = res.quality.get("layer_a", {})
    qb = res.quality.get("layer_b", {})
    a_ok = all(qa.get("ok", {}).get(s, False) for s in cfg["api"]["layer_a"]["sorts"])
    b_ok = qb.get("coverage", 0.0) >= cfg["completeness"]["timeline_coverage_min"]
    return bool(a_ok and b_ok)


# ---------------------------------------------------------------- driver
def run_day(client, cfg: dict[str, Any], date: dt.date, root: Path, matcher: NameMatcher,
            cohort_df=None) -> DayResult:
    res = DayResult(date=date.isoformat())
    b = cfg["api"]["budget"]
    budget = Budget(b["requests_per_day"], b["searches_per_day"], cfg["api"]["layer_b"]["budget"],
                    cfg["api"]["reserve"])
    layer_a(client, cfg, date, root, res)
    layer_b(client, cfg, date, root, res, budget)
    cohort_df = cohort_df if cohort_df is not None else CO.load_or_build(cfg, root)
    k = CO.cohort_for_date(cfg, date)
    names = cohort_df.loc[cohort_df["cohort"] == k, "name"].tolist()
    res.quality["cohort"] = k
    layer_c(client, cfg, date, root, res, budget, names, matcher)
    res.complete = completeness(cfg, res)
    write_manifest(root, date, res, client)
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Daily CLSTR collector for mp_clstr_news")
    ap.add_argument("--date", default=dt.datetime.now(dt.timezone.utc).date().isoformat(),
                    help="pull date (UTC), default today")
    ap.add_argument("--root", default=str(C.ROOT), help="repository root (raw/, manifests/ live here)")
    ap.add_argument("--mock", action="store_true", help="use the synthetic API (no network, no key)")
    args = ap.parse_args(argv)

    cfg = C.load_config()
    root = Path(args.root)
    date = dt.date.fromisoformat(args.date)
    names = C.verified_names(root)
    matcher = NameMatcher(names)
    if args.mock:
        from .mock_api import MockClstrClient
        _, wend = window_for(cfg, date)
        client = MockClstrClient(names, pull_time=wend, seed=int(date.strftime("%Y%m%d")))
    else:
        key = os.environ.get("CLSTR_API_KEY", "")
        if not key:
            print("CLSTR_API_KEY is not set", file=sys.stderr)
            return 2
        client = ClstrClient(key, base_url=cfg["api"]["base_url"],
                             requests_per_minute=cfg["api"]["budget"]["requests_per_minute"],
                             retries=cfg["api"]["retries"])
    res = run_day(client, cfg, date, root, matcher)
    print(json.dumps({"date": res.date, "complete": res.complete, "quality": res.quality}, indent=1))
    return 0 if res.complete else 1


if __name__ == "__main__":
    sys.exit(main())
