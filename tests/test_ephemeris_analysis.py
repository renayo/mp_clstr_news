import argparse
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mpclstr import analysis
from mpclstr.ephemeris import assert_frame, julian_day, mean_node, parse_horizons_csv, true_node
from mpclstr.synthetic import make_synthetic

SAMPLE = """*******************************************************************************
$$SOE
 2026-Sep-16 00:00, , ,  173.4567890,   2.1234567,
 2026-Sep-17 00:00, , ,  174.4321000,  -0.5000000,
$$EOE
*******************************************************************************"""


def test_parse_horizons():
    df = parse_horizons_csv(SAMPLE)
    assert list(df["date"]) == ["2026-09-16", "2026-09-17"]
    assert np.isclose(df["lon"].iloc[0], 173.456789) and np.isclose(df["lat"].iloc[1], -0.5)
    with pytest.raises(ValueError):
        parse_horizons_csv("no block here")


def test_nodes():
    j2000 = julian_day(dt.datetime(2000, 1, 1, 12, tzinfo=dt.timezone.utc))
    assert np.isclose(j2000, 2451545.0)
    assert np.isclose(mean_node(j2000), 125.0445550)
    # retrograde ~ -19.34 deg/yr
    j1 = julian_day(dt.datetime(2027, 1, 1, tzinfo=dt.timezone.utc))
    j2 = julian_day(dt.datetime(2028, 1, 1, tzinfo=dt.timezone.utc))
    assert -19.6 < ((mean_node(j2) - mean_node(j1) + 180) % 360 - 180) < -19.1
    # true node stays within ~2 deg of the mean node (the periodic terms sum to at most ~1.97 deg)
    for k in range(0, 3650, 37):
        j = j1 + k
        diff = (true_node(j) - mean_node(j) + 180) % 360 - 180
        assert abs(diff) < 2.0


def test_frame_assertion():
    idx = pd.Index(["2027-03-20", "2027-03-21"], name="date")
    assert_frame(pd.DataFrame({"Sun": [359.6, 0.6]}, index=idx))
    with pytest.raises(AssertionError):
        assert_frame(pd.DataFrame({"Sun": [335.4, 336.4]}, index=idx))   # a sidereal-looking Sun fails


def _args(**kw):
    base = dict(series="N", node="mean", ephemeris=None, septile_lag=51, exclude_short=False, exclude_top=0,
                exclude_wordlist=None, sidereal=False, year=None, interim_label="test", n_rep=30, seed=42, float32=False)
    base.update(kw)
    return argparse.Namespace(**base)


def test_analysis_end_to_end_synthetic(tmp_path, cfg):
    root = tmp_path / "synth"
    make_synthetic(root, cfg, days=100, bodies=40, pool=50, plant=0.6, seed=3)
    summary, nulls = analysis.run(cfg, root, _args())
    assert summary["dataset"]["days"] == 100 and summary["dataset"]["bodies"] == 40
    for h in ("H1", "H3", "H4", "H5", "H6", "H7", "H8"):
        assert "supported" in summary["hypotheses"][h]
    assert set(summary["hypotheses"]["H2"]) == set(r["name"] for r in cfg["reference_points"] if r["independent"])
    assert summary["tests"]["D_Sun"]["compound"]["d"] > 2       # planted Sun signal visible
    assert "Ketu" in summary["detail"]["per_reference"]          # reported descriptively
    assert nulls["unnamed"]["D"].shape == (30,)
    # robustness switches run
    s2, _ = analysis.run(cfg, root, _args(node="true", sidereal=True, exclude_short=True, exclude_top=3, n_rep=5))
    assert s2["dataset"]["bodies"] <= 40
