"""Estimators and null models (PREREGISTRATION.md §7).

Layout: every array is (B bodies × T days) with time as the contiguous last
axis — this makes the per-body circular roll of the compound null and the
kernel dot products an order of magnitude faster than the (T × B) layout.
Outcome series ``c`` are already L2-normalised per body; ``theta`` are
separation angles in degrees and ``L`` tropical longitudes.

Registered statistics:

    V_{R,n}   harmonic V-statistic          Σ c cos(nθ) / Σ c
    D_R       aspect concentration          Σ_n V_{R,n} over the nine aspect harmonics
    T         FPOA–Libra projection         Σ_L w(L) cos(L − 180°) on the centred binned wave
    ACF       circular autocorrelation      at the eight aspect lags, binned wave
    Δ_pol, G_elem, G_gen, Y, M, F           Block II differential statistics

Nulls:

    compound  permute body ↔ series, roll each series in time
    unnamed   permute body ↔ series, replace orbits by unnamed asteroids
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .angles import bins, harmonic_kernel, phase_locked_kernel

N_WAVE = 360


# ------------------------------------------------------------ normalisation
def l2_normalize_rows(c: np.ndarray, norm: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Divide each body's row by its L2 norm (or by a supplied parent norm). Zero rows stay zero."""
    c = np.ascontiguousarray(c, dtype=np.float64)
    if norm is None:
        norm = np.sqrt((c ** 2).sum(axis=1))
    norm = np.where(norm > 0, norm, 1.0)
    return np.ascontiguousarray(c / norm[:, None]), norm


# --------------------------------------------------------------- estimators
def v_stat(c: np.ndarray, kernel: np.ndarray) -> float:
    tot = float(c.sum())
    if tot <= 0:
        return 0.0
    return float(np.dot(c.ravel(), kernel.ravel()) / tot)


def harmonic_v(c: np.ndarray, theta: np.ndarray, n: int) -> float:
    return v_stat(np.ascontiguousarray(c, dtype=np.float64), np.cos(n * np.deg2rad(theta)))


def harmonic_amplitude(c: np.ndarray, theta: np.ndarray, n: int) -> tuple[float, float]:
    """Phase-free amplitude A_n and peak phase (degrees) of the n-th harmonic."""
    tot = float(c.sum())
    if tot <= 0:
        return 0.0, float("nan")
    th = n * np.deg2rad(theta)
    a = float((c * np.cos(th)).sum() / tot)
    b = float((c * np.sin(th)).sum() / tot)
    return float(np.hypot(a, b)), float((np.degrees(np.arctan2(b, a)) / n) % (360.0 / n))


def wave_from_bins(c: np.ndarray, bins_flat: np.ndarray, counts: np.ndarray, centre: bool = True) -> np.ndarray:
    wsum = np.bincount(bins_flat, weights=c.ravel(), minlength=N_WAVE)
    w = wsum / counts
    return w - w.mean() if centre else w


def binned_wave(c: np.ndarray, theta: np.ndarray, centre: bool = True) -> np.ndarray:
    """Mean normalised value per integer-degree bin of theta (360 bins)."""
    lon = bins(theta).ravel()
    counts = np.maximum(np.bincount(lon, minlength=N_WAVE).astype(float), 1.0)
    return wave_from_bins(np.asarray(c, dtype=np.float64), lon, counts, centre)


def first_harmonic(w: np.ndarray) -> dict[str, float]:
    L = np.deg2rad(np.arange(N_WAVE))
    a = float((w * np.cos(L)).sum())
    b = float((w * np.sin(L)).sum())
    return {"a": a, "b": b, "amplitude": 2.0 * float(np.hypot(a, b)) / N_WAVE,
            "peak_deg": float(np.degrees(np.arctan2(b, a)) % 360.0)}


_COS_L = np.cos(np.deg2rad(np.arange(N_WAVE)))


def t_libra(w: np.ndarray) -> float:
    """T = Σ_L w(L) cos(L − 180°) = −Σ_L w(L) cos L  (FPOA audit statistic)."""
    return -float(np.dot(w, _COS_L))


def circular_acf(w: np.ndarray, lags: list[int]) -> np.ndarray:
    """Biased circular ACF via Wiener–Khinchin, exactly as in the first study."""
    w = np.asarray(w, dtype=np.float64)
    x = w - w.mean()
    var = float((x * x).sum())
    scale = float((w * w).sum())
    if var <= 1e-20 * max(scale, 1e-300):
        return np.zeros(len(lags))
    F = np.fft.rfft(x)
    acf = np.fft.irfft(F * np.conj(F), n=len(x)) / var
    return acf[np.asarray(lags, dtype=int)]


def modulation_percent(w_uncentred: np.ndarray) -> float:
    """Amplitude of the first harmonic as a percentage of the all-angle mean."""
    m = float(w_uncentred.mean())
    if m <= 0:
        return float("nan")
    return 100.0 * first_harmonic(w_uncentred - m)["amplitude"] / m


# --------------------------------------------------------------- kernels
@dataclass
class Kernels:
    """Precomputed kernels for one set of orbits (named bodies or the unnamed pool), (B × T) layout."""
    refs: list[str]
    theta: dict[str, np.ndarray]
    K_D: dict[str, np.ndarray] = field(default_factory=dict)
    K_harm: dict[str, np.ndarray] = field(default_factory=dict)
    K_chal: dict[str, np.ndarray] = field(default_factory=dict)
    bins: dict[str, np.ndarray] = field(default_factory=dict)       # (B × T) integer-degree bins
    counts: dict[str, np.ndarray] = field(default_factory=dict)     # bin occupancy (360,)
    L: np.ndarray | None = None
    K_sign: dict[str, np.ndarray] = field(default_factory=dict)

    n_bodies: int = 0

    @classmethod
    def build(cls, refs: list[str], theta: dict[str, np.ndarray], cfg: dict[str, Any], L: np.ndarray,
              sign_L: np.ndarray | None = None, dtype=np.float64, keep_theta: bool = True) -> "Kernels":
        """Build kernels from (B × T) separations. ``keep_theta=False`` drops the angle tables
        after use (the unnamed pool needs only its kernels); ``dtype=np.float32`` halves memory."""
        th = {r: np.ascontiguousarray(theta[r], dtype=np.float64) for r in theta}
        k = cls(refs=refs, theta={}, L=np.ascontiguousarray(L, dtype=np.float64))
        k.n_bodies = int(k.L.shape[0])
        H = cfg["harmonics"]
        for r in refs:
            k.K_D[r] = harmonic_kernel(th[r], H, dtype)
            k.K_harm[r] = harmonic_kernel(th[r], cfg["harmonious_harmonics"], dtype)
            k.K_chal[r] = harmonic_kernel(th[r], cfg["challenging_harmonics"], dtype)
        for r in th:
            b = bins(th[r])
            k.bins[r] = b
            k.counts[r] = np.maximum(np.bincount(b.ravel(), minlength=N_WAVE).astype(float), 1.0)
        sL = k.L if sign_L is None else np.ascontiguousarray(sign_L, dtype=np.float64)
        sg = cfg["signs"]
        k.K_sign["yang"] = phase_locked_kernel(sL, 6, sg["yang_centre_deg"], dtype)
        for m, phi in sg["modality_centres_deg"].items():
            k.K_sign[m] = phase_locked_kernel(sL, 4, phi, dtype)
        for e, phi in sg["element_centres_deg"].items():
            k.K_sign["sign_" + e] = phase_locked_kernel(sL, 3, phi, dtype)
        if keep_theta:
            k.theta = th
        return k

    def subset(self, rows: np.ndarray) -> "Kernels":
        """Row (body) subset (materialised). The Monte Carlo loop uses lazy row selection instead."""
        k = Kernels(refs=self.refs, theta={r: self.theta[r][rows] for r in self.theta},
                    L=None if self.L is None else self.L[rows])
        k.n_bodies = int(len(rows))
        k.K_D = {r: self.K_D[r][rows] for r in self.refs}
        k.K_harm = {r: self.K_harm[r][rows] for r in self.refs}
        k.K_chal = {r: self.K_chal[r][rows] for r in self.refs}
        k.bins = {r: self.bins[r][rows] for r in self.bins}
        k.counts = {r: np.maximum(np.bincount(k.bins[r].ravel(), minlength=N_WAVE).astype(float), 1.0)
                    for r in k.bins}
        k.K_sign = {n: v[rows] for n, v in self.K_sign.items()}
        return k


# ------------------------------------------------------------- statistics
KERNEL_KEYS_DOC = """Kernel keys used by the statistics: ('D', ref), ('harm', ref), ('chal', ref), ('sign', name)."""


def kernel_array(K: Kernels, key: tuple[str, str]) -> np.ndarray:
    kind, name = key
    if kind == "D":
        return K.K_D[name]
    if kind == "harm":
        return K.K_harm[name]
    if kind == "chal":
        return K.K_chal[name]
    if kind == "sign":
        return K.K_sign[name]
    raise KeyError(key)


def required_pairs(series_keys: set[str], K: Kernels, planets: dict[str, dict[str, Any]]) -> list[tuple[str, tuple[str, str]]]:
    """Every (series, kernel) dot product the registered statistics consume."""
    pairs: list[tuple[str, tuple[str, str]]] = [("N", ("D", r)) for r in K.refs]
    if {"N_pos", "N_neg"} <= series_keys:
        for r in K.refs:
            for sk in ("N_pos", "N_neg"):
                pairs += [(sk, ("harm", r)), (sk, ("chal", r))]
    elems = ["space", "air", "fire", "water", "earth"]
    if all(f"N_{e}" in series_keys for e in elems):
        for p, attr in planets.items():
            e = attr.get("element")
            if e and p in K.K_D:
                pairs += [(f"N_{e}", ("D", p))]
                if ("N", ("D", p)) not in pairs:
                    pairs.append(("N", ("D", p)))
    if {"N_male", "N_female"} <= series_keys:
        for p, attr in planets.items():
            if attr.get("gender") in ("male", "female") and p in K.K_D:
                pairs += [("N_male", ("D", p)), ("N_female", ("D", p))]
    if {"N_yang", "N_yin"} <= series_keys:
        pairs += [("N_yang", ("sign", "yang")), ("N_yin", ("sign", "yang"))]
    if {"N_cardinal", "N_fixed", "N_mutable"} <= series_keys:
        pairs += [(f"N_{m}", ("sign", m)) for m in ("cardinal", "fixed", "mutable")]
    if all(f"N_{e}" in series_keys for e in ("fire", "earth", "air", "water")):
        pairs += [(f"N_{e}", ("sign", "sign_" + e)) for e in ("fire", "earth", "air", "water")]
    seen, out = set(), []
    for pr in pairs:
        if pr not in seen:
            seen.add(pr)
            out.append(pr)
    return out


def statistics_from_primitives(dot, tot, wave, refs: list[str], series_keys: set[str],
                               planets: dict[str, dict[str, Any]], acf_lags: list[int]) -> dict[str, float]:
    """The registered statistics expressed through three primitives:
    dot(series_key, kernel_key) = Σ c·K ; tot(series_key) = Σ c ; wave(series_key, ref) = centred binned wave."""
    def v(sk: str, kk: tuple[str, str]) -> float:
        t = tot(sk)
        return dot(sk, kk) / t if t > 0 else 0.0

    out: dict[str, float] = {}
    D = 0.0
    for r in refs:
        d = v("N", ("D", r))
        out[f"D_{r}"] = d
        D += d
    out["D"] = D
    out["T_FPOA"] = t_libra(wave("N", "FPOA"))
    acf_omni = 0.0
    for r in refs:
        j = float((circular_acf(wave("N", r), acf_lags) ** 2).sum())
        out[f"ACF2_{r}"] = j
        acf_omni += j
    out["ACF2"] = acf_omni
    if {"N_pos", "N_neg"} <= series_keys:
        out["Delta_pol"] = sum(v("N_pos", ("harm", r)) - v("N_neg", ("harm", r))
                               - v("N_pos", ("chal", r)) + v("N_neg", ("chal", r)) for r in refs)
    elems = ["space", "air", "fire", "water", "earth"]
    if all(f"N_{e}" in series_keys for e in elems):
        g = 0.0
        for p, attr in planets.items():
            e = attr.get("element")
            if e and p in refs:
                own, kk = f"N_{e}", ("D", p)
                tot_n, tot_o = tot("N"), tot(own)
                v_own = dot(own, kk) / tot_o if tot_o > 0 else 0.0
                v_oth = (dot("N", kk) - dot(own, kk)) / (tot_n - tot_o) if (tot_n - tot_o) > 0 else 0.0
                g += v_own - v_oth
        out["G_elem"] = g
    if {"N_male", "N_female"} <= series_keys:
        g = 0.0
        for p, attr in planets.items():
            gd = attr.get("gender")
            if gd in ("male", "female") and p in refs:
                diff = v("N_male", ("D", p)) - v("N_female", ("D", p))
                g += diff if gd == "male" else -diff
        out["G_gen"] = g
    if {"N_yang", "N_yin"} <= series_keys:
        out["Y"] = v("N_yang", ("sign", "yang")) - v("N_yin", ("sign", "yang"))
    if {"N_cardinal", "N_fixed", "N_mutable"} <= series_keys:
        out["M"] = sum(v(f"N_{m}", ("sign", m)) for m in ("cardinal", "fixed", "mutable"))
    if all(f"N_{e}" in series_keys for e in ("fire", "earth", "air", "water")):
        out["F"] = sum(v(f"N_{e}", ("sign", "sign_" + e)) for e in ("fire", "earth", "air", "water"))
    return out


def registered_statistics(series: dict[str, np.ndarray], K: Kernels, cfg: dict[str, Any],
                          planets: dict[str, dict[str, Any]], acf_lags: list[int],
                          occupied_rows: np.ndarray | None = None) -> dict[str, float]:
    """Every registered statistic for one (series, orbits) configuration, computed directly.

    ``occupied_rows`` restricts the bin occupancy of the binned waves when the series are
    zero-padded onto a larger pool of orbits (unnamed null, materialised form)."""
    totals = {k: float(v.sum()) for k, v in series.items()}

    def dot(sk, kk):
        return float(np.dot(series[sk].ravel(), kernel_array(K, kk).ravel()))

    def tot(sk):
        return totals[sk]

    def wave(sk, r):
        c = series[sk]
        if occupied_rows is None:
            return wave_from_bins(c, K.bins[r].ravel(), K.counts[r])
        cnt = np.maximum(np.bincount(K.bins[r][occupied_rows].ravel(), minlength=N_WAVE).astype(float), 1.0)
        return wave_from_bins(c, K.bins[r].ravel(), cnt)

    return statistics_from_primitives(dot, tot, wave, K.refs, set(series.keys()), planets, acf_lags)


# --------------------------------------------------------------- nulls
def stack_series(series: dict[str, np.ndarray]) -> tuple[list[str], np.ndarray]:
    keys = list(series.keys())
    return keys, np.ascontiguousarray(np.stack([series[k] for k in keys], axis=0))


def compound_draw(stack: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Permute which body carries which series, then roll each series by a random shift in time.

    ``stack`` is (S series × B bodies × T days); all series of a body move together.
    Implemented as one flat gather: element (b, t) of the result is element (perm[b], (t − shift[b]) mod T)."""
    S, B, T = stack.shape
    perm = rng.permutation(B)
    shift = rng.integers(0, T, size=B)
    idx = (np.arange(T)[None, :] - shift[:, None]) % T                  # (B × T)
    flat = (perm[:, None] * T + idx).ravel()
    return np.take(stack.reshape(S, B * T), flat, axis=1).reshape(S, B, T)


class UnnamedNull:
    """The unnamed-asteroid null with the body-by-orbit dot products precomputed.

    For every (series, kernel) pair the statistics consume, M = C · Kᵀ (B × P) holds the
    dot product of each real series with each pool orbit's kernel. A replicate then costs
    one fancy-indexed sum per pair, plus the binned waves of N on the drawn orbits."""

    def __init__(self, series: dict[str, np.ndarray], pool: Kernels, planets: dict[str, dict[str, Any]],
                 acf_lags: list[int], free_pool_kernels: bool = True):
        self.refs = pool.refs
        self.series_keys = set(series.keys())
        self.planets = planets
        self.acf_lags = acf_lags
        self.P = pool.n_bodies
        self.B, self.T = series["N"].shape
        self.tot = {k: float(v.sum()) for k, v in series.items()}
        self.M: dict[tuple[str, tuple[str, str]], np.ndarray] = {}
        for sk, kk in required_pairs(self.series_keys, pool, planets):
            self.M[(sk, kk)] = series[sk] @ kernel_array(pool, kk).T            # (B × P)
        self.bins = {r: pool.bins[r] for r in pool.bins}
        self.N = series["N"]
        if free_pool_kernels:
            pool.K_D.clear(); pool.K_harm.clear(); pool.K_chal.clear(); pool.K_sign.clear()
        self._padded = np.zeros((self.P, self.T))

    def draw(self, rng: np.random.Generator) -> dict[str, float]:
        rows = rng.choice(self.P, size=self.B, replace=False)
        perm = rng.permutation(self.B)

        def dot(sk, kk):
            return float(self.M[(sk, kk)][perm, rows].sum())

        def tot(sk):
            return self.tot[sk]

        padded = self._padded
        padded[:] = 0.0
        padded[rows] = self.N[perm]

        def wave(sk, r):
            b = self.bins[r]
            cnt = np.maximum(np.bincount(b[rows].ravel(), minlength=N_WAVE).astype(float), 1.0)
            return wave_from_bins(padded, b.ravel(), cnt)

        return statistics_from_primitives(dot, tot, wave, self.refs, self.series_keys, self.planets, self.acf_lags)


def unnamed_draw(stack: np.ndarray, pool: Kernels, rng: np.random.Generator,
                 padded: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Materialised form of one unnamed-null replicate (used by tests to check ``UnnamedNull``)."""
    S, B, T = stack.shape
    P = pool.n_bodies
    rows = rng.choice(P, size=B, replace=False)
    perm = rng.permutation(B)
    if padded is None or padded.shape != (S, P, T):
        padded = np.zeros((S, P, T), dtype=stack.dtype)
    else:
        padded[:] = 0.0
    padded[:, rows, :] = stack[:, perm, :]
    return padded, rows


def monte_carlo(series: dict[str, np.ndarray], K_named: Kernels, K_unnamed: Kernels, cfg: dict[str, Any],
                planets: dict[str, dict[str, Any]], acf_lags: list[int], n_rep: int, seed: int,
                progress=None) -> dict[str, dict[str, np.ndarray]]:
    """Null distributions of every registered statistic under both nulls.

    Note: the unnamed pool's kernels are released after the dot-product matrices are built."""
    keys, stack = stack_series(series)
    rng = np.random.default_rng(seed)
    obs = registered_statistics(series, K_named, cfg, planets, acf_lags)
    names = list(obs.keys())
    out = {"compound": {n: np.empty(n_rep) for n in names}, "unnamed": {n: np.empty(n_rep) for n in names}}
    unnamed = UnnamedNull(series, K_unnamed, planets, acf_lags)
    for i in range(n_rep):
        cs = compound_draw(stack, rng)
        s_c = registered_statistics(dict(zip(keys, cs)), K_named, cfg, planets, acf_lags)
        s_u = unnamed.draw(rng)
        for n in names:
            out["compound"][n][i] = s_c[n]
            out["unnamed"][n][i] = s_u[n]
        if progress and (i + 1) % max(1, n_rep // 10) == 0:
            progress(i + 1, n_rep)
    return out


def summarise(obs: float, null: np.ndarray) -> dict[str, float]:
    n = len(null)
    ge = int((null >= obs).sum())
    p = (1 + ge) / (1 + n)
    sd = float(null.std(ddof=0))
    d = float((obs - null.mean()) / sd) if sd > 0 else float("nan")
    return {"observed": float(obs), "null_mean": float(null.mean()), "null_sd": sd,
            "p_one_sided": float(p), "d": d, "bf_pragmatic": float(1.0 / (2.0 * p))}
