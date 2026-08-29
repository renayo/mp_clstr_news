import datetime as dt
import json
import shutil
from pathlib import Path

import pandas as pd

from mpclstr import config as C
from mpclstr.classify import DummyClassifier, classify_frame
from mpclstr.collect import run_day, window_for
from mpclstr.derive import derive, quality_tables
from mpclstr.matching import NameMatcher
from mpclstr.mock_api import MockClstrClient


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    shutil.copy(C.ROOT / "data" / "body_names.csv", root / "data" / "body_names.csv")
    shutil.copy(C.ROOT / "data" / "unnamed_pool.txt", root / "data" / "unnamed_pool.txt")
    return root


def test_two_days_collect_and_derive(tmp_path, cfg, names):
    root = _root(tmp_path)
    matcher = NameMatcher(names)
    d1 = dt.date.fromisoformat(cfg["study"]["window_start"])
    d2 = d1 + dt.timedelta(days=1)
    results = []
    for d in (d1, d2):
        _, wend = window_for(cfg, d)
        client = MockClstrClient(names, pull_time=wend, n_situations=40, clusters_per_situation=4,
                                 mention_rate=0.5, seed=int(d.strftime("%Y%m%d")))
        res = run_day(client, cfg, d, root, matcher)
        results.append((res, client))
        assert res.complete
        assert (root / "raw" / "situations" / f"{d}_relevance.jsonl").exists()
        assert (root / "raw" / "situations" / f"{d}_recent.jsonl").exists()
        assert (root / "raw" / "timelines" / f"{d}.jsonl").exists()
        assert (root / "raw" / "search" / f"{d}.jsonl").exists()
        q = res.quality
        assert q["layer_a"]["census_size"] == 40
        assert q["layer_b"]["coverage"] == 1.0
        assert q["layer_c"]["searched"] == 225 or q["layer_c"]["searched"] == 224
        assert client.n_searches <= cfg["api"]["budget"]["searches_per_day"]
        assert client.n_attempts <= cfg["api"]["budget"]["requests_per_day"]
    # hash chain
    m1 = json.loads((root / "manifests" / f"{d1}.json").read_text())
    m2 = json.loads((root / "manifests" / f"{d2}.json").read_text())
    assert m1["prev_manifest"] is None
    assert m2["prev_manifest"] == f"{d1}.json"
    import hashlib
    assert m2["prev_manifest_sha256"] == hashlib.sha256((root / "manifests" / f"{d1}.json").read_bytes()).hexdigest()
    assert all(len(h) == 64 for h in m1["files"].values())

    # derive and check counts against the mock's own truth
    frames = derive(root, cfg, names, matcher)
    N = frames["N"]
    assert list(N.index) == [d1.isoformat(), d2.isoformat()]
    for (res, client), d in zip(results, (d1, d2)):
        wstart, wend = window_for(cfg, d)
        truth = {}
        for c in client.clusters:
            ts = dt.datetime.fromisoformat(c["published_at"].replace("Z", "+00:00"))
            if not (wstart <= ts < wend):
                continue
            for n in matcher.match_fields(c["title"], c["summary"]):
                truth[n] = truth.get(n, 0) + 1
        got = N.loc[d.isoformat()]
        assert int(got.sum()) == sum(truth.values())
        for n, k in truth.items():
            assert got[n] == k
    assert (frames["A"].to_numpy() >= frames["N"].to_numpy()).all()
    assert frames["complete"]["complete"].all()
    # E: confirmed search hits assigned by published_at; E_plus never exceeds E
    assert (frames["E_plus"].to_numpy() <= frames["E"].to_numpy()).all()
    # quality tables from the dummy classifier partition N on every axis
    text = frames["clusters_text"]
    rub = C.load_rubric()
    cls = classify_frame(DummyClassifier(rub), rub, text, C.rubric_hash())
    qt = quality_tables(frames, cls, cfg, names)
    for axis, labels in cfg["classification"]["axes"].items():
        from mpclstr.derive import label_column
        tot = sum(qt[label_column(axis, l)].to_numpy() for l in labels)
        assert abs(tot - N.to_numpy()).max() < 1e-9


def test_budget_caps_timelines(tmp_path, cfg, names):
    root = _root(tmp_path)
    matcher = NameMatcher(names)
    d = dt.date.fromisoformat(cfg["study"]["window_start"])
    _, wend = window_for(cfg, d)
    small = json.loads(json.dumps(cfg))
    small["api"]["layer_b"]["budget"] = 10
    client = MockClstrClient(names, pull_time=wend, n_situations=30, clusters_per_situation=2, seed=1)
    res = run_day(client, small, d, root, matcher)
    assert res.quality["layer_b"]["situations_fetched"] == 10
    assert not res.complete                                  # coverage 10/30 < 0.98


def test_parallel_timelines_match_sequential_and_hide_latency(tmp_path, cfg, names):
    """Five workers behind one pacer: same archive as one worker, in a fraction of the wall time."""
    import copy, time
    from mpclstr.collect import Budget, DayResult, layer_a, layer_b
    d = dt.date.fromisoformat(cfg["study"]["window_start"])
    _, wend = window_for(cfg, d)
    out = {}
    for workers in (1, 5):
        root = _root(tmp_path / f"w{workers}")
        c = copy.deepcopy(cfg)
        c["api"]["parallel_timelines"] = workers
        client = MockClstrClient(names, pull_time=wend, n_situations=100, clusters_per_situation=3,
                                 mention_rate=0.5, seed=3, latency_s=0.02)
        res = DayResult(date=d.isoformat())
        b = c["api"]["budget"]
        budget = Budget(b["requests_per_day"], b["searches_per_day"], c["api"]["layer_b"]["budget"], c["api"]["reserve"])
        layer_a(client, c, d, root, res, budget)
        t0 = time.monotonic()
        layer_b(client, c, d, root, res, budget)
        elapsed = time.monotonic() - t0
        ids = set()
        for rec in (json.loads(l) for l in (root / "raw" / "timelines" / f"{d}.jsonl").read_text().splitlines()):
            for cl in rec["body"].get("timeline", []):
                ids.add(cl["id"])
        out[workers] = (res.quality["layer_b"], elapsed, client.n_attempts, ids)
    (q1, t1, n1, ids1), (q5, t5, n5, ids5) = out[1], out[5]
    assert q1["coverage"] == 1.0 and q5["coverage"] == 1.0
    assert n1 == n5 and q1["clusters_in_window"] == q5["clusters_in_window"] and q1["pages"] == q5["pages"]
    assert ids1 == ids5                                         # identical archive content
    assert t5 < t1 * 0.5                                        # 100 × 20 ms sequential vs 5 in flight


def test_time_budget_writes_incomplete_day(tmp_path, cfg, names):
    import copy
    root = _root(tmp_path)
    matcher = NameMatcher(names)
    d = dt.date.fromisoformat(cfg["study"]["window_start"])
    _, wend = window_for(cfg, d)
    c = copy.deepcopy(cfg)
    c["api"]["time_budget_minutes"] = 0.02          # ~1.2 s
    client = MockClstrClient(names, pull_time=wend, n_situations=200, clusters_per_situation=2, seed=2,
                             latency_s=0.02)
    res = run_day(client, c, d, root, matcher)
    assert not res.complete
    assert res.quality["stop_reason"] == "time budget exhausted"
    assert (root / "manifests" / f"{d}.json").exists()      # the day is still written out
    m = json.loads((root / "manifests" / f"{d}.json").read_text())
    assert m["complete"] is False and m["quality"]["stop_reason"] == "time budget exhausted"


def test_daily_cap_stops_cleanly(tmp_path, cfg, names):
    from mpclstr.clstr_client import DailyCapExceeded
    root = _root(tmp_path)
    matcher = NameMatcher(names)
    d = dt.date.fromisoformat(cfg["study"]["window_start"])
    _, wend = window_for(cfg, d)
    client = MockClstrClient(names, pull_time=wend, n_situations=30, clusters_per_situation=2, seed=4)
    real = client.situation
    calls = {"n": 0}

    def capped(*a, **k):
        calls["n"] += 1
        if calls["n"] > 5:
            raise DailyCapExceeded("HTTP 429 with Retry-After 86400s")
        return real(*a, **k)
    client.situation = capped
    res = run_day(client, cfg, d, root, matcher)
    assert not res.complete
    assert res.quality["stop_reason"].startswith("daily cap")
    assert res.quality["layer_c"]["searched"] == 0             # nothing more is requested after the cap
    assert calls["n"] <= 5 + cfg["api"]["parallel_timelines"] * 2   # in-flight workers may finish, no more


def test_client_pacing_is_global_across_threads():
    """With a fake clock, N threads issuing requests through one client never exceed the allowance."""
    import threading
    from mpclstr.clstr_client import ClstrClient

    class FakeResp:
        status_code = 200
        headers = {}
        text = ""
        def json(self): return {"data": [], "next_cursor": None}

    class FakeSession:
        headers = {}
        def get(self, url, params=None, timeout=None): return FakeResp()

    t = {"now": 0.0}
    lock = threading.Lock()

    def clock(): return t["now"]

    def sleep(s):
        with lock:
            t["now"] += s

    client = ClstrClient("k", requests_per_minute=60, session=FakeSession(), sleep=sleep, clock=clock, safety=1.0)
    starts = []

    def worker():
        for _ in range(20):
            client.get("situations", {"limit": 1})
            with lock:
                starts.append(t["now"])
    threads = [threading.Thread(target=worker) for _ in range(5)]
    for th in threads: th.start()
    for th in threads: th.join()
    assert client.n_attempts == 100
    # 100 requests at 60/min need at least 99 s of fake time between the first and the last start
    assert max(starts) - min(starts) >= 99.0 - 1e-6


def test_derive_is_incremental_when_raw_files_are_absent(tmp_path, cfg, names):
    """A fresh checkout holding only today's raw files must keep yesterday's derived rows."""
    import shutil as sh
    root = _root(tmp_path)
    matcher = NameMatcher(names)
    d1 = dt.date.fromisoformat(cfg["study"]["window_start"])
    d2 = d1 + dt.timedelta(days=1)
    for d in (d1, d2):
        _, wend = window_for(cfg, d)
        client = MockClstrClient(names, pull_time=wend, n_situations=30, clusters_per_situation=3,
                                 mention_rate=0.6, seed=int(d.strftime("%Y%m%d")))
        run_day(client, cfg, d, root, matcher)
        frames = derive(root, cfg, names, matcher)
        (root / "derived").mkdir(exist_ok=True)
        for k in ("N", "A", "S", "N_sit", "E", "E_plus"):
            frames[k].to_csv(root / "derived" / f"{k}.csv")
        frames["matched_clusters"].to_csv(root / "derived" / "matched_clusters.csv", index=False)
        (root / "classified").mkdir(exist_ok=True)
        frames["clusters_text"].to_csv(root / "classified" / "clusters_text.csv", index=False)
    full = derive(root, cfg, names, matcher)
    day1_row = full["N"].loc[d1.isoformat()].copy()
    day1_clusters = set(full["matched_clusters"].query("date == @d1.isoformat()")["cluster_id"])
    assert day1_row.sum() > 0 and day1_clusters
    # simulate the next day's fresh checkout: raw files of day 1 are gone, manifests and derived tables remain
    for f in list((root / "raw").rglob(f"{d1}*")):
        f.unlink()
    again = derive(root, cfg, names, matcher)
    assert again["complete"].loc[d1.isoformat(), "raw_in_checkout"] == False  # noqa: E712
    assert (again["N"].loc[d1.isoformat()] == day1_row).all()                   # carried, not zeroed
    assert set(again["matched_clusters"].query("date == @d1.isoformat()")["cluster_id"]) == day1_clusters
    assert (again["N"].loc[d2.isoformat()] == full["N"].loc[d2.isoformat()]).all()   # recomputed day unchanged
