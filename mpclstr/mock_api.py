"""A deterministic stand-in for the CLSTR API, for tests and dry runs.

It produces responses in the documented v1 shapes so the collector, the
deriver and the tests can run without network access or a key. Content is
synthetic; a configurable fraction of clusters mention names from the
registered list so that matching can be exercised end to end.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import threading
import time
from typing import Any

import numpy as np

from .clstr_client import RequestRecord

_CATEGORIES = ["politics", "business", "technology", "health", "sports", "culture", "international", "crime"]
_WORDS = ("summit talks trade court election storm rescue launch strike merger vaccine flood "
          "festival verdict rally outage ceasefire drought harvest satellite championship").split()


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class MockClstrClient:
    """Mimics ``ClstrClient`` for one or more pull days."""

    def __init__(self, names: list[str], *, pull_time: dt.datetime, n_situations: int = 120,
                 clusters_per_situation: int = 6, mention_rate: float = 0.25, seed: int = 0,
                 page_size_cap: int = 50, latency_s: float = 0.0):
        self.names = list(names)
        self.pull_time = pull_time
        self.n_situations = n_situations
        self.k = clusters_per_situation
        self.mention_rate = mention_rate
        self.rng = np.random.default_rng(seed)
        self.n_attempts = 0
        self.n_searches = 0
        self.n_rate_limited = 0
        self.slept_s = 0.0
        self.page_size_cap = page_size_cap
        self.latency_s = latency_s
        self._lock = threading.Lock()
        self._build()

    # ------------------------------------------------------------ synthetic data
    def _build(self) -> None:
        self.situations: list[dict[str, Any]] = []
        self.timelines: dict[str, list[dict[str, Any]]] = {}
        self.clusters: list[dict[str, Any]] = []
        for i in range(self.n_situations):
            sid = hashlib.md5(f"sit{i}-{self.pull_time.date()}".encode()).hexdigest()[:12]
            words = self.rng.choice(_WORDS, 3)
            title = " ".join(words).capitalize()
            first_seen = self.pull_time - dt.timedelta(days=int(self.rng.integers(0, 20)))
            sig = int(self.rng.integers(1, 11))
            self.situations.append({
                "id": sid, "slug": f"sit-{i}", "title": title,
                "summary_preview": f"{title}. Developments continue.",
                "cluster_count": self.k * 3, "source_count": self.k * 10,
                "first_seen": _iso(first_seen), "last_updated": _iso(self.pull_time - dt.timedelta(hours=1)),
                "status": "ACTIVE", "category": str(self.rng.choice(_CATEGORIES)),
                "categories": [str(self.rng.choice(_CATEGORIES))], "countries": ["US"],
                "significance_score": sig, "latest_cluster_title": title,
                "url": f"https://clstr.news/situations/sit-{i}",
            })
            tl = []
            for j in range(self.k * 3):  # 3 days of clusters, newest first
                hours_ago = 2 + j * (72 / (self.k * 3))
                pub = self.pull_time - dt.timedelta(hours=hours_ago)
                mention = ""
                if self.rng.random() < self.mention_rate:
                    mention = " " + str(self.rng.choice(self.names))
                ctitle = f"{title} update {j}{mention}"
                cid = hashlib.md5(f"{sid}-{j}".encode()).hexdigest()[:12]
                c = {"id": cid, "slug": f"{sid}-{j}", "title": ctitle,
                     "summary": f"Summary of {ctitle.lower()}.", "category": self.situations[-1]["category"],
                     "countries": ["US"], "significance_score": int(self.rng.integers(1, 11)),
                     "sources": int(self.rng.integers(1, 40)), "published_at": _iso(pub),
                     "updated_at": _iso(pub), "url": f"https://clstr.news/cluster/{sid}-{j}",
                     "situation_id": sid}
                tl.append(c)
                self.clusters.append(c)
            self.timelines[sid] = tl
        self.by_relevance = sorted(self.situations, key=lambda s: -s["significance_score"])
        self.by_recent = sorted(self.situations, key=lambda s: s["last_updated"], reverse=True)

    # ---------------------------------------------------------------- endpoints
    def _rec(self, path: str, params: dict[str, Any], body: Any, is_search: bool = False) -> RequestRecord:
        if self.latency_s:
            time.sleep(self.latency_s)
        with self._lock:
            self.n_attempts += 1
            if is_search:
                self.n_searches += 1
        return RequestRecord(path, {k: v for k, v in params.items() if v is not None}, 200,
                             dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), 5, 1, body)

    def list_situations(self, *, limit, days, sort, category, country, cursor=None) -> RequestRecord:
        limit = min(limit, self.page_size_cap)
        order = self.by_relevance if sort == "relevance" else self.by_recent
        start = int(cursor) if cursor else 0
        page = order[start:start + limit]
        nxt = str(start + limit) if start + limit < len(order) else None
        body = {"data": page, "next_cursor": nxt}
        return self._rec("situations", {"limit": limit, "days": days, "sort": sort, "category": category,
                                        "country": country, "cursor": cursor}, body)

    def situation(self, situation_id, *, timeline_limit, timeline_before=None) -> RequestRecord:
        tl = self.timelines[situation_id]
        start = 0
        if timeline_before:
            ids = [c["id"] for c in tl]
            start = ids.index(timeline_before) + 1
        page = tl[start:start + timeline_limit]
        sit = next(s for s in self.situations if s["id"] == situation_id)
        body = dict(sit)
        body["summary"] = sit["summary_preview"]
        body["timeline"] = page
        body["next_timeline_before"] = page[-1]["id"] if start + timeline_limit < len(tl) and page else None
        return self._rec(f"situations/{situation_id}",
                         {"timeline_limit": timeline_limit, "timeline_before": timeline_before}, body)

    def search(self, q, *, days, limit, cursor=None) -> RequestRecord:
        cutoff = self.pull_time - dt.timedelta(days=days)
        hits = [c for c in self.clusters if q.casefold() in c["title"].casefold()
                and dt.datetime.fromisoformat(c["published_at"].replace("Z", "+00:00")) >= cutoff]
        # semantic neighbours fill the page even when nothing mentions the name
        others = [c for c in self.clusters if c not in hits][: max(0, limit)]
        pool = hits + others
        start = int(cursor) if cursor else 0
        page = pool[start:start + limit]
        nxt = str(start + limit) if start + limit < len(pool) else None
        body = {"data": page, "query": {"q": q, "days": days}, "next_cursor": nxt}
        return self._rec("search", {"q": q, "days": days, "limit": limit, "cursor": cursor}, body, is_search=True)

    # convenience for tests
    def dump(self) -> str:
        return json.dumps({"situations": len(self.situations), "clusters": len(self.clusters)})
