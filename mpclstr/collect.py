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
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import config as C
from . import cohorts as CO
from .clstr_client import ClstrClient, ClstrError, DailyCapExceeded, RequestRecord
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
        self._lock = threading.Lock()
        self.n = 0

    def write(self, rec: RequestRecord, layer: str, date: str) -> None:
        line = json.dumps(rec.as_raw_line(layer, date), ensure_ascii=False) + "\n"
        with self._lock:
            self._fh.write(line)
            self.n += 1

    def close(self) -> None:
        self._fh.close()


@dataclass
class Budget:
    """Daily request budget, the time budget, and the stop flag shared by all layers."""
    requests_per_day: int
    searches_per_day: int
    layer_b: int
    reserve: int
    deadline: float = float("inf")          # monotonic clock value after which no new request starts
    spent_b: int = 0
    spent_searches: int = 0
    stop_reason: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def stop(self, reason: str) -> None:
        with self._lock:
            if self.stop_reason is None:
                self.stop_reason = reason

    def time_left(self) -> bool:
        if time.monotonic() >= self.deadline:
            self.stop("time budget exhausted")
        return self.stop_reason is None

    def can_request(self, client_attempts: int) -> bool:
        return self.time_left() and client_attempts < self.requests_per_day - self.reserve

    def can_timeline(self, client_attempts: int) -> bool:
        return self.spent_b < self.layer_b and self.can_request(client_attempts)

    def can_search(self, client_attempts: int) -> bool:
        return self.spent_searches < self.searches_per_day and self.can_request(client_attempts)

    def spend_b(self) -> None:
        with self._lock:
            self.spent_b += 1


class Progress:
    """A line to the log every ``every`` requests: which layer, how far, how fast, how many 429s."""

    def __init__(self, client, every: int = 100):
        self.client, self.every, self.t0, self._last = client, every, time.monotonic(), 0

    def tick(self, layer: str, detail: str = "") -> None:
        n = getattr(self.client, "n_attempts", 0)
        if n - self._last >= self.every:
            self._last = n
            el = time.monotonic() - self.t0
            print(f"  [{layer}] {n} requests in {el / 60:.1f} min ({n / max(el, 1) * 60:.1f}/min), "
                  f"429s {getattr(self.client, 'n_rate_limited', 0)}, backoff {getattr(self.client, 'slept_s', 0.0):.0f}s {detail}",
                  flush=True)


@dataclass
class DayResult:
    date: str
    census: list[dict[str, Any]] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)
    files: list[Path] = field(default_factory=list)
    complete: bool = False
    manifest_path: Path | None = None


# ------------------------------------------------------------------ layers
def layer_a(client, cfg, date: dt.date, root: Path, res: DayResult, budget: Budget | None = None,
            progress: Progress | None = None) -> None:
    la = cfg["api"]["layer_a"]
    d = date.isoformat()
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    q: dict[str, Any] = {"pages": {}, "situations": {}, "ok": {}}
    for sort in la["sorts"]:
        w = RawWriter(root / "raw" / "situations" / f"{d}_{sort}.jsonl")
        cursor, pages, ok = None, 0, False
        try:
            while pages < la["max_pages"] and (budget is None or budget.can_request(client.n_attempts)):
                rec = client.list_situations(limit=la["limit"], days=la["days"], sort=sort,
                                             category=la["category"], country=la["country"], cursor=cursor)
                w.write(rec, "A", d)
                pages += 1
                if progress:
                    progress.tick("A", f"{sort} page {pages}")
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
        except DailyCapExceeded as exc:
            q.setdefault("errors", []).append(f"A/{sort}: {exc}")
            if budget:
                budget.stop(f"daily cap: {exc}")
        except ClstrError as exc:
            q.setdefault("errors", []).append(f"A/{sort}: {exc}")
        finally:
            w.close()
            res.files.append(w.path)
        q["pages"][sort] = pages
        q["ok"][sort] = ok
        q["situations"][sort] = len(by_id)
    print(f"  [A] census: {len(order)} situations from {sum(q['pages'].values())} pages", flush=True)
    res.census = [by_id[s] for s in order]
    q["census_size"] = len(res.census)
    res.quality["layer_a"] = q


def _fetch_timeline(client, cfg, sid: str, wstart: dt.datetime, wend: dt.datetime,
                    budget: Budget) -> tuple[list[RequestRecord], int, int, str | None]:
    """All pages of one situation's timeline back to the window's start.

    Returns (records, pages, clusters_in_window, error)."""
    lb = cfg["api"]["layer_b"]
    records: list[RequestRecord] = []
    before, pages, in_window = None, 0, 0
    while pages < lb["max_pages_per_situation"] and budget.can_timeline(client.n_attempts):
        try:
            rec = client.situation(sid, timeline_limit=lb["timeline_limit"], timeline_before=before)
        except DailyCapExceeded as exc:
            budget.stop(f"daily cap: {exc}")
            return records, pages, in_window, f"B/{sid}: {exc}"
        except ClstrError as exc:
            return records, pages, in_window, f"B/{sid}: {exc}"
        budget.spend_b()
        records.append(rec)
        pages += 1
        clusters, cursor = extract_timeline(rec.body)
        stamps = [s for s in (parse_ts(c.get("published_at")) for c in clusters) if s]
        in_window += sum(1 for s in stamps if wstart <= s < wend)
        oldest = min(stamps) if stamps else None
        if not clusters or oldest is None or oldest < wstart:
            break
        before = cursor or clusters[-1].get("id")
        if not before:
            break
    return records, pages, in_window, None


def layer_b(client, cfg, date: dt.date, root: Path, res: DayResult, budget: Budget,
            progress: Progress | None = None) -> None:
    """Cluster timelines of every census situation, fetched by a small pool of workers.

    The pool only hides latency: the client's global pacing keeps the request rate within the
    per-minute allowance no matter how many workers are waiting on replies."""
    d = date.isoformat()
    wstart, wend = window_for(cfg, date)
    w = RawWriter(root / "raw" / "timelines" / f"{d}.jsonl")
    fetched, clusters_in_window, pages_total = 0, 0, 0
    errors: list[str] = []
    workers = max(1, int(cfg["api"].get("parallel_timelines", 1)))
    todo = list(res.census)
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = set()
            it = iter(todo)
            # keep the pool topped up so there is always a request ready when the pacer allows one
            while pending or budget.can_timeline(client.n_attempts):
                while len(pending) < workers * 2 and budget.can_timeline(client.n_attempts):
                    sit = next(it, None)
                    if sit is None:
                        break
                    pending.add(pool.submit(_fetch_timeline, client, cfg, sit["id"], wstart, wend, budget))
                if not pending:
                    break
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for fut in done:
                    records, pages, in_window, err = fut.result()
                    for rec in records:
                        w.write(rec, "B", d)
                    pages_total += pages
                    clusters_in_window += in_window
                    if pages:
                        fetched += 1
                    if err:
                        errors.append(err)
                    if progress:
                        progress.tick("B", f"{fetched}/{len(todo)} situations")
    finally:
        w.close()
        res.files.append(w.path)
    n = len(res.census)
    res.quality["layer_b"] = {"situations_fetched": fetched, "census_size": n,
                              "coverage": (fetched / n) if n else 1.0, "pages": pages_total,
                              "clusters_in_window": clusters_in_window, "workers": workers,
                              "errors": errors[:50], "n_errors": len(errors)}
    print(f"  [B] timelines: {fetched}/{n} situations, {pages_total} pages, {clusters_in_window} clusters in window",
          flush=True)


def layer_c(client, cfg, date: dt.date, root: Path, res: DayResult, budget: Budget,
            cohort_names: Iterable[str], matcher: NameMatcher, progress: Progress | None = None) -> None:
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
            except DailyCapExceeded as exc:
                errors.append(f"C/{name}: {exc}")
                budget.stop(f"daily cap: {exc}")
                break
            except ClstrError as exc:
                errors.append(f"C/{name}: {exc}")
                continue
            budget.spent_searches += 1
            searched += 1
            w.write(rec, "C", d)
            if progress:
                progress.tick("C", f"{searched} names searched")
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
                              "truncated": truncated, "errors": errors[:50], "n_errors": len(errors)}
    print(f"  [C] search: {searched}/{len(names)} names, {second_pages} second pages, {len(truncated)} truncated",
          flush=True)


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
                               "searches": getattr(client, "n_searches", None),
                               "rate_limited_429": getattr(client, "n_rate_limited", None),
                               "backoff_seconds": round(float(getattr(client, "slept_s", 0.0)), 1)}
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
    t0 = time.monotonic()
    res = DayResult(date=date.isoformat())
    b = cfg["api"]["budget"]
    minutes = float(cfg["api"].get("time_budget_minutes", 0) or 0)
    budget = Budget(b["requests_per_day"], b["searches_per_day"], cfg["api"]["layer_b"]["budget"],
                    cfg["api"]["reserve"], deadline=(t0 + minutes * 60.0) if minutes > 0 else float("inf"))
    progress = Progress(client)
    print(f"collect {res.date}: budget {b['requests_per_day']} requests, {b['searches_per_day']} searches, "
          f"{minutes:.0f} min", flush=True)
    layer_a(client, cfg, date, root, res, budget, progress)
    layer_b(client, cfg, date, root, res, budget, progress)
    cohort_df = cohort_df if cohort_df is not None else CO.load_or_build(cfg, root)
    k = CO.cohort_for_date(cfg, date)
    names = cohort_df.loc[cohort_df["cohort"] == k, "name"].tolist()
    res.quality["cohort"] = k
    layer_c(client, cfg, date, root, res, budget, names, matcher, progress)
    res.quality["stop_reason"] = budget.stop_reason
    res.quality["elapsed_seconds"] = round(time.monotonic() - t0, 1)
    res.complete = completeness(cfg, res) and budget.stop_reason is None
    write_manifest(root, date, res, client)
    print(f"collect {res.date}: complete={res.complete}"
          + (f" ({budget.stop_reason})" if budget.stop_reason else "")
          + f", {getattr(client, 'n_attempts', '?')} requests in {(time.monotonic() - t0) / 60:.1f} min", flush=True)
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Daily CLSTR collector for mp_clstr_news")
    ap.add_argument("--date", default=dt.datetime.now(dt.timezone.utc).date().isoformat(),
                    help="pull date (UTC), default today")
    ap.add_argument("--root", default=str(C.ROOT), help="repository root (raw/, manifests/ live here)")
    ap.add_argument("--mock", action="store_true", help="use the synthetic API (no network, no key)")
    ap.add_argument("--force", action="store_true", help="run even if this date already has a complete manifest")
    args = ap.parse_args(argv)

    cfg = C.load_config()
    root = Path(args.root)
    date = dt.date.fromisoformat(args.date)
    existing = root / "manifests" / f"{date.isoformat()}.json"
    if existing.exists() and not args.force:
        try:
            prev = json.loads(existing.read_text(encoding="utf-8"))
        except ValueError:
            prev = {}
        if prev.get("complete"):
            print(f"{date} already has a complete manifest; the daily request allowance is per UTC day and a second "
                  f"run would exhaust it. Use --force to run anyway.")
            return 0
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
