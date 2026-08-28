import datetime as dt

from mpclstr import config as C
from mpclstr.cohorts import cohort_for_date, make_cohorts


def test_window_and_dates(cfg):
    days = C.window_dates(cfg)
    assert len(days) == 1826
    assert days[0].isoformat() == "2026-09-16" and days[-1].isoformat() == "2031-09-15"
    assert C.day_index(cfg, dt.date(2027, 7, 2)) == 290
    assert C.day_index(cfg, dt.date(2031, 9, 15)) == 1826


def test_population_counts(names):
    assert len(names) == 1122
    assert len(C.unnamed_pool()) == 1211
    assert len([n for n in names if len(n) <= 3]) == 18


def test_cohorts(cfg, names):
    df = make_cohorts(names, cfg["seeds"]["cohorts"], 5)
    assert sorted(df["cohort"].value_counts().tolist(), reverse=True) == [225, 225, 224, 224, 224]
    assert set(df["name"]) == set(names) and len(df) == len(names)
    again = make_cohorts(names, cfg["seeds"]["cohorts"], 5)
    assert df.equals(again)
    start = dt.date.fromisoformat(cfg["study"]["window_start"])
    assert [cohort_for_date(cfg, start + dt.timedelta(days=i)) for i in range(7)] == [0, 1, 2, 3, 4, 0, 1]


def test_registered_constants(cfg):
    asp = {a["name"]: a for a in cfg["aspects"]}
    assert [asp[k]["harmonic"] for k in ("conjunction", "opposition", "trine", "square", "quintile",
                                          "sextile", "septile", "octile", "semisextile")] == [1, 2, 3, 4, 5, 6, 7, 8, 12]
    assert sorted(cfg["harmonics"]) == sorted(a["harmonic"] for a in cfg["aspects"])
    assert cfg["acf_lags"] == [30, 45, 51, 60, 72, 90, 120, 180]
    assert set(cfg["harmonious_harmonics"]) == {a["harmonic"] for a in cfg["aspects"] if a["class"] == "harmonious"}
    assert set(cfg["challenging_harmonics"]) == {a["harmonic"] for a in cfg["aspects"] if a["class"] == "challenging"}
    assert len(C.independent_reference_names(cfg)) == 12
    assert abs(cfg["inference"]["alpha_h2"] - 0.05 / 12) < 1e-9
    b = cfg["api"]
    assert (b["layer_a"]["max_pages"] * len(b["layer_a"]["sorts"]) + b["layer_b"]["budget"]
            + b["budget"]["searches_per_day"] + b["reserve"]) <= b["budget"]["requests_per_day"]
    lc = b["layer_c"]
    assert lc["n_cohorts"] == lc["days"] and 225 + lc["spare_searches"] == b["budget"]["searches_per_day"]
