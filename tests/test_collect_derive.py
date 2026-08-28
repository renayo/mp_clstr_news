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
