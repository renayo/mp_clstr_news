"""The daily collector (PREREGISTRATION.md §4).

Run once per day at the registered pull time::

    CLSTR_API_KEY=... python -m mpclstr.collect --date 2026-09-16

Layer A  census of situations in two sort orders (≤ 81 pages each)
Layer B  cluster timelines of every census situation, in relevance order
Layer C  embedding search: back-fill of missed names, today's cohort, second pages
Pass 2   one more attempt at everything that gave up on a 5xx (§4.6a)
then the quality log and the hash-chained manifest.

Every successful response is written verbatim to ``raw/`` as one JSON line
carrying the request path, parameters, status, headers and timestamp; every
failed attempt is written the same way to ``raw/errors/`` (§4.7). Nothing is
interpreted here beyond what is needed to page, to stop at the window edge,
to decide on second search pages, and to check the collection invariant of
§4.3a; all interpretation happens in ``derive.py`` from the archive.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import json
import math
import os
import signal
import sys
import threading
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from . import __version__
from . import config as C
from . import cohorts as CO
from .clstr_client import (ClstrClient, ClstrError, DailyCapExceeded, Gone, MalformedRequest, NotFound,
                           RateLimited, RequestRecord, Unauthorized, Unavailable)
from .matching import NameMatcher

# The documented v1 shape of GET /situations/{id}, confirmed against a live response on 2026-08-30:
#
#     {"data": {<situation fields>, "timeline": [<cluster>, ...],            # newest first
#               "timeline_cursor": {"has_more": bool, "next_before": "<cluster id>",
#                                   "remaining_count": n, "total_count": n}, "day_span": n}}
#
# and each cluster carries "published_at" as ISO 8601 with a Z. The extractor reads that shape first
# and falls back to a bounded search of the same keys one or two levels down, so a re-nesting by the
# provider degrades to a logged invariant failure (§4.3a) rather than a silent zero. The shape is pinned
# by tests/test_collect_derive.py::test_extract_timeline_real_shape.
TIMELINE_KEYS = ("timeline", "events", "clusters", "entries", "items")
CONTAINER_KEYS = ("data", "situation", "timeline", "result")
TIMELINE_CURSOR_KEYS = ("next_before", "next_timeline_before", "timeline_next_before", "next_cursor")
CURSOR_CONTAINER_KEYS = ("timeline_cursor", "data", "situation", "timeline", "pagination", "meta", "cursor")
CLUSTER_TIME_KEYS = ("published_at", "published", "first_published_at", "publishedAt", "created_at", "date", "time")

# Why a day is not complete (§4.7). The first applicable reason, in this order, is recorded;
# aborts outrank budget stops, budget stops outrank the layer symptoms they cause.
STOP_REASONS = ("malformed_request", "unauthorized", "operator_abort",
                "request_budget_exhausted", "time_budget_exhausted",
                "layer_a_http_error", "layer_a_cursor_unexhausted",
                "coverage_below_threshold", "zero_clusters_in_window")


# ----------------------------------------------------------------- helpers
def parse_ts(s: Any) -> dt.datetime | None:
    """A timestamp as UTC: ISO 8601 (with Z, an offset, or fractional seconds), an epoch number,
    or an RFC 2822 date. None when absent or unreadable."""
    if s is None or s == "":
        return None
    if isinstance(s, bool):
        return None
    if isinstance(s, (int, float)):
        try:
            secs = float(s)
            if secs > 1e11:            # milliseconds
                secs /= 1000.0
            return dt.datetime.fromtimestamp(secs, tz=dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(s, str):
        return None
    txt = s.strip()
    try:
        t = dt.datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except ValueError:
        try:
            t = email.utils.parsedate_to_datetime(txt)
        except (TypeError, ValueError, IndexError):
            return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)   # naive stamps are taken as UTC, never as local time
    return t.astimezone(dt.timezone.utc)


def cluster_time(c: dict[str, Any]) -> dt.datetime | None:
    """The publication time of a cluster, from the first readable of the known timestamp keys."""
    for k in CLUSTER_TIME_KEYS:
        if k in c:
            t = parse_ts(c.get(k))
            if t is not None:
                return t
    return None


def window_for(cfg: dict[str, Any], date: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """[12:00 UTC of the previous day, 12:00 UTC of the pull day)."""
    hh, mm = (int(x) for x in cfg["study"]["pull_time_utc"].split(":"))
    end = dt.datetime(date.year, date.month, date.day, hh, mm, tzinfo=dt.timezone.utc)
    return end - dt.timedelta(days=1), end


def _find_list(d: dict[str, Any], depth: int = 0) -> list[dict[str, Any]] | None:
    for k in TIMELINE_KEYS:
        v = d.get(k)
        if isinstance(v, list):
            return [c for c in v if isinstance(c, dict)]
    if depth < 2:
        for k in CONTAINER_KEYS:
            v = d.get(k)
            if isinstance(v, dict):
                found = _find_list(v, depth + 1)
                if found is not None:
                    return found
        v = d.get("data")
        if isinstance(v, list) and all(isinstance(c, dict) for c in v):
            return list(v)
    return None


def _find_cursor(d: dict[str, Any], depth: int = 0) -> str | None:
    """The id to pass as ``timeline_before`` for the next older page, or None when the provider says
    there is no more (``has_more: false``) or no cursor is present."""
    tc = d.get("timeline_cursor")
    if isinstance(tc, dict) and tc.get("has_more") is False:
        return None
    for k in TIMELINE_CURSOR_KEYS:
        v = d.get(k)
        if isinstance(v, str) and v:
            return v
    if depth < 2:
        for k in CURSOR_CONTAINER_KEYS:
            v = d.get(k)
            if isinstance(v, dict):
                c = _find_cursor(v, depth + 1)
                if c:
                    return c
    return None


def extract_timeline(body: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Return (clusters as returned — newest first, cursor for the next older page or None)."""
    if not isinstance(body, dict):
        return [], None
    data = body.get("data")
    sit = data if isinstance(data, dict) else body
    tl = sit.get("timeline")
    if isinstance(tl, list):                       # the documented shape
        clusters = [c for c in tl if isinstance(c, dict)]
    else:                                          # bounded fallback over the known keys
        clusters = _find_list(body) or []
    return clusters, _find_cursor(body)


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

    def write(self, rec: RequestRecord, layer: str, date: str, **extra: Any) -> None:
        line = json.dumps(rec.as_raw_line(layer, date, **extra), ensure_ascii=False) + "\n"
        with self._lock:
            self._fh.write(line)
            self._fh.flush()
            self.n += 1

    def close(self) -> None:
        self._fh.close()


def _quota_int(client, key: str) -> int | None:
    """A quota header the client last saw (``remaining-day``, ``remaining-search``), as an int."""
    try:
        v = (getattr(client, "quota", None) or {}).get(key)
        return int(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


@dataclass
class Budget:
    """Daily request budget, the search ledger, the time budget, and the stop flag shared by all layers.

    The provider meters distinct requests per UTC day: a retry of the same request is not charged
    again (observed 2026-08-30, §4.1). The request ledger therefore paces against the provider's own
    ``X-RateLimit-Remaining-Day`` when the client has seen it, and against attempts otherwise; the
    search ledger charges one slot per distinct query, successful or not, and never charges a retry."""
    requests_per_day: int
    searches_per_day: int
    layer_b: int
    reserve: int
    deadline: float = float("inf")          # monotonic clock value after which no new request starts
    spent_b: int = 0
    spent_searches: int = 0                 # distinct search queries charged today (the metered unit, §4.1)
    inflight_searches: int = 0
    stop_reason: str | None = None
    _charged: set = field(default_factory=set, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def stop(self, reason: str) -> None:
        with self._lock:
            if self.stop_reason is None:
                self.stop_reason = reason

    def time_left(self) -> bool:
        if time.monotonic() >= self.deadline:
            self.stop("time_budget_exhausted")
        return self.stop_reason is None

    def can_request(self, client_attempts: int, remaining_day: int | None = None) -> bool:
        if not self.time_left():
            return False
        if remaining_day is not None:
            exhausted = remaining_day <= self.reserve
        else:
            exhausted = client_attempts >= self.requests_per_day - self.reserve
        if exhausted:
            self.stop("request_budget_exhausted")
            return False
        return True

    def can_timeline(self, client_attempts: int, remaining_day: int | None = None) -> bool:
        return self.spent_b < self.layer_b and self.can_request(client_attempts, remaining_day)

    def search_room(self, remaining_search: int | None = None) -> bool:
        with self._lock:
            room = self.spent_searches + self.inflight_searches < self.searches_per_day
            if remaining_search is not None:
                room = room and (remaining_search - self.inflight_searches) > 0
        return room

    def reserve_search(self, key: str, remaining_search: int | None = None) -> bool:
        """Reserve one ledger slot for a query; a query already charged today (a retry) needs none."""
        with self._lock:
            if key in self._charged:
                return True
            if self.spent_searches + self.inflight_searches >= self.searches_per_day:
                return False
            if remaining_search is not None and (remaining_search - self.inflight_searches) <= 0:
                return False
            self.inflight_searches += 1
            return True

    def settle_search(self, key: str) -> None:
        """Charge the query once, whatever its outcome (the provider charges the first attempt)."""
        with self._lock:
            if key in self._charged:
                return
            self._charged.add(key)
            self.inflight_searches = max(0, self.inflight_searches - 1)
            self.spent_searches += 1

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


def _log(msg: str) -> None:
    print(f"  {dt.datetime.now(dt.timezone.utc).strftime('%H:%M:%S')} {msg}", flush=True)


@dataclass
class DayResult:
    date: str
    census: list[dict[str, Any]] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)
    files: list[Path] = field(default_factory=list)
    complete: bool = False
    manifest_path: Path | None = None
    started_at: str = ""

    def add_file(self, p: Path) -> None:
        if p not in self.files:
            self.files.append(p)


def _run_pool(jobs: Iterable[Any], fn: Callable[[Any], Any], workers: int, may_submit: Callable[[], bool],
              on_done: Callable[[Any], None]) -> None:
    """Run ``fn`` over ``jobs`` with a small pool kept topped up, so a request is always ready when the
    pacer allows one; ``may_submit`` is consulted before every submission and stops the feed."""
    it = iter(jobs)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        pending: set = set()
        while True:
            while len(pending) < workers * 2 and may_submit():
                job = next(it, None)
                if job is None:
                    break
                pending.add(pool.submit(fn, job))
            if not pending:
                break
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                on_done(fut.result())


# ------------------------------------------------------------------ layer A
def layer_a(client, cfg, date: dt.date, root: Path, res: DayResult, budget: Budget | None = None,
            progress: Progress | None = None) -> None:
    la = cfg["api"]["layer_a"]
    d = date.isoformat()
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    q: dict[str, Any] = {"pages": {}, "situations": {}, "ok": {}, "cursor_unexhausted": {}, "errors": [],
                         "error_classes": {}}
    classes: Counter = Counter()
    for sort in la["sorts"]:
        w = RawWriter(root / "raw" / "situations" / f"{d}_{sort}.jsonl")
        cursor, pages, ok, unexhausted = None, 0, False, False
        try:
            while pages < la["max_pages"] and (budget is None or budget.can_request(client.n_attempts, _quota_int(client, "remaining-day"))):
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
                if pages >= la["max_pages"]:
                    ok = True  # hit the documented ceiling: still a complete pull by protocol
                else:
                    unexhausted = True  # budget or time ran out with a cursor in hand
        except DailyCapExceeded as exc:
            q["errors"].append(f"A/{sort}: {exc}")
            classes["429"] += 1
            if budget:
                budget.stop("request_budget_exhausted")
        except (MalformedRequest, Unauthorized) as exc:
            q["errors"].append(f"A/{sort}: {exc}")
            classes[str(exc.status)] += 1
            if budget:
                budget.stop("malformed_request" if isinstance(exc, MalformedRequest) else "unauthorized")
        except ClstrError as exc:
            q["errors"].append(f"A/{sort}: {exc}")
            classes[str(exc.status)] += 1
        finally:
            w.close()
            res.add_file(w.path)
        q["pages"][sort] = pages
        q["ok"][sort] = ok
        q["cursor_unexhausted"][sort] = unexhausted
        q["situations"][sort] = len(by_id)
    q["error_classes"] = dict(classes)
    q["n_errors"] = len(q["errors"])
    _log(f"[A] census: {len(order)} situations from {sum(q['pages'].values())} pages")
    res.census = [by_id[s] for s in order]
    q["census_size"] = len(res.census)
    res.quality["layer_a"] = q


# ------------------------------------------------------------------ layer B
@dataclass
class TimelineResult:
    sid: str
    records: list[RequestRecord] = field(default_factory=list)
    pages: int = 0
    in_window: int = 0
    status: str = "ok"          # ok | retired | deferred | failed | aborted | stopped
    error: str | None = None
    http_status: int | None = None
    moved_to: str | None = None


def _fetch_timeline(client, cfg, sid: str, wstart: dt.datetime, wend: dt.datetime,
                    budget: Budget) -> TimelineResult:
    """All pages of one situation's timeline back to the window's start."""
    lb = cfg["api"]["layer_b"]
    r = TimelineResult(sid)
    before, sid_cur = None, sid
    while r.pages < lb["max_pages_per_situation"] and budget.can_timeline(client.n_attempts, _quota_int(client, "remaining-day")):
        try:
            rec = client.situation(sid_cur, timeline_limit=lb["timeline_limit"], timeline_before=before)
        except DailyCapExceeded as exc:
            budget.stop("request_budget_exhausted")
            r.status, r.error, r.http_status = "stopped", f"B/{sid}: {exc}", 429
            return r
        except (MalformedRequest, Unauthorized) as exc:
            budget.stop("malformed_request" if isinstance(exc, MalformedRequest) else "unauthorized")
            r.status, r.error, r.http_status = "aborted", f"B/{sid}: {exc}", exc.status
            return r
        except (NotFound, Gone) as exc:
            r.status, r.error, r.http_status = "retired", f"B/{sid}: {exc}", exc.status
            return r
        except (Unavailable, RateLimited) as exc:
            r.status, r.error, r.http_status = "deferred", f"B/{sid}: {exc}", exc.status
            return r
        except ClstrError as exc:
            r.status, r.error, r.http_status = "failed", f"B/{sid}: {exc}", exc.status
            return r
        budget.spend_b()
        r.records.append(rec)
        r.pages += 1
        if rec.redirected_from:
            sid_cur = rec.path.rstrip("/").rsplit("/", 1)[-1]
            r.moved_to = sid_cur
        clusters, cursor = extract_timeline(rec.body)
        stamps = [t for t in (cluster_time(c) for c in clusters) if t]
        r.in_window += sum(1 for t in stamps if wstart <= t < wend)
        oldest = min(stamps) if stamps else None
        if not clusters or oldest is None or oldest < wstart:
            break
        before = cursor or clusters[-1].get("id")
        if not before:
            break
    if r.pages == 0 and r.status == "ok":
        r.status = "stopped"   # the budget or the clock ran out before the first page
    return r


def _absorb_timeline(q: dict[str, Any], w: RawWriter, d: str, r: TimelineResult, classes: Counter) -> None:
    for rec in r.records:
        w.write(rec, "B", d)
    q["pages"] += r.pages
    q["clusters_in_window"] += r.in_window
    if r.pages:
        q["situations_fetched"] += 1
    if r.moved_to:
        q["moved"][r.sid] = r.moved_to
    if r.status == "retired" and r.sid not in q["retired"]:
        q["retired"].append(r.sid)
    if r.status == "deferred" and r.sid not in q["deferred"]:
        q["deferred"].append(r.sid)
    if r.error:
        q["errors"].append(r.error)
        classes[str(r.http_status)] += 1


def summarise_layer_b(cfg: dict[str, Any], q: dict[str, Any]) -> None:
    """Coverage over the eligible census (retired situations excluded), the failure allowance, and
    the collection invariant of §4.3a."""
    comp = cfg["completeness"]
    n = q["census_size"]
    n_el = max(0, n - len(q["retired"]))
    fetched = q["situations_fetched"]
    unfetched = max(0, n_el - fetched)
    allowed = 0
    if n_el:
        allowed = max(int(comp.get("timeline_failure_allowance_min", 0)),
                      math.ceil(float(comp.get("timeline_failure_allowance_fraction", 0.0)) * n_el))
    q["n_eligible"] = n_el
    q["unfetched"] = unfetched
    q["allowed_failures"] = allowed
    q["coverage"] = (fetched / n_el) if n_el else 1.0
    q["coverage_ok"] = unfetched <= allowed
    q["invariant_ok"] = True
    if comp.get("require_clusters_in_window", True) and fetched >= 1 and q["clusters_in_window"] == 0:
        q["invariant_ok"] = False
    q["ok"] = bool(q["coverage_ok"] and q["invariant_ok"])
    q["n_errors"] = len(q["errors"])


def layer_b(client, cfg, date: dt.date, root: Path, res: DayResult, budget: Budget,
            progress: Progress | None = None) -> None:
    """Cluster timelines of every census situation, fetched by a small pool of workers.

    The pool only hides latency: the client's global pacing keeps the request rate within the
    per-minute allowance no matter how many workers are waiting on replies."""
    d = date.isoformat()
    wstart, wend = window_for(cfg, date)
    w = RawWriter(root / "raw" / "timelines" / f"{d}.jsonl")
    workers = max(1, int(cfg["api"].get("parallel_timelines", 1)))
    q: dict[str, Any] = {"situations_fetched": 0, "census_size": len(res.census), "pages": 0,
                         "clusters_in_window": 0, "workers": workers, "retired": [], "moved": {},
                         "deferred": [], "errors": [], "n_errors": 0, "error_classes": {}}
    classes: Counter = Counter()
    todo = list(res.census)

    def on_done(r: TimelineResult) -> None:
        _absorb_timeline(q, w, d, r, classes)
        if r.status in ("retired", "deferred", "failed", "aborted"):
            _log(f"[B] {r.status}: {r.error}")
        if progress:
            progress.tick("B", f"{q['situations_fetched']}/{len(todo)} situations")

    try:
        _run_pool(todo, lambda sit: _fetch_timeline(client, cfg, sit["id"], wstart, wend, budget), workers,
                  lambda: budget.can_timeline(client.n_attempts, _quota_int(client, "remaining-day")), on_done)
    finally:
        w.close()
        res.add_file(w.path)
    q["stopped_early"] = budget.stop_reason is not None
    q["error_classes"] = dict(classes)
    summarise_layer_b(cfg, q)
    res.quality["layer_b"] = q
    _log(f"[B] timelines: {q['situations_fetched']}/{q['n_eligible']} eligible situations "
         f"({len(q['retired'])} retired, {len(q['deferred'])} deferred), {q['pages']} pages, "
         f"{q['clusters_in_window']} clusters in window")


# ------------------------------------------------------------------ layer C
@dataclass
class SearchJob:
    kind: str                   # backfill | cohort | second
    name: str
    days: int
    limit: int
    cursor: str | None = None
    for_date: str | None = None

    def key(self) -> str:
        """The query as the provider meters it: path and parameters."""
        return f"search|{self.name}|{self.days}|{self.limit}|{self.cursor or ''}"


@dataclass
class SearchResult:
    job: SearchJob
    record: RequestRecord | None = None
    status: str = "ok"          # ok | deferred | failed | stopped | aborted | cap
    error: str | None = None
    http_status: int | None = None
    confirmed: int = 0
    next_cursor: str | None = None


def _reserved(jobs: Iterable[SearchJob], budget: Budget, client, halted: Callable[[], bool]) -> Iterable[SearchJob]:
    """Yield jobs only while the search ledger has room, reserving one slot per job as it is pulled, so
    that no more successful searches can be issued than the day's allowance (§4.1)."""
    for j in jobs:
        if halted() or not budget.can_request(client.n_attempts, _quota_int(client, "remaining-day")):
            return
        if not budget.reserve_search(j.key(), _quota_int(client, "remaining-search")):
            return
        yield j


def _search_job(client, budget: Budget, matcher: NameMatcher, job: SearchJob) -> SearchResult:
    """One search whose ledger slot was reserved by ``_reserved``; the slot is settled here."""
    r = SearchResult(job)
    try:
        rec = client.search(job.name, days=job.days, limit=job.limit, cursor=job.cursor)
    except DailyCapExceeded as exc:
        r.status, r.error, r.http_status = ("cap" if exc.cap == "search" else "stopped"), f"C/{job.name}: {exc}", 429
        if exc.cap != "search":
            budget.stop("request_budget_exhausted")
        return r
    except (MalformedRequest, Unauthorized) as exc:
        budget.stop("malformed_request" if isinstance(exc, MalformedRequest) else "unauthorized")
        r.status, r.error, r.http_status = "aborted", f"C/{job.name}: {exc}", exc.status
        return r
    except (Unavailable, RateLimited) as exc:
        r.status, r.error, r.http_status = "deferred", f"C/{job.name}: {exc}", exc.status
        return r
    except ClstrError as exc:
        r.status, r.error, r.http_status = "failed", f"C/{job.name}: {exc}", exc.status
        return r
    finally:
        budget.settle_search(job.key())
    r.record = rec
    data = rec.body.get("data", []) if isinstance(rec.body, dict) else []
    r.confirmed = sum(1 for c in data if job.name in matcher.match_fields(c.get("title"), c.get("summary")))
    r.next_cursor = rec.body.get("next_cursor") if isinstance(rec.body, dict) else None
    return r


def backfill_queue(root: Path, cfg: dict[str, Any], date: dt.date) -> list[tuple[str, dt.date]]:
    """Names recorded as missing by earlier manifests inside the back-fill horizon and not since
    back-filled, oldest first (§4.7). Manifests are the only state: nothing else is kept."""
    horizon = int(cfg["completeness"]["backfill_days"])
    mdir = root / "manifests"
    missing: list[tuple[str, dt.date]] = []
    done: set[tuple[str, str]] = set()
    if not mdir.exists():
        return []
    for p in sorted(mdir.glob("*.json")):
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
            d = dt.date.fromisoformat(m["date"])
        except (ValueError, KeyError):
            continue
        if d >= date or (date - d).days > horizon:
            continue
        qc = m.get("quality", {}).get("layer_c", {}) or {}
        for name in qc.get("missing", []) or []:
            if (name, d) not in missing:
                missing.append((name, d))
        for item in (qc.get("backfill", {}) or {}).get("done", []) or []:
            if isinstance(item, dict) and item.get("name") and item.get("for"):
                done.add((item["name"], item["for"]))
    return [(n, d) for (n, d) in missing if (n, d.isoformat()) not in done]


def layer_c(client, cfg, date: dt.date, root: Path, res: DayResult, budget: Budget,
            cohort_names: Iterable[str], matcher: NameMatcher, progress: Progress | None = None,
            backfill: list[tuple[str, dt.date]] | None = None) -> None:
    """Search in the registered priority order: back-fill, today's cohort, second pages (§4.1, §4.4)."""
    lc = cfg["api"]["layer_c"]
    d = date.isoformat()
    w = RawWriter(root / "raw" / "search" / f"{d}.jsonl")
    names = list(cohort_names)
    backfill = list(backfill or [])
    workers = max(1, int(cfg["api"].get("parallel_searches", cfg["api"].get("parallel_timelines", 1))))
    q: dict[str, Any] = {"cohort_size": len(names), "searched": 0, "successful_searches": 0, "second_pages": 0,
                         "truncated": [], "missing": [], "deferred": [], "workers": workers,
                         "backfill": {"queued": len(backfill), "attempted": 0, "done": [], "missing": []},
                         "errors": [], "n_errors": 0, "error_classes": {}, "stop_reason": None}
    classes: Counter = Counter()
    pending_second: list[tuple[str, str]] = []
    searched_names: set[str] = set()
    horizon = int(cfg["completeness"]["backfill_days"])

    def absorb(r: SearchResult) -> None:
        job = r.job
        if r.status == "cap":
            q["stop_reason"] = q["stop_reason"] or "search_cap_reached"
        elif r.status == "stopped" and budget.stop_reason:
            q["stop_reason"] = q["stop_reason"] or budget.stop_reason
        if r.error:
            q["errors"].append(r.error)
            classes[str(r.http_status)] += 1
            if r.status in ("deferred", "failed", "aborted", "cap"):
                _log(f"[C] {r.status}: {r.error}")
        if r.record is None:
            if job.kind == "backfill":
                q["backfill"]["missing"].append({"name": job.name, "for": job.for_date})
            elif job.kind == "cohort":
                if r.status == "deferred":
                    q["deferred"].append(job.name)
                if job.name not in q["missing"]:
                    q["missing"].append(job.name)
            elif job.kind == "second":
                q["truncated"].append(job.name)
            return
        q["successful_searches"] += 1
        extra = {"backfill_for": job.for_date} if job.kind == "backfill" else {}
        w.write(r.record, "C", d, **extra)
        if job.kind == "backfill":
            q["backfill"]["done"].append({"name": job.name, "for": job.for_date, "days": job.days})
        elif job.kind == "cohort":
            q["searched"] += 1
            searched_names.add(job.name)
            if job.name in q["missing"]:
                q["missing"].remove(job.name)
            if r.confirmed >= lc["second_page_threshold"] and r.next_cursor:
                pending_second.append((job.name, r.next_cursor))
        elif job.kind == "second":
            q["second_pages"] += 1
            if r.confirmed >= lc["second_page_threshold"]:
                q["truncated"].append(job.name)
        if progress:
            progress.tick("C", f"{q['searched']}/{len(names)} names searched")

    def halted() -> bool:
        return q["stop_reason"] is not None or budget.stop_reason is not None

    def may_submit() -> bool:
        return not halted() and budget.time_left()

    try:
        # priority 1: back-fill of names missed on earlier days, oldest first, within the reserve
        reserve = int(lc.get("backfill_reserve", 0))
        jobs: list[SearchJob] = []
        for name, for_date in backfill[:reserve]:
            days = min(horizon, (date - for_date).days + int(lc["days"]))
            jobs.append(SearchJob("backfill", name, days, int(lc["limit"]), None, for_date.isoformat()))
        q["backfill"]["attempted"] = len(jobs)
        # priority 2: the first page for every name in today's cohort
        jobs += [SearchJob("cohort", n, int(lc["days"]), int(lc["limit"])) for n in names]
        _run_pool(_reserved(jobs, budget, client, halted), lambda j: _search_job(client, budget, matcher, j),
                  workers, may_submit, absorb)
        # priority 3: second pages, in cohort order, within the registered allowance
        cap2 = int(lc.get("second_pages_max", lc.get("spare_searches", 0)))
        order = {n: i for i, n in enumerate(names)}
        pending_second.sort(key=lambda t: order.get(t[0], 10**9))
        second = [SearchJob("second", n, int(lc["days"]), int(lc["limit"]), cur) for n, cur in pending_second[:cap2]]
        for n, _ in pending_second[cap2:]:
            q["truncated"].append(n)
        _run_pool(_reserved(second, budget, client, halted), lambda j: _search_job(client, budget, matcher, j),
                  workers, may_submit, absorb)
    finally:
        w.close()
        res.add_file(w.path)
    for n in names:
        if n not in searched_names and n not in q["missing"]:
            q["missing"].append(n)          # never reached: ledger, budget, or time
    q["error_classes"] = dict(classes)
    q["n_errors"] = len(q["errors"])
    q["ok"] = not q["missing"]
    res.quality["layer_c"] = q
    _log(f"[C] search: {q['searched']}/{len(names)} names, {len(q['backfill']['done'])} back-filled, "
         f"{q['second_pages']} second pages, {len(q['truncated'])} truncated, {len(q['missing'])} missing")


# ------------------------------------------------------------------ pass 2
def second_pass(client, cfg, date: dt.date, root: Path, res: DayResult, budget: Budget,
                matcher: NameMatcher, progress: Progress | None = None) -> None:
    """One more attempt at every request that gave up on a 5xx, at the end of the run (§4.6a)."""
    if not cfg["api"].get("second_pass", True):
        return
    d = date.isoformat()
    wstart, wend = window_for(cfg, date)
    qb = res.quality.get("layer_b")
    qc = res.quality.get("layer_c")
    workers = max(1, int(cfg["api"].get("parallel_timelines", 1)))
    if qb and qb.get("deferred") and budget.stop_reason is None:
        w = RawWriter(root / "raw" / "timelines" / f"{d}.jsonl")
        classes: Counter = Counter(qb.get("error_classes", {}))
        deferred = list(qb["deferred"])
        qb["deferred"] = []
        stats = {"attempted": len(deferred), "recovered": 0}

        def on_done(r: TimelineResult) -> None:
            _absorb_timeline(qb, w, d, r, classes)
            if r.pages:
                stats["recovered"] += 1
            if progress:
                progress.tick("B2", f"{stats['recovered']}/{stats['attempted']} recovered")

        try:
            _run_pool(deferred, lambda sid: _fetch_timeline(client, cfg, sid, wstart, wend, budget), workers,
                      lambda: budget.can_timeline(client.n_attempts, _quota_int(client, "remaining-day")), on_done)
        finally:
            w.close()
            res.add_file(w.path)
        qb["second_pass"] = stats
        qb["error_classes"] = dict(classes)
        summarise_layer_b(cfg, qb)
        _log(f"[B2] second pass: {stats['recovered']}/{stats['attempted']} deferred timelines recovered")
    if qc and qc.get("deferred") and budget.stop_reason is None and qc.get("stop_reason") is None:
        lc = cfg["api"]["layer_c"]
        w = RawWriter(root / "raw" / "search" / f"{d}.jsonl")
        classes = Counter(qc.get("error_classes", {}))
        deferred = list(qc["deferred"])
        qc["deferred"] = []
        stats = {"attempted": len(deferred), "recovered": 0}
        cworkers = max(1, int(cfg["api"].get("parallel_searches", workers)))

        def on_search(r: SearchResult) -> None:
            if r.record is not None:
                w.write(r.record, "C", d, second_pass=True)
                qc["searched"] += 1
                qc["successful_searches"] += 1
                stats["recovered"] += 1
                if r.job.name in qc["missing"]:
                    qc["missing"].remove(r.job.name)
            else:
                if r.error:
                    qc["errors"].append(r.error)
                    classes[str(r.http_status)] += 1
                if r.status == "cap":
                    qc["stop_reason"] = qc["stop_reason"] or "search_cap_reached"

        def halted() -> bool:
            return qc["stop_reason"] is not None or budget.stop_reason is not None

        try:
            _run_pool(_reserved([SearchJob("cohort", n, int(lc["days"]), int(lc["limit"])) for n in deferred],
                                budget, client, halted),
                      lambda j: _search_job(client, budget, matcher, j), cworkers,
                      lambda: not halted() and budget.time_left(), on_search)
        finally:
            w.close()
            res.add_file(w.path)
        qc["second_pass"] = stats
        qc["error_classes"] = dict(classes)
        qc["n_errors"] = len(qc["errors"])
        qc["ok"] = not qc["missing"]
        _log(f"[C2] second pass: {stats['recovered']}/{stats['attempted']} deferred searches recovered")


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
                               "successful_searches": getattr(client, "n_search_ok", None),
                               "rate_limited_429": getattr(client, "n_rate_limited", None),
                               "backoff_seconds": round(float(getattr(client, "slept_s", 0.0)), 1),
                               "errors_by_status": dict(getattr(client, "errors_by_status", {}) or {})}
    res.quality["quota"] = dict(getattr(client, "quota", {}) or {})
    cfg = C.load_config()
    manifest = {
        "date": date.isoformat(),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "started_at": res.started_at,
        "registration_version": cfg["study"]["registration_version"],
        "collector": {"package_version": __version__,
                      "git_sha": os.environ.get("GITHUB_SHA"),
                      "runner": "github-actions" if os.environ.get("GITHUB_ACTIONS") else "local"},
        "complete": res.complete,
        "stop_reason": res.quality.get("stop_reason"),
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


def completeness(cfg: dict[str, Any], res: DayResult, budget: Budget | None = None) -> tuple[bool, str | None]:
    """(complete, stop_reason): the day is complete when Layer A returned both orders with HTTP 200 and
    exhausted their cursors, Layer B's unfetched eligible situations are within the allowance, and the
    collection invariant held. Layer C never enters the test (§4.7)."""
    qa = res.quality.get("layer_a", {})
    qb = res.quality.get("layer_b", {})
    reasons: set[str] = set()
    stop = budget.stop_reason if budget else res.quality.get("stop_reason")
    if stop in ("malformed_request", "unauthorized", "operator_abort"):
        reasons.add(stop)
    for s in cfg["api"]["layer_a"]["sorts"]:
        if not qa.get("ok", {}).get(s, False):
            reasons.add("layer_a_cursor_unexhausted" if qa.get("cursor_unexhausted", {}).get(s) else "layer_a_http_error")
    if stop in ("request_budget_exhausted", "time_budget_exhausted") and (not qb or qb.get("stopped_early")):
        reasons.add(stop)
    if qb and not qb.get("coverage_ok", False):
        reasons.add("coverage_below_threshold")
    if not qb:
        reasons.add("coverage_below_threshold")
    if qb and not qb.get("invariant_ok", True):
        reasons.add("zero_clusters_in_window")
    for r in STOP_REASONS:
        if r in reasons:
            return False, r
    return True, None


# ---------------------------------------------------------------- driver
def run_day(client, cfg: dict[str, Any], date: dt.date, root: Path, matcher: NameMatcher,
            cohort_df=None) -> DayResult:
    t0 = time.monotonic()
    res = DayResult(date=date.isoformat(), started_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    b = cfg["api"]["budget"]
    minutes = float(cfg["api"].get("time_budget_minutes", 0) or 0)
    budget = Budget(b["requests_per_day"], b["searches_per_day"], cfg["api"]["layer_b"]["budget"],
                    cfg["api"]["reserve"], deadline=(t0 + minutes * 60.0) if minutes > 0 else float("inf"))
    progress = Progress(client)
    errors_path = root / "raw" / "errors" / f"{date.isoformat()}.jsonl"
    err_writer: RawWriter | None = None
    if cfg["api"].get("archive_errors", True) and hasattr(client, "error_sink"):
        err_writer = RawWriter(errors_path)
        client.error_sink = lambda rec: err_writer.write(rec, "error", date.isoformat())

    def on_signal(signum, frame):  # noqa: ARG001
        budget.stop("operator_abort")
        _log(f"signal {signum}: finishing in-flight requests and writing the manifest")

    prev_handlers = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                prev_handlers[sig] = signal.signal(sig, on_signal)
            except (ValueError, OSError):
                pass
    print(f"collect {res.date}: budget {b['requests_per_day']} requests, {b['searches_per_day']} searches, "
          f"{minutes:.0f} min", flush=True)
    try:
        layer_a(client, cfg, date, root, res, budget, progress)
        layer_b(client, cfg, date, root, res, budget, progress)
        cohort_df = cohort_df if cohort_df is not None else CO.load_or_build(cfg, root)
        k = CO.cohort_for_date(cfg, date)
        names = cohort_df.loc[cohort_df["cohort"] == k, "name"].tolist()
        res.quality["cohort"] = k
        layer_c(client, cfg, date, root, res, budget, names, matcher, progress,
                backfill=backfill_queue(root, cfg, date))
        second_pass(client, cfg, date, root, res, budget, matcher, progress)
    except KeyboardInterrupt:
        budget.stop("operator_abort")
    finally:
        for sig, h in prev_handlers.items():
            try:
                signal.signal(sig, h)
            except (ValueError, OSError):
                pass
        if err_writer is not None:
            err_writer.close()
            client.error_sink = None
            if errors_path.exists() and errors_path.stat().st_size > 0:
                res.add_file(errors_path)
    res.quality.setdefault("layer_b", {})
    res.quality.setdefault("layer_c", {})
    res.complete, reason = completeness(cfg, res, budget)
    res.quality["stop_reason"] = reason
    res.quality["halted"] = budget.stop_reason
    res.quality["layers_ok"] = {"a": all(res.quality.get("layer_a", {}).get("ok", {}).values() or [False]),
                                "b": bool(res.quality["layer_b"].get("ok", False)),
                                "c": bool(res.quality["layer_c"].get("ok", False))}
    res.quality["elapsed_seconds"] = round(time.monotonic() - t0, 1)
    write_manifest(root, date, res, client)
    qb = res.quality["layer_b"]
    if qb and not qb.get("invariant_ok", True):
        print(f"collect {res.date}: INVARIANT FAILED — {qb.get('situations_fetched')} timelines fetched and no cluster "
              f"inside the window; see §4.3a. The day is incomplete.", flush=True)
    print(f"collect {res.date}: complete={res.complete}"
          + (f" ({reason})" if reason else "")
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
