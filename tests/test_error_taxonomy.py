"""The §4.6a error taxonomy, the §4.3a collection invariant, the retired-situation denominator,
the end-of-run second pass, the back-fill queue, and the error archive (§4.7).

The client tests drive ``ClstrClient`` with a fake session and a fake clock, so every status class
is exercised without the network. The collector tests run ``run_day`` against small fake clients
that answer in the documented v1 shapes.
"""
import copy
import datetime as dt
import json
import shutil
import threading
from pathlib import Path

import pytest

from mpclstr import config as C
from mpclstr.clstr_client import (ClstrClient, ClstrError, DailyCapExceeded, Gone, MalformedRequest,
                                  NotFound, RequestRecord, Unauthorized, Unavailable)
from mpclstr.collect import extract_timeline, run_day, window_for
from mpclstr.matching import NameMatcher
from mpclstr.mock_api import MockClstrClient, _iso


# ------------------------------------------------------------------ fixtures
def _root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    shutil.copy(C.ROOT / "data" / "body_names.csv", root / "data" / "body_names.csv")
    shutil.copy(C.ROOT / "data" / "unnamed_pool.txt", root / "data" / "unnamed_pool.txt")
    return root


class FakeResp:
    def __init__(self, status: int, body=None, headers=None, text: str | None = None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = text if text is not None else (json.dumps(body) if body is not None else "")

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class FakeSession:
    """Returns queued responses per path suffix; unmatched paths get 200 with an empty data list."""

    def __init__(self):
        self.headers = {}
        self.queues: dict[str, list[FakeResp]] = {}
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def queue(self, path_suffix: str, *resps: FakeResp) -> None:
        self.queues.setdefault(path_suffix, []).extend(resps)

    def get(self, url, params=None, timeout=None):
        with self._lock:
            self.calls.append(url)
            for suffix, q in self.queues.items():
                if url.endswith(suffix) and q:
                    return q.pop(0)
        return FakeResp(200, {"data": [], "next_cursor": None})


def _client(session, **kw) -> ClstrClient:
    t = {"now": 0.0}
    lock = threading.Lock()

    def clock():
        return t["now"]

    def sleep(s):
        with lock:
            t["now"] += s
    c = ClstrClient("k", session=session, sleep=sleep, clock=clock, safety=1.0,
                    requests_per_minute=6000, **kw)
    c._fake_time = t
    return c


# ------------------------------------------------------------------ the client
def test_5xx_gives_up_after_retries_and_archives_every_attempt():
    s = FakeSession()
    s.queue("/situations/x", *[FakeResp(503, {"error": "unavailable"}, {"Retry-After": "60"})] * 4)
    seen: list[RequestRecord] = []
    c = _client(s)
    c.error_sink = seen.append
    with pytest.raises(Unavailable) as ei:
        c.situation("x", timeline_limit=3)
    assert "after 4 attempts" in str(ei.value) and ei.value.status == 503
    assert len(seen) == 4 and all(r.status == 503 for r in seen)
    assert all(r.headers.get("retry-after") == "60" for r in seen)
    assert c.errors_by_status["503"] == 4
    assert c.slept_s == pytest.approx(240.0)          # the server's Retry-After, honoured every time
    assert c.n_attempts == 4


def test_5xx_then_200_succeeds_on_the_next_attempt():
    s = FakeSession()
    s.queue("/situations/x", FakeResp(502, {"error": "upstream_error"}),
            FakeResp(200, {"data": {"id": "x", "timeline": [], "timeline_cursor": {"has_more": False}}}))
    c = _client(s)
    rec = c.situation("x", timeline_limit=3)
    assert rec.status == 200 and rec.attempt == 2
    assert c.errors_by_status["502"] == 1


@pytest.mark.parametrize("status,exc", [(400, MalformedRequest), (401, Unauthorized), (410, Gone)])
def test_final_4xx_is_never_retried(status, exc):
    s = FakeSession()
    s.queue("/situations/x", FakeResp(status, {"error": "e"}))
    c = _client(s)
    with pytest.raises(exc) as ei:
        c.situation("x", timeline_limit=3)
    assert ei.value.status == status
    assert c.n_attempts == 1                           # one attempt, no retry


def test_404_moved_to_is_followed_once_and_recorded():
    s = FakeSession()
    s.queue("/situations/old", FakeResp(404, {"error": "not_found", "moved_to": "new"}))
    s.queue("/situations/new", FakeResp(200, {"data": {"id": "new", "timeline": [],
                                                       "timeline_cursor": {"has_more": False}}}))
    seen = []
    c = _client(s)
    c.error_sink = seen.append
    rec = c.situation("old", timeline_limit=3)
    assert rec.status == 200
    assert rec.path.endswith("situations/new")
    assert rec.redirected_from == "situations/old"
    assert [r.status for r in seen] == [404]           # the 404 itself is archived


def test_plain_404_is_not_found():
    s = FakeSession()
    s.queue("/situations/x", FakeResp(404, {"error": "not_found"}))
    with pytest.raises(NotFound):
        _client(s).situation("x", timeline_limit=3)


def test_429_burst_is_waited_out_and_retried():
    s = FakeSession()
    s.queue("/search", FakeResp(429, {"error": "rate_limited"}, {"Retry-After": "30"}),
            FakeResp(200, {"data": [], "next_cursor": None},
                     {"X-RateLimit-Limit-Search": "250", "X-RateLimit-Remaining-Search": "100"}))
    c = _client(s)
    rec = c.search("Tyson", days=5, limit=30)
    assert rec.status == 200 and rec.attempt == 2
    assert c.n_rate_limited == 1 and c.slept_s == pytest.approx(30.0)
    assert c.n_search_ok == 1
    assert c.quota.get("remaining-search") == "100"    # quota headers are captured


def test_429_daily_cap_stops_immediately_and_names_the_cap():
    s = FakeSession()
    s.queue("/search", FakeResp(429, {"error": "rate_limited", "message": "daily search cap reached"},
                                {"Retry-After": "20000", "X-RateLimit-Remaining-Search": "0"}))
    c = _client(s)
    with pytest.raises(DailyCapExceeded) as ei:
        c.search("Tyson", days=5, limit=30)
    assert ei.value.cap == "search"
    assert c.n_attempts == 1                           # a daily cap is never retried same-day


def test_network_failure_retries_then_defers():
    import requests as rq

    class DeadSession(FakeSession):
        def get(self, url, params=None, timeout=None):
            raise rq.ConnectionError("boom")
    c = _client(DeadSession())
    with pytest.raises(Unavailable):
        c.get("situations", {"limit": 1})
    assert c.n_attempts == 4


# ------------------------------------------------------------------ the shape
def test_extract_timeline_real_shape():
    """The documented GET /situations/{id} shape, confirmed live on 2026-08-30."""
    body = {"data": {
        "id": "0c270b48", "slug": "example", "title": "Example situation",
        "summary": "…", "cluster_count": 50, "status": "ACTIVE",
        "timeline": [
            {"id": "c1", "title": "newest", "published_at": "2026-08-29T12:53:51.000Z"},
            {"id": "c2", "title": "older", "published_at": "2026-08-29T12:34:17.000Z"},
        ],
        "timeline_cursor": {"has_more": True, "next_before": "c2", "remaining_count": 48, "total_count": 50},
        "day_span": 84,
    }}
    clusters, cursor = extract_timeline(body)
    assert [c["id"] for c in clusters] == ["c1", "c2"]
    assert cursor == "c2"
    # the provider saying has_more: false ends pagination even though ids remain
    body["data"]["timeline_cursor"] = {"has_more": False, "next_before": None,
                                       "remaining_count": 0, "total_count": 50}
    _, cursor = extract_timeline(body)
    assert cursor is None


def test_extract_timeline_tolerates_known_variants():
    cl = [{"id": "c1", "published_at": "2026-08-29T13:00:00Z"}]
    assert extract_timeline({"timeline": cl})[0] == cl                     # unwrapped (the old mock)
    assert extract_timeline({"data": {"clusters": cl}})[0] == cl           # renamed list
    assert extract_timeline({"data": {"timeline": {"items": cl}}})[0] == cl  # re-nested once more
    assert extract_timeline({"unrelated": 1})[0] == []                     # alien shape -> empty, §4.3a fires


# ------------------------------------------------------------------ the collector
def test_retired_situation_leaves_the_denominator(tmp_path, cfg, names):
    """A 404/410 between the census and the fetch is a retirement, not a coverage failure (§4.6a)."""
    root = _root(tmp_path)
    matcher = NameMatcher(names)
    d = dt.date.fromisoformat(cfg["study"]["window_start"])
    _, wend = window_for(cfg, d)
    client = MockClstrClient(names, pull_time=wend, n_situations=30, clusters_per_situation=2, seed=7)
    victim = client.situations[3]["id"]
    del client.timelines[victim]                     # the mock now answers 404 for it
    res = run_day(client, cfg, d, root, matcher)
    qb = res.quality["layer_b"]
    assert victim in qb["retired"]
    assert qb["census_size"] == 30 and qb["n_eligible"] == 29
    assert qb["situations_fetched"] == 29 and qb["coverage"] == 1.0
    assert res.complete and res.quality["stop_reason"] is None


def test_zero_clusters_in_window_fails_the_day(tmp_path, cfg, names):
    """§4.3a: timelines fetched and nothing in the window is a contradiction, not a quiet day."""
    root = _root(tmp_path)
    matcher = NameMatcher(names)
    d = dt.date.fromisoformat(cfg["study"]["window_start"])
    _, wend = window_for(cfg, d)
    client = MockClstrClient(names, pull_time=wend + dt.timedelta(days=40),   # every cluster far too old
                             n_situations=10, clusters_per_situation=2, seed=8)
    res = run_day(client, cfg, d, root, matcher)
    qb = res.quality["layer_b"]
    assert qb["situations_fetched"] == 10 and qb["clusters_in_window"] == 0
    assert qb["invariant_ok"] is False
    assert not res.complete and res.quality["stop_reason"] == "zero_clusters_in_window"


def test_second_pass_recovers_deferred_timelines_and_searches(tmp_path, cfg, names):
    root = _root(tmp_path)
    matcher = NameMatcher(names)
    d = dt.date.fromisoformat(cfg["study"]["window_start"])
    _, wend = window_for(cfg, d)
    client = MockClstrClient(names, pull_time=wend, n_situations=30, clusters_per_situation=2, seed=9)
    victims = {client.situations[1]["id"], client.situations[4]["id"]}
    real_sit, real_search = client.situation, client.search
    failed_sits, failed_names = set(), set()

    def flaky_situation(sid, **kw):
        if sid in victims and sid not in failed_sits:
            failed_sits.add(sid)
            raise Unavailable(f"gave up on situations/{sid} after 4 attempts: HTTP 503", status=503)
        return real_sit(sid, **kw)

    def flaky_search(q, **kw):
        if len(failed_names) < 3 and q not in failed_names:
            failed_names.add(q)
            raise Unavailable("gave up on search after 4 attempts: HTTP 503", status=503)
        return real_search(q, **kw)
    client.situation, client.search = flaky_situation, flaky_search
    res = run_day(client, cfg, d, root, matcher)
    qb, qc = res.quality["layer_b"], res.quality["layer_c"]
    assert qb["second_pass"] == {"attempted": 2, "recovered": 2}
    assert qb["deferred"] == [] and qb["coverage"] == 1.0
    assert qc["second_pass"]["recovered"] == 3 and qc["missing"] == []
    assert res.complete
    # the second-pass responses landed in the same raw files
    tl = [json.loads(l) for l in (root / "raw" / "timelines" / f"{d}.jsonl").read_text().splitlines()]
    assert len({r["request"]["path"] for r in tl}) == 30


def test_missing_search_is_backfilled_next_day(tmp_path, cfg, names):
    root = _root(tmp_path)
    matcher = NameMatcher(names)
    c = copy.deepcopy(cfg)
    c["api"]["second_pass"] = False                     # keep the miss so the queue has work
    d1 = dt.date.fromisoformat(cfg["study"]["window_start"])
    d2 = d1 + dt.timedelta(days=1)
    _, wend1 = window_for(c, d1)
    client = MockClstrClient(names, pull_time=wend1, n_situations=10, clusters_per_situation=2, seed=10)
    real_search = client.search
    victim = {"name": None}

    def flaky_search(q, **kw):
        if victim["name"] is None:
            victim["name"] = q
        if q == victim["name"]:
            raise Unavailable("gave up on search after 4 attempts: HTTP 503", status=503)
        return real_search(q, **kw)
    client.search = flaky_search
    res1 = run_day(client, c, d1, root, matcher)
    assert victim["name"] in res1.quality["layer_c"]["missing"]
    assert res1.complete                                # Layer C never fails the day (§4.7)

    _, wend2 = window_for(c, d2)
    client2 = MockClstrClient(names, pull_time=wend2, n_situations=10, clusters_per_situation=2, seed=11)
    res2 = run_day(client2, c, d2, root, matcher)
    done = res2.quality["layer_c"]["backfill"]["done"]
    assert {(x["name"], x["for"]) for x in done} == {(victim["name"], d1.isoformat())}
    assert done[0]["days"] == 1 + c["api"]["layer_c"]["days"]   # the window is widened to cover the miss
    lines = [json.loads(l) for l in (root / "raw" / "search" / f"{d2}.jsonl").read_text().splitlines()]
    bf = [l for l in lines if l.get("backfill_for")]
    assert len(bf) == 1 and bf[0]["backfill_for"] == d1.isoformat()
    assert bf[0]["request"]["params"]["q"] == victim["name"]
    # a third day must not back-fill it again
    d3 = d2 + dt.timedelta(days=1)
    _, wend3 = window_for(c, d3)
    client3 = MockClstrClient(names, pull_time=wend3, n_situations=10, clusters_per_situation=2, seed=12)
    res3 = run_day(client3, c, d3, root, matcher)
    assert res3.quality["layer_c"]["backfill"]["queued"] == 0


def test_error_archive_is_written_and_hashed(tmp_path, cfg, names):
    """A run whose client reports failures leaves raw/errors/<date>.jsonl, hashed in the manifest."""
    root = _root(tmp_path)
    matcher = NameMatcher(names)
    d = dt.date.fromisoformat(cfg["study"]["window_start"])
    _, wend = window_for(cfg, d)
    client = MockClstrClient(names, pull_time=wend, n_situations=8, clusters_per_situation=2, seed=13)
    client.error_sink = None                            # run_day installs the writer
    real_sit = client.situation
    tripped = {"done": False}

    def flaky(sid, **kw):
        if not tripped["done"]:
            tripped["done"] = True
            rec = RequestRecord(f"situations/{sid}", {}, 503, _iso(dt.datetime.now(dt.timezone.utc)), 5, 1,
                                '{"error": "unavailable"}', {"retry-after": "60"})
            if client.error_sink:
                client.error_sink(rec)
            raise Unavailable(f"gave up on situations/{sid} after 4 attempts: HTTP 503", status=503)
        return real_sit(sid, **kw)
    client.situation = flaky
    res = run_day(client, cfg, d, root, matcher)
    epath = root / "raw" / "errors" / f"{d}.jsonl"
    assert epath.exists()
    lines = [json.loads(l) for l in epath.read_text().splitlines()]
    assert lines and lines[0]["status"] == 503 and lines[0]["layer"] == "error"
    assert lines[0]["headers"]["retry-after"] == "60"
    m = json.loads((root / "manifests" / f"{d}.json").read_text())
    assert f"raw/errors/{d}.jsonl" in m["files"]
    assert res.complete                                 # recovered by the second pass
