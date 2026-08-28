"""A paced, budgeted, logged client for the CLSTR v1 REST API.

Only three endpoints are used (PREREGISTRATION.md Appendix B):

    GET /situations         limit, days, sort, category, country, cursor
    GET /situations/{id}    timeline_limit, timeline_before
    GET /search             q, days, limit, cursor

The client never logs or stores the API key. Every request — including
retries — is counted against the daily request cap, and every search page
against the daily search cap, exactly as the provider counts them.
"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests


class ClstrError(RuntimeError):
    pass


@dataclass
class RequestRecord:
    path: str
    params: dict[str, Any]
    status: int
    requested_at: str
    elapsed_ms: int
    attempt: int
    body: Any = None

    def as_raw_line(self, layer: str, date: str) -> dict[str, Any]:
        return {
            "layer": layer,
            "date": date,
            "request": {"path": self.path, "params": self.params},
            "status": self.status,
            "requested_at": self.requested_at,
            "elapsed_ms": self.elapsed_ms,
            "attempt": self.attempt,
            "body": self.body,
        }


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
    n_attempts: int = field(default=0, init=False)
    n_searches: int = field(default=0, init=False)
    _last_start: float = field(default=-1e9, init=False)

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.api_key}",
                                     "Accept": "application/json",
                                     "User-Agent": "mp_clstr_news/0.2 (pre-registered study)"})

    # ------------------------------------------------------------------ core
    def _pace(self) -> None:
        min_gap = 60.0 / float(self.requests_per_minute)
        now = self.clock()
        wait = self._last_start + min_gap - now
        if wait > 0:
            self.sleep(wait)
        self._last_start = self.clock()

    def get(self, path: str, params: dict[str, Any] | None = None, *, is_search: bool = False) -> RequestRecord:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 2):
            self._pace()
            self.n_attempts += 1
            if is_search:
                self.n_searches += 1
            t0 = self.clock()
            requested_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:  # network problem: retry
                last_exc = exc
                self.sleep(min(60.0, 2.0 ** attempt))
                continue
            elapsed_ms = int((self.clock() - t0) * 1000)
            if resp.status_code == 200:
                try:
                    body = resp.json()
                except ValueError as exc:
                    raise ClstrError(f"non-JSON body from {path}") from exc
                return RequestRecord(path, params, 200, requested_at, elapsed_ms, attempt, body)
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else min(60.0, 2.0 ** attempt)
                except ValueError:
                    delay = min(60.0, 2.0 ** attempt)
                last_exc = ClstrError(f"HTTP {resp.status_code} from {path}")
                self.sleep(delay)
                continue
            # 4xx other than 429: do not retry
            raise ClstrError(f"HTTP {resp.status_code} from {path}: {resp.text[:200]}")
        raise ClstrError(f"gave up on {path} after {self.retries + 1} attempts: {last_exc}")

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
