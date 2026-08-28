"""Ephemeris build (PREREGISTRATION.md §6).

    python -m mpclstr.ephemeris resolve            # names -> minor-planet numbers (JPL SBDB) -> data/body_ids.csv
    python -m mpclstr.ephemeris build [--epoch 00:00] [--out data/ephemeris]

Geocentric apparent ecliptic longitudes of date from JPL Horizons (OBSERVER
table, CENTER='500@399', QUANTITIES='31'), one row per window day at the
registered epoch, for the verified named bodies, the unnamed control pool and
the ten major bodies; Rahu from the Meeus mean-node polynomial (Ch. 47) with
the true node as a sensitivity alternative; Ketu = Rahu + 180°; FPOA = 0°.

The build asserts the frame by checking that the Sun crosses 0° between the
two daily rows that bracket the March 2027 equinox.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from . import config as C

HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"
SBDB = "https://ssd-api.jpl.nasa.gov/sbdb.api"


# ---------------------------------------------------------------- Meeus nodes
def julian_day(t: dt.datetime) -> float:
    t = t.astimezone(dt.timezone.utc)
    y, m, d = t.year, t.month, t.day
    h = t.hour + t.minute / 60.0 + t.second / 3600.0
    if m <= 2:
        y -= 1
        m += 12
    A = y // 100
    B = 2 - A + A // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + B - 1524.5 + h / 24.0


def mean_node(jd: float) -> float:
    """Mean longitude of the Moon's ascending node, degrees (Meeus Ch. 47; first-study constants)."""
    T = (jd - 2451545.0) / 36525.0
    om = (125.0445550 - 1934.1361849 * T + 0.0020762 * T ** 2 + T ** 3 / 467410.0 - T ** 4 / 60616000.0)
    return om % 360.0


def true_node(jd: float) -> float:
    """True ascending node: mean node plus the principal periodic terms (Meeus Ch. 47)."""
    T = (jd - 2451545.0) / 36525.0
    D = 297.8501921 + 445267.1114034 * T - 0.0018819 * T ** 2 + T ** 3 / 545868.0 - T ** 4 / 113065000.0
    M = 357.5291092 + 35999.0502909 * T - 0.0001536 * T ** 2 + T ** 3 / 24490000.0
    Mp = 134.9633964 + 477198.8675055 * T + 0.0087414 * T ** 2 + T ** 3 / 69699.0 - T ** 4 / 14712000.0
    F = 93.2720950 + 483202.0175233 * T - 0.0036539 * T ** 2 - T ** 3 / 3526000.0 + T ** 4 / 863310000.0
    r = np.deg2rad
    corr = (-1.4979 * np.sin(r(2 * (D - F))) - 0.1500 * np.sin(r(M)) - 0.1226 * np.sin(r(2 * D))
            + 0.1176 * np.sin(r(2 * F)) - 0.0801 * np.sin(r(2 * (Mp - F))))
    return (mean_node(jd) + corr) % 360.0


# ------------------------------------------------------------- Horizons I/O
_HZ_DATE = re.compile(r"^\s*(\d{4}-[A-Za-z]{3}-\d{2} \d{2}:\d{2})")


def parse_horizons_csv(text: str) -> pd.DataFrame:
    """Rows between $$SOE and $$EOE of a CSV_FORMAT='YES' OBSERVER table with QUANTITIES='31'."""
    if "$$SOE" not in text or "$$EOE" not in text:
        raise ValueError("no ephemeris block in Horizons response: " + text[:300].replace("\n", " "))
    block = text.split("$$SOE", 1)[1].split("$$EOE", 1)[0]
    rows = []
    for ln in block.splitlines():
        m = _HZ_DATE.match(ln)
        if not m:
            continue
        when = dt.datetime.strptime(m.group(1), "%Y-%b-%d %H:%M")
        nums = [float(x) for x in re.findall(r"[-+]?\d+\.\d+(?:[eE][-+]?\d+)?", ln.split(",", 1)[1])]
        if len(nums) < 2:
            continue
        rows.append({"date": when.date().isoformat(), "lon": nums[0] % 360.0, "lat": nums[1]})
    return pd.DataFrame(rows)


def horizons_longitudes(command: str, start: dt.date, stop: dt.date, epoch: str = "00:00",
                        session: requests.Session | None = None, retries: int = 4) -> pd.DataFrame:
    s = session or requests.Session()
    params = {
        "format": "text", "COMMAND": f"'{command}'", "OBJ_DATA": "'NO'", "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'", "CENTER": "'500@399'",
        "START_TIME": f"'{start.isoformat()} {epoch}'",
        # STOP is exclusive of the step landing exactly on it only when it does not divide; add one minute
        "STOP_TIME": f"'{stop.isoformat()} {epoch}'", "STEP_SIZE": "'1 d'",
        "QUANTITIES": "'31'", "CAL_FORMAT": "'CAL'", "ANG_FORMAT": "'DEG'", "CSV_FORMAT": "'YES'",
        "TIME_DIGITS": "'MINUTES'", "EXTRA_PREC": "'YES'",
    }
    last = None
    for attempt in range(retries):
        try:
            r = s.get(HORIZONS, params=params, timeout=120)
            if r.status_code == 200:
                return parse_horizons_csv(r.text)
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        except (requests.RequestException, ValueError) as exc:
            last = str(exc)
        time.sleep(2.0 ** attempt)
    raise RuntimeError(f"Horizons failed for {command}: {last}")


# ---------------------------------------------------------------- SBDB names
def _clean(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.casefold())


def resolve_name(name: str, session: requests.Session | None = None) -> dict[str, Any]:
    """Resolve a minor-planet name to its number and SPK-ID via the JPL SBDB API."""
    s = session or requests.Session()
    tried = [name, name.replace(" ", ""), name.replace("'", "")]
    for q in dict.fromkeys(tried):
        r = s.get(SBDB, params={"sstr": q}, timeout=60)
        if r.status_code != 200:
            continue
        j = r.json()
        obj = j.get("object")
        if obj:
            full = obj.get("fullname", "")
            m = re.match(r"^\s*(\d+)\s+(.*?)\s*(\(.*\))?\s*$", full)
            number = m.group(1) if m else obj.get("des")
            found = m.group(2) if m else full
            return {"name": name, "number": number, "spkid": obj.get("spkid"), "fullname": full,
                    "exact": _clean(found) == _clean(name), "status": "resolved"}
        lst = j.get("list") or []
        exact = [c for c in lst if _clean(re.sub(r"^\d+\s+", "", c.get("name", ""))) == _clean(name)]
        if len(exact) == 1:
            c = exact[0]
            num = re.match(r"^\s*(\d+)", c.get("name", "")) or re.match(r"^\s*(\d+)", c.get("pdes", ""))
            return {"name": name, "number": num.group(1) if num else c.get("pdes"), "spkid": None,
                    "fullname": c.get("name"), "exact": True, "status": "resolved-from-list"}
        if lst:
            return {"name": name, "number": None, "spkid": None, "fullname": json.dumps(lst[:5]),
                    "exact": False, "status": "ambiguous"}
    return {"name": name, "number": None, "spkid": None, "fullname": None, "exact": False, "status": "not-found"}


def resolve_all(names: list[str], out: Path, sleep: float = 0.3) -> pd.DataFrame:
    s = requests.Session()
    rows = []
    for i, n in enumerate(names):
        rows.append(resolve_name(n, s))
        time.sleep(sleep)
        if (i + 1) % 100 == 0:
            print(f"  resolved {i + 1}/{len(names)}")
            pd.DataFrame(rows).to_csv(out, index=False)
    df = pd.DataFrame(rows)
    df.to_csv(out, index=False)
    return df


# ------------------------------------------------------------------- build
def build(cfg: dict[str, Any], root: Path, out_dir: Path, epoch: str = "00:00", sleep: float = 0.7) -> None:
    dates = C.window_dates(cfg)
    start, stop = dates[0], dates[-1]
    out_dir.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    index = pd.Index([d.isoformat() for d in dates], name="date")

    # references
    refs = pd.DataFrame(index=index)
    refs["FPOA"] = 0.0
    for r in cfg["reference_points"]:
        if r["kind"] == "major":
            df = horizons_longitudes(r["horizons"], start, stop, epoch, s).set_index("date")
            refs[r["name"]] = df["lon"].reindex(index)
            time.sleep(sleep)
    hh, mm = (int(x) for x in epoch.split(":"))
    jds = np.array([julian_day(dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=dt.timezone.utc)) for d in dates])
    refs["Rahu"] = [mean_node(j) for j in jds]
    refs["Ketu"] = (refs["Rahu"] + 180.0) % 360.0
    refs["Rahu_true"] = [true_node(j) for j in jds]
    refs["Ketu_true"] = (refs["Rahu_true"] + 180.0) % 360.0
    assert_frame(refs)
    refs.to_csv(out_dir / "references.csv", float_format="%.4f")
    print("wrote references.csv")

    # named bodies
    ids = pd.read_csv(root / "data" / "body_ids.csv")
    ids = ids[ids["status"].str.startswith("resolved") & ids["number"].notna()]
    named = pd.DataFrame(index=index)
    for i, row in enumerate(ids.itertuples(index=False)):
        try:
            df = horizons_longitudes(f"{int(row.number)};", start, stop, epoch, s).set_index("date")
            named[row.name] = df["lon"].reindex(index)
        except RuntimeError as exc:
            print(f"  {row.name}: {exc}", file=sys.stderr)
            named[row.name] = np.nan
        time.sleep(sleep)
        if (i + 1) % 50 == 0:
            named.to_csv(out_dir / "named.csv", float_format="%.4f")
            print(f"  named {i + 1}/{len(ids)}")
    named.to_csv(out_dir / "named.csv", float_format="%.4f")

    # unnamed pool
    pool = C.unnamed_pool(root)
    unnamed = pd.DataFrame(index=index)
    for i, des in enumerate(pool):
        num = re.match(r"^\s*(\d+)", des)
        cmd = f"{num.group(1)};" if num else f"{des};"
        try:
            df = horizons_longitudes(cmd, start, stop, epoch, s).set_index("date")
            unnamed[des] = df["lon"].reindex(index)
        except RuntimeError as exc:
            print(f"  {des}: {exc}", file=sys.stderr)
            unnamed[des] = np.nan
        time.sleep(sleep)
        if (i + 1) % 50 == 0:
            unnamed.to_csv(out_dir / "unnamed.csv", float_format="%.4f")
            print(f"  unnamed {i + 1}/{len(pool)}")
    unnamed.to_csv(out_dir / "unnamed.csv", float_format="%.4f")
    print("ephemeris build complete")


def assert_frame(refs: pd.DataFrame) -> None:
    """The Sun must cross 0° between the rows bracketing the March 2027 equinox (tropical frame of date)."""
    if "2027-03-20" in refs.index and "2027-03-21" in refs.index:
        a, b = float(refs.loc["2027-03-20", "Sun"]), float(refs.loc["2027-03-21", "Sun"])
        if not (a > 358.5 and b < 1.5):
            raise AssertionError(f"frame check failed: Sun at {a:.3f} on 2027-03-20 and {b:.3f} on 2027-03-21")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the registered ephemeris tables")
    ap.add_argument("cmd", choices=["resolve", "build"])
    ap.add_argument("--root", default=str(C.ROOT))
    ap.add_argument("--epoch", default=None, help="HH:MM UTC (default: registered epoch)")
    ap.add_argument("--out", default=None, help="output directory (default: data/ephemeris)")
    args = ap.parse_args(argv)
    cfg = C.load_config()
    root = Path(args.root)
    if args.cmd == "resolve":
        df = resolve_all(C.verified_names(root), root / "data" / "body_ids.csv")
        print(df["status"].value_counts().to_string())
        return 0
    epoch = args.epoch or cfg["study"]["ephemeris_epoch_utc"]
    out = Path(args.out) if args.out else root / "data" / "ephemeris"
    build(cfg, root, out, epoch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
