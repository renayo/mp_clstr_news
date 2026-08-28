"""Ephemeris build (PREREGISTRATION.md §6).

    python -m mpclstr.ephemeris resolve            # names -> numbers (JPL SBDB) -> data/body_ids.csv; resumable
    python -m mpclstr.ephemeris build [--epoch 00:00] [--out data/ephemeris]   # resumable
    python -m mpclstr.ephemeris check [--out data/ephemeris]                   # verify the tables

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
MPC_NAMES = "https://www.minorplanetcenter.net/iau/lists/MPNames.html"
USER_AGENT = "mp_clstr_news/0.2 (pre-registered research; https://github.com/renayo/mp_clstr_news)"


def make_session() -> requests.Session:
    """A session that identifies itself; JPL's edge rejects anonymous default clients with 403."""
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9, */*;q=0.5"})
    return s


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
    s = session or make_session()
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


def _variants(name: str) -> list[str]:
    """Spellings to try in order: as given, hyphen/space swaps, no spaces, no apostrophes."""
    v = [name, name.replace(" ", "-"), name.replace("-", " "), name.replace(" ", ""),
         name.replace("'", ""), name.replace("'", " "), name.replace("-", "")]
    return list(dict.fromkeys(x for x in v if x))


def _sbdb_get(session: requests.Session, q: str, retries: int = 4) -> tuple[int, Any]:
    """One SBDB lookup with backoff on 429/5xx. Returns (status, json-or-None)."""
    status = 0
    for attempt in range(retries):
        try:
            r = session.get(SBDB, params={"sstr": q}, timeout=60)
        except requests.RequestException:
            status = -1
            time.sleep(min(60.0, 2.0 ** attempt))
            continue
        status = r.status_code
        if status == 200:
            try:
                return 200, r.json()
            except ValueError:
                return 200, None
        if status == 429 or status >= 500:
            ra = r.headers.get("Retry-After")
            try:
                delay = float(ra) if ra else min(90.0, 3.0 * 2.0 ** attempt)
            except ValueError:
                delay = min(90.0, 3.0 * 2.0 ** attempt)
            time.sleep(delay)
            continue
        return status, None            # other 4xx: not retryable for this spelling
    return status, None


def resolve_name(name: str, session: requests.Session | None = None) -> dict[str, Any]:
    """Resolve a minor-planet name to its number and SPK-ID via the JPL SBDB API.

    Status values: resolved, resolved-from-list, ambiguous, not-found, or http-<code>
    (the service could not be reached properly; re-run ``resolve`` to retry those rows)."""
    s = session or make_session()
    worst = 0
    for q in _variants(name):
        status, j = _sbdb_get(s, q)
        if status != 200 or j is None:
            worst = status if status != 200 else worst
            if status in (429, -1) or status >= 500:
                return {"name": name, "number": None, "spkid": None, "fullname": None, "exact": False,
                        "status": f"http-{status}"}
            continue
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
    return {"name": name, "number": None, "spkid": None, "fullname": None, "exact": False,
            "status": "not-found" if not worst else f"http-{worst}"}


SBDB_QUERY = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"


def fetch_named_table(session: requests.Session | None = None, cache: Path | None = None) -> pd.DataFrame:
    """All numbered asteroids with an IAU name, in one request to the SBDB query API.

    Columns: number (pdes), name, spkid. Cached to ``cache`` (CSV) when given."""
    if cache is not None and cache.exists():
        return pd.read_csv(cache, dtype=str)
    s = session or make_session()
    r = s.get(SBDB_QUERY, params={"fields": "pdes,name,spkid", "sb-kind": "a", "sb-ns": "n"}, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"SBDB query API returned HTTP {r.status_code}: {r.text[:200]}")
    j = r.json()
    fields = j.get("fields") or []
    data = j.get("data") or []
    if not fields or not data:
        raise RuntimeError(f"SBDB query API returned no table: {str(j)[:200]}")
    df = pd.DataFrame(data, columns=fields)
    df = df[df["name"].notna() & (df["name"].astype(str).str.strip() != "")]
    df = df.rename(columns={"pdes": "number"})[["number", "name", "spkid"]].astype(str)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache, index=False)
    return df


_PROVISIONAL = re.compile(r"^\d{4}\s+[A-Z]{1,2}\d*$")


def parse_mpc_names(html_text: str) -> pd.DataFrame:
    """(number) Name pairs from the MPC's alphabetical list of minor-planet names."""
    import html as _html
    text = _html.unescape(re.sub(r"<[^>]+>", " ", html_text))
    rows = {}
    for m in re.finditer(r"\((\d+)\)\s+([^\(\)\n]+?)(?=\s{2,}|\s*\(|\n|$)", text):
        num, name = m.group(1), m.group(2).strip()
        if not name or not re.search(r"[A-Za-z]", name) or _PROVISIONAL.match(name):
            continue
        rows.setdefault(num, name)
    df = pd.DataFrame({"number": list(rows.keys()), "name": list(rows.values())})
    df["spkid"] = None
    return df


def fetch_mpc_names(session: requests.Session | None = None, cache: Path | None = None) -> pd.DataFrame:
    """All named minor planets from the Minor Planet Center's alphabetical list (one page)."""
    if cache is not None and cache.exists():
        return pd.read_csv(cache, dtype=str)
    s = session or make_session()
    r = s.get(MPC_NAMES, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"MPC names list returned HTTP {r.status_code}")
    df = parse_mpc_names(r.text)
    if len(df) < 1000:
        raise RuntimeError(f"MPC names list parsed to only {len(df)} entries; format may have changed")
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache, index=False)
    return df


def fetch_bulk_table(session: requests.Session, cache_dir: Path) -> tuple[pd.DataFrame, str]:
    """The first bulk source that answers: JPL's query API, then the MPC's list."""
    errors = []
    for label, fn, cache in (("JPL SBDB query API", fetch_named_table, cache_dir / "sbdb_named_asteroids.csv"),
                             ("MPC MPNames list", fetch_mpc_names, cache_dir / "mpc_named_asteroids.csv")):
        try:
            return fn(session, cache=cache), label
        except Exception as exc:
            errors.append(f"{label}: {str(exc)[:120]}")
    raise RuntimeError("; ".join(errors))


def resolve_bulk(names: list[str], table: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Match names against the bulk table by the same normalisation as the per-name path."""
    index: dict[str, list[dict[str, str]]] = {}
    for row in table.to_dict("records"):
        index.setdefault(_clean(str(row["name"])), []).append(row)
    out: dict[str, dict[str, Any]] = {}
    for n in names:
        hits = index.get(_clean(n), [])
        if len(hits) == 1:
            h = hits[0]
            out[n] = {"name": n, "number": h["number"], "spkid": h.get("spkid"),
                      "fullname": f"{h['number']} {h['name']}", "exact": True, "status": "resolved"}
        elif len(hits) > 1:
            out[n] = {"name": n, "number": None, "spkid": None,
                      "fullname": json.dumps([f"{h['number']} {h['name']}" for h in hits[:5]]),
                      "exact": False, "status": "ambiguous"}
    return out


def resolve_all(names: list[str], out: Path, sleep: float = 1.0, session: requests.Session | None = None,
                bulk: bool = True, table: pd.DataFrame | None = None) -> pd.DataFrame:
    """Resolve every name, resuming from an existing table: rows already resolved are kept,
    every other row (not-found, ambiguous, http-*) is retried."""
    s = session or make_session()
    prev: dict[str, dict[str, Any]] = {}
    if out.exists():
        old = pd.read_csv(out)
        for row in old.to_dict("records"):
            if str(row.get("status", "")).startswith("resolved"):
                prev[row["name"]] = row
        print(f"  resuming {out.name}: {len(prev)} names already resolved, {len(names) - len(prev)} to (re)try")
    # bulk pass: one request for the whole named-asteroid table, matched locally
    if bulk:
        try:
            label = "supplied table"
            if table is None:
                print("  fetching the table of named minor planets (one request) ...")
                table, label = fetch_bulk_table(s, out.parent)
            found = resolve_bulk([n for n in names if n not in prev], table)
            print(f"  bulk table ({label}): {len(table)} named minor planets; matched "
                  f"{sum(1 for v in found.values() if v['status'] == 'resolved')} of {len(names) - len(prev)} remaining names locally")
            prev.update({k: v for k, v in found.items() if v["status"] == "resolved"})
            ambiguous = {k: v for k, v in found.items() if v["status"] == "ambiguous"}
        except Exception as exc:  # network or format problem: fall back to per-name lookups
            print(f"  bulk table unavailable ({exc}); falling back to per-name lookups")
            ambiguous = {}
    else:
        ambiguous = {}
    rows = []
    todo, throttled = 0, 0
    for i, n in enumerate(names):
        if n in prev:
            rows.append(prev[n])
            continue
        if n in ambiguous:
            rows.append(ambiguous[n])
            continue
        if throttled >= 3:
            rows.append({"name": n, "number": None, "spkid": None, "fullname": None, "exact": False,
                         "status": "http-throttled"})
            continue
        rec = resolve_name(n, s)
        throttled = throttled + 1 if str(rec["status"]).startswith("http-") else 0
        rows.append(rec)
        todo += 1
        time.sleep(sleep)
        if todo % 25 == 0:
            pd.DataFrame(rows + [prev[m] for m in names[i + 1:] if m in prev]).to_csv(out, index=False)
            done = sum(1 for r in rows if str(r.get("status", "")).startswith("resolved"))
            print(f"  {i + 1}/{len(names)} processed, {done} resolved so far")
    if throttled >= 3:
        print("  the per-name service is throttling; stopped early. Re-run 'resolve' later to retry the http-* rows.")
    df = pd.DataFrame(rows)
    df.to_csv(out, index=False)
    return df


# ------------------------------------------------------------------- build
def build(cfg: dict[str, Any], root: Path, out_dir: Path, epoch: str = "00:00", sleep: float = 0.7) -> None:
    dates = C.window_dates(cfg)
    start, stop = dates[0], dates[-1]
    out_dir.mkdir(parents=True, exist_ok=True)
    s = make_session()
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

    # named bodies (resumable: columns already complete in an existing named.csv are skipped)
    ids = pd.read_csv(root / "data" / "body_ids.csv")
    ids = ids[ids["status"].astype(str).str.startswith("resolved") & ids["number"].notna()]
    named = _load_partial(out_dir / "named.csv", index)
    _fetch_columns(named, [(row.name, f"{int(row.number)};") for row in ids.itertuples(index=False)],
                   out_dir / "named.csv", "named", start, stop, epoch, s, sleep)

    # unnamed pool (resumable)
    pool = C.unnamed_pool(root)
    unnamed = _load_partial(out_dir / "unnamed.csv", index)
    targets = []
    for des in pool:
        num = re.match(r"^\s*(\d+)", des)
        targets.append((des, f"{num.group(1)};" if num else f"{des};"))
    _fetch_columns(unnamed, targets, out_dir / "unnamed.csv", "unnamed", start, stop, epoch, s, sleep)
    print("ephemeris build complete — now run: python -m mpclstr.ephemeris check")


def _load_partial(path: Path, index: pd.Index) -> pd.DataFrame:
    """An existing table with the right date index, or an empty one."""
    if path.exists():
        df = pd.read_csv(path, index_col="date")
        if list(df.index) == list(index):
            print(f"  resuming {path.name}: {int((~df.isna().any()).sum())} columns already complete")
            return df
        print(f"  {path.name} has a different date index; rebuilding it")
    return pd.DataFrame(index=index)


def _fetch_columns(table: pd.DataFrame, targets: list[tuple[str, str]], path: Path, label: str,
                   start: dt.date, stop: dt.date, epoch: str, s: requests.Session, sleep: float) -> None:
    todo = [(name, cmd) for name, cmd in targets if name not in table.columns or table[name].isna().any()]
    print(f"  {label}: {len(targets) - len(todo)} done, {len(todo)} to fetch")
    for i, (name, cmd) in enumerate(todo):
        try:
            df = horizons_longitudes(cmd, start, stop, epoch, s).set_index("date")
            table[name] = df["lon"].reindex(table.index)
        except RuntimeError as exc:
            print(f"  {name}: {exc}", file=sys.stderr)
            table[name] = np.nan
        time.sleep(sleep)
        if (i + 1) % 25 == 0 or i + 1 == len(todo):
            table.to_csv(path, float_format="%.4f")
            print(f"  {label} {i + 1}/{len(todo)}")
    table.to_csv(path, float_format="%.4f")


def assert_frame(refs: pd.DataFrame) -> None:
    """The Sun must cross 0° between the rows bracketing the March 2027 equinox (tropical frame of date)."""
    if "2027-03-20" in refs.index and "2027-03-21" in refs.index:
        a, b = float(refs.loc["2027-03-20", "Sun"]), float(refs.loc["2027-03-21", "Sun"])
        if not (a > 358.5 and b < 1.5):
            raise AssertionError(f"frame check failed: Sun at {a:.3f} on 2027-03-20 and {b:.3f} on 2027-03-21")


def check(cfg: dict[str, Any], root: Path, out_dir: Path) -> int:
    """Verify the built tables: date index, frame, node motion, missing bodies, unresolved names."""
    dates = [d.isoformat() for d in C.window_dates(cfg)]
    ok = True
    refs = pd.read_csv(out_dir / "references.csv", index_col="date")
    named = pd.read_csv(out_dir / "named.csv", index_col="date")
    unnamed = pd.read_csv(out_dir / "unnamed.csv", index_col="date")
    for nm, df in (("references", refs), ("named", named), ("unnamed", unnamed)):
        if list(df.index) != dates:
            print(f"FAIL {nm}.csv: date index does not match the registered window")
            ok = False
    try:
        assert_frame(refs)
        print("OK   frame: the Sun crosses 0° at the March 2027 equinox (tropical, of date)")
    except AssertionError as exc:
        print(f"FAIL {exc}")
        ok = False
    dr = ((refs["Rahu"].iloc[-1] - refs["Rahu"].iloc[0] + 180) % 360 - 180) if len(refs) > 1 else 0
    yrs = (len(refs) - 1) / 365.25
    print(f"{'OK  ' if -20.5 < dr / yrs < -18.5 else 'FAIL'} Rahu mean motion {dr / yrs:+.2f} deg/yr (expect ≈ -19.3)")
    sun = (refs["Sun"].diff().dropna() + 180) % 360 - 180
    print(f"{'OK  ' if 0.95 < sun.mean() < 1.02 else 'FAIL'} Sun mean daily motion {sun.mean():.4f} deg/day")
    verified = C.verified_names(root)
    missing = [n for n in verified if n not in named.columns]
    nan_cols = [c for c in named.columns if named[c].isna().any()]
    print(f"{'OK  ' if not missing else 'WARN'} named bodies: {len(named.columns)} columns, {len(missing)} verified names absent"
          + (f" (e.g. {missing[:5]})" if missing else ""))
    print(f"{'OK  ' if not nan_cols else 'WARN'} named bodies with gaps: {len(nan_cols)}" + (f" {nan_cols[:5]}" if nan_cols else ""))
    unn_nan = [c for c in unnamed.columns if unnamed[c].isna().any()]
    print(f"{'OK  ' if len(unnamed.columns) - len(unn_nan) >= len(verified) else 'FAIL'} unnamed pool: "
          f"{len(unnamed.columns) - len(unn_nan)} complete of {len(unnamed.columns)} (need ≥ {len(verified)})")
    ids_path = root / "data" / "body_ids.csv"
    if ids_path.exists():
        ids = pd.read_csv(ids_path)
        bad = ids[~ids["status"].astype(str).str.startswith("resolved")]
        inexact = ids[ids["status"].astype(str).str.startswith("resolved") & (ids["exact"] == False)]  # noqa: E712
        print(f"{'OK  ' if bad.empty else 'WARN'} body_ids.csv: {len(bad)} unresolved/ambiguous names"
              + (f" — fix by hand: {bad['name'].tolist()[:10]}" if not bad.empty else ""))
        print(f"{'OK  ' if inexact.empty else 'WARN'} body_ids.csv: {len(inexact)} resolved to a non-identical name — review"
              + (f": {inexact['name'].tolist()[:10]}" if not inexact.empty else ""))
    # daily motion sanity for asteroids: median |Δlon| should be a few tenths of a degree
    med = np.nanmedian(np.abs(((named.diff().iloc[1:] + 180) % 360) - 180).to_numpy())
    print(f"{'OK  ' if 0.05 < med < 0.6 else 'WARN'} median daily motion of named bodies {med:.3f} deg/day")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the registered ephemeris tables")
    ap.add_argument("cmd", choices=["resolve", "build", "check"])
    ap.add_argument("--root", default=str(C.ROOT))
    ap.add_argument("--epoch", default=None, help="HH:MM UTC (default: registered epoch)")
    ap.add_argument("--out", default=None, help="output directory (default: data/ephemeris)")
    ap.add_argument("--sleep", type=float, default=1.0, help="seconds between per-name SBDB requests (resolve)")
    ap.add_argument("--no-bulk", action="store_true", help="skip the one-request bulk table; per-name lookups only")
    args = ap.parse_args(argv)
    cfg = C.load_config()
    root = Path(args.root)
    if args.cmd == "resolve":
        print("resolver: bulk table first, per-name lookups for the remainder (resumable)")
        df = resolve_all(C.verified_names(root), root / "data" / "body_ids.csv", sleep=args.sleep,
                         bulk=not args.no_bulk)
        print(df["status"].value_counts().to_string())
        bad = df[~df["status"].astype(str).str.startswith("resolved")]
        if not bad.empty:
            print(f"{len(bad)} names not resolved; re-run 'resolve' to retry http-* rows, "
                  f"fix 'ambiguous'/'not-found' rows by hand in data/body_ids.csv")
        return 0
    epoch = args.epoch or cfg["study"]["ephemeris_epoch_utc"]
    out = Path(args.out) if args.out else root / "data" / "ephemeris"
    if args.cmd == "check":
        return check(cfg, root, out)
    build(cfg, root, out, epoch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
