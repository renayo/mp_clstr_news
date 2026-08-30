"""A paced, budgeted, logged client for the CLSTR v1 REST API.

Only three endpoints are used (PREREGISTRATION.md Appendix B):

    GET /situations         limit, days, sort, category, country, cursor
    GET /situations/{id}    timeline_limit, timeline_before
    GET /search             q, days, limit, cursor

Responses are handled by documented status class (PREREGISTRATION.md §4.6a):

    200                    archive and return
    400 bad_request        never retried -> MalformedRequest   (a code defect; the run aborts)
    401 unauthorized       never retried -> Unauthorized       (the run aborts)
    404 not_found          never retried; a ``moved_to`` is followed once, else -> NotFound (retired)
    410 gone               never retried -> Gone               (retired)
    429 rate_limited       a per-minute cap is waited out (Retry-After) and re-issued;
                           a daily cap (Retry-After above DAILY_CAP_HINT) -> DailyCapExceeded
    500 / 502 / 503        retried with backoff; then -> Unavailable (end-of-run pass)
    network failure        as 5xx

Every attempt is counted against the daily request cap; successful ``/search``
responses are counted against the search cap (the metered unit, §4.1). Every
non-200 attempt is handed to ``error_sink`` with its status, headers and the
start of its body so that the archive holds the failures too (§4.7). The
client never logs or stores the API key.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

MAX_RETRY_AFTER = 120.0        # seconds; a burst-limit Retry-After is honoured up to this
DAILY_CAP_HINT = 600.0         # a 429 with Retry-After above this is a daily cap: stop, do not retry
BODY_KEEP = 4096               # characters of a non-200 body kept in the error archive
KEPT_HEADERS = ("retry-after", "content-type", "date", "server", "cf-ray", "cf-mitigated", "cf-cache-status")


class ClstrError(RuntimeError):
    """Base class. ``status`` is the HTTP status that decided the outcome (None for a network failure)."""

    def __init__(self, msg: str, *, status: int | None = None, path: str = "", attempts: int = 0,
                 body: Any = None):
        super().__init__(msg)
        self.status, self.path, self.attempts, self.body = status, path, attempts, body


class MalformedRequest(ClstrError):
    """400 — a malformed request is a code defect; never retried."""


class Unauthorized(ClstrError):
    """401 — no key, or key unknown or revoked; never retried."""


class NotFound(ClstrError):
    """404 without a usable ``moved_to``; never retried. A situation is recorded as retired."""


class Gone(ClstrError):
    """410 — the record existed and was retired; never retried."""


class RateLimited(ClstrError):
    """429 persisted through every retry (a per-minute cap that would not clear)."""


class DailyCapExceeded(ClstrError):
    """A 429 whose Retry-After says 'come back tomorrow'. ``cap`` is 'search' or 'day'."""

    def __init__(self, msg: str, *, cap: str = "day", **kw: Any):
        super().__init__(msg, **kw)
        self.cap = cap


class Unavailable(ClstrError):
    """5xx or a network failure persisted through every retry; eligible for the end-of-run pass."""


@dataclass
class RequestRecord:
    path: str
    params: dict[str, Any]
    status: int | None
    requested_at: str
    elapsed_ms: int
    attempt: int
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    redirected_from: str | None = None

    def as_raw_line(self, layer: str, date: str, **extra: Any) -> dict[str, Any]:
        line: dict[str, Any] = {
            "layer": layer,
            "date": date,
            "request": {"path": self.path, "params": self.params},
            "status": self.status,
            "requested_at": self.requested_at,
            "elapsed_ms": self.elapsed_ms,
            "attempt": self.attempt,
            "headers": self.headers,
            "body": self.body,
        }
        if self.redirected_from:
            line["redirected_from"] = self.redirected_from
        line.update(extra)
        return line


def _kept_headers(headers: Any) -> dict[str, str]:
    """The response headers worth archiving: quota headers, Retry-After, and the edge's identity."""
    out: dict[str, str] = {}
    try:
        items = headers.items()
    except AttributeError:
        return out
    for k, v in items:
        kl = str(k).lower()
        if kl.startswith("x-ratelimit") or kl in KEPT_HEADERS:
            out[kl] = str(v)
    return out


def _retry_after_seconds(headers: dict[str, str], attempt: int) -> float:
    """Numeric Retry-After if present, else the client's own short schedule (2, 4, 8, 16 s)."""
    ra = headers.get("retry-after")
    if ra:
        try:
            return float(ra)
        except ValueError:
            pass
    return min(60.0, 2.0 ** attempt)


def _json_or_none(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _message_of(body: Any) -> str:
    if isinstance(body, dict):
        for k in ("message", "detail", "error", "error_description"):
            v = body.get(k)
            if isinstance(v, str):
                return v
            if isinstance(v, dict):
                inner = _message_of(v)
                if inner:
                    return inner
    return ""


def moved_to_of(body: Any) -> str | None:
    """The ``moved_to`` of a 404 body, at the top level or inside an ``error`` object."""
    if not isinstance(body, dict):
        return None
    for holder in (body, body.get("error") if isinstance(body.get("error"), dict) else {}):
        v = holder.get("moved_to")
        if isinstance(v, str) and v:
            return v
    return None


@dataclass
class ClstrClient:
    api_key: str
    base_url: str = "https://api.clstr.news/v1"
    requests_per_minute: int = 60
    retries: int = 3
    timeout: float = 60.0
    session: Any = None
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    safety: float = 0.92           # use this fraction of the per-minute allowance
    error_sink: Callable[[RequestRecord], None] | None = None
    n_attempts: int = field(default=0, init=False)
    n_searches: int = field(default=0, init=False)
    n_search_ok: int = field(default=0, init=False)
    n_rate_limited: int = field(default=0, init=False)
    slept_s: float = field(default=0.0, init=False)
    errors_by_status: Counter = field(default_factory=Counter, init=False)
    quota: dict[str, str] = field(default_factory=dict, init=False)
    _last_start: float = field(default=-1e9, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.api_key}",
                                     "Accept": "application/json",
                                     "User-Agent": "mp_clstr_news/0.3 (pre-registered study)"})

    # ------------------------------------------------------------------ core
    def _pace(self) -> None:
        """Global token spacing: safe to call from several threads; throughput is bounded by the
        per-minute allowance, never by the latency of any one request."""
        min_gap = 60.0 / (float(self.requests_per_minute) * self.safety)
        with self._lock:
            now = self.clock()
            wait = self._last_start + min_gap - now
            start = max(now, self._last_start + min_gap)
            self._last_start = start
        if wait > 0:
            self.sleep(wait)

    def _count(self, is_search: bool) -> None:
        with self._lock:
            self.n_attempts += 1
            if is_search:
                self.n_searches += 1

    def _backoff(self, seconds: float) -> None:
        with self._lock:
            self.slept_s += seconds
        self.sleep(seconds)

    def _note_quota(self, headers: dict[str, str]) -> None:
        q = {k[len("x-ratelimit-"):]: v for k, v in headers.items() if k.startswith("x-ratelimit-")}
        if q:
            with self._lock:
                self.quota.update(q)
                self.quota["seen_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    def _archive_error(self, rec: RequestRecord) -> None:
        with self._lock:
            self.errors_by_status[str(rec.status)] += 1
        if self.error_sink is not None:
            try:
                self.error_sink(rec)
            except Exception:  # archiving a failure must never turn into a second failure
                pass

    def _cap_kind(self, headers: dict[str, str], body: Any, is_search: bool) -> str:
        """Which daily cap a 429 names: the quota headers first, then the message, then the endpoint."""
        if headers.get("x-ratelimit-remaining-search", "").strip() == "0":
            return "search"
        if headers.get("x-ratelimit-remaining-day", "").strip() == "0":
            return "day"
        msg = _message_of(body).lower()
        if "search" in msg:
            return "search"
        if "day" in msg or "daily" in msg:
            return "day"
        return "search" if is_search else "day"

    def _resolve_moved(self, path: str, moved: str) -> str:
        """Turn a ``moved_to`` (id, path, or URL) into a request path."""
        m = moved.strip()
        base = self.base_url.rstrip("/")
        if m.startswith("http://") or m.startswith("https://"):
            m = m[len(base):] if m.startswith(base) else m.split("/v1/", 1)[-1]
        m = m.lstrip("/")
        if m.startswith("v1/"):
            m = m[3:]
        if "/" in m:
            return m
        head = path.rstrip("/").rsplit("/", 1)[0]
        return f"{head}/{m}" if head else m

    def get(self, path: str, params: dict[str, Any] | None = None, *, is_search: bool = False,
            follow_moved_to: bool = True) -> RequestRecord:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        last: ClstrError | None = None
        for attempt in range(1, self.retries + 2):
            self._pace()
            self._count(is_search)
            t0 = self.clock()
            requested_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:  # network problem: retry
                elapsed_ms = int((self.clock() - t0) * 1000)
                last = Unavailable(f"{type(exc).__name__} from {path}", status=None, path=path, attempts=attempt)
                self._archive_error(RequestRecord(path, params, None, requested_at, elapsed_ms, attempt,
                                                  f"{type(exc).__name__}: {exc}"[:BODY_KEEP], {}))
                self._backoff(min(60.0, 2.0 ** attempt))
                continue
            elapsed_ms = int((self.clock() - t0) * 1000)
            status = resp.status_code
            headers = _kept_headers(resp.headers)
            self._note_quota(headers)
            if status == 200:
                try:
                    body = resp.json()
                except ValueError as exc:
                    raise ClstrError(f"non-JSON body from {path}", status=200, path=path, attempts=attempt) from exc
                if is_search:
                    with self._lock:
                        self.n_search_ok += 1
                return RequestRecord(path, params, 200, requested_at, elapsed_ms, attempt, body, headers)
            text = (resp.text or "")[:BODY_KEEP]
            self._archive_error(RequestRecord(path, params, status, requested_at, elapsed_ms, attempt, text, headers))
            if status == 429 or status >= 500:
                delay = _retry_after_seconds(headers, attempt)
                if status == 429:
                    with self._lock:
                        self.n_rate_limited += 1
                    if delay > DAILY_CAP_HINT:
                        raise DailyCapExceeded(f"HTTP 429 from {path} with Retry-After {delay:.0f}s",
                                               cap=self._cap_kind(headers, _json_or_none(text), is_search),
                                               status=429, path=path, attempts=attempt, body=text)
                    last = RateLimited(f"HTTP 429 from {path}", status=429, path=path, attempts=attempt, body=text)
                else:
                    last = Unavailable(f"HTTP {status} from {path}", status=status, path=path, attempts=attempt, body=text)
                self._backoff(min(delay, MAX_RETRY_AFTER))
                continue
            # every other 4xx is final on the first response
            body = _json_or_none(text)
            kw: dict[str, Any] = {"status": status, "path": path, "attempts": attempt, "body": text}
            if status == 400:
                raise MalformedRequest(f"HTTP 400 from {path}: {text[:200]}", **kw)
            if status == 401:
                raise Unauthorized(f"HTTP 401 from {path}: {text[:200]}", **kw)
            if status == 404:
                moved = moved_to_of(body)
                if moved and follow_moved_to:
                    rec = self.get(self._resolve_moved(path, moved), params, is_search=is_search,
                                   follow_moved_to=False)
                    rec.redirected_from = path
                    return rec
                raise NotFound(f"HTTP 404 from {path}: {text[:200]}", **kw)
            if status == 410:
                raise Gone(f"HTTP 410 from {path}: {text[:200]}", **kw)
            raise ClstrError(f"HTTP {status} from {path}: {text[:200]}", **kw)
        msg = f"gave up on {path} after {self.retries + 1} attempts: {last}"
        if isinstance(last, RateLimited):
            raise RateLimited(msg, status=429, path=path, attempts=self.retries + 1)
        raise Unavailable(msg, status=getattr(last, "status", None), path=path, attempts=self.retries + 1)

    # ------------------------------------------------------------- endpoints
    def list_situations(self, *, limit: int, days: int, sort: str, category: str, country: str,
                        cursor: str | None = None) -> RequestRecord:
        return self.get("situations", {"limit": limit, "days": days, "sort": sort,
                                       "category": category, "country": country, "cursor": cursor})

    def situation(self, situation_id: str, *, timeline_limit: int,
                  timeline_before: str | None = None) -> RequestRecord:
        return self.get(f"situations/{situation_id}",
                        {"timeline_limit": timeline_limit, "timeline_before": timeline_before})

    def search(self, q: str, *, days: int, limit: int, cursor: str | None = None) -> RequestRecord:
        return self.get("search", {"q": q, "days": days, "limit": limit, "cursor": cursor}, is_search=True)
