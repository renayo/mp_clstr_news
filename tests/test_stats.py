import numpy as np

from mpclstr.angles import (bins, harmonic_kernel, phase_locked_kernel, separation, sign_element, sign_index,
                            sign_modality, sign_polarity)
from mpclstr.stats import (Kernels, UnnamedNull, binned_wave, circular_acf, compound_draw, harmonic_v,
                           l2_normalize_rows, monte_carlo, registered_statistics, summarise, t_libra, unnamed_draw,
                           v_stat)


def test_angles_basics():
    L = np.array([[10.0], [350.0]])            # two bodies, one day
    r = np.array([20.0])
    th = separation(L, r)
    assert np.allclose(th, [[350.0], [330.0]])
    assert bins(np.array([359.6, 0.4, 0.5, 89.49])).tolist() == [0, 0, 1, 89]
    assert sign_index(np.array([0, 29.9, 30, 359.9])).tolist() == [0, 0, 1, 11]
    assert sign_polarity(np.array([15, 45])).tolist() == [1, 0]                # Aries yang, Taurus yin
    assert sign_modality(np.array([15, 45, 75, 105])).tolist() == [0, 1, 2, 0]  # cardinal fixed mutable cardinal
    assert sign_element(np.array([15, 45, 75, 105])).tolist() == [0, 1, 2, 3]  # fire earth air water


def test_ketu_identities():
    rng = np.random.default_rng(0)
    th = rng.uniform(0, 360, (50, 40))
    c = rng.exponential(1.0, (50, 40))
    for n in [1, 2, 3, 4, 5, 6, 7, 8, 12]:
        vr = harmonic_v(c, th, n)
        vk = harmonic_v(c, (th + 180) % 360, n)
        assert np.isclose(vk, (-1) ** n * vr)
    lags = [30, 45, 51, 60, 72, 90, 120, 180]
    assert np.allclose(circular_acf(binned_wave(c, th), lags), circular_acf(binned_wave(c, (th + 180) % 360), lags))


def test_harmonic_v_recovers_planted_signal():
    rng = np.random.default_rng(1)
    th = rng.uniform(0, 360, (400, 200))
    c = 1.0 + 0.5 * np.cos(4 * np.deg2rad(th))          # square-family modulation only
    assert harmonic_v(c, th, 4) > 0.2
    for n in [1, 2, 3, 5, 6, 7, 8, 12]:
        assert abs(harmonic_v(c, th, n)) < 0.03
    K = harmonic_kernel(th, [1, 2, 3, 4, 5, 6, 7, 8, 12]).astype(float)
    assert np.isclose(v_stat(c, K), sum(harmonic_v(c, th, n) for n in [1, 2, 3, 4, 5, 6, 7, 8, 12]), atol=1e-5)


def test_t_libra_sign_and_first_harmonic():
    L = np.arange(360)
    w = np.cos(np.deg2rad(L - 180))                      # peak at Libra
    assert t_libra(w) > 0
    assert t_libra(-w) < 0


def test_modality_statistic_cancels_common_fourth_harmonic():
    rng = np.random.default_rng(2)
    L = rng.uniform(0, 360, (300, 100))
    common = 1.0 + 0.6 * np.cos(4 * np.deg2rad(L - 33.0))  # a 4th harmonic shared by all classes
    parts = {m: common * f for m, f in (("cardinal", 0.2), ("fixed", 0.3), ("mutable", 0.5))}
    M = sum(v_stat(parts[m], phase_locked_kernel(L, 4, phi).astype(float))
            for m, phi in (("cardinal", 15.0), ("fixed", 45.0), ("mutable", 75.0)))
    assert abs(M) < 1e-6


def test_polarity_statistic_detects_sign_structure():
    rng = np.random.default_rng(3)
    L = rng.uniform(0, 360, (300, 100))
    yang_sign = (np.floor(L / 30) % 2 == 0).astype(float)
    N_yang = 1.0 + 0.8 * yang_sign
    N_yin = 1.0 + 0.8 * (1 - yang_sign)
    K = phase_locked_kernel(L, 6, 15.0).astype(float)
    assert v_stat(N_yang, K) - v_stat(N_yin, K) > 0.1


def test_compound_draw_preserves_series_and_rolls():
    rng = np.random.default_rng(4)
    stack = rng.poisson(3.0, (2, 7, 20)).astype(float)       # 2 series × 7 bodies × 20 days
    out = compound_draw(stack, rng)
    assert out.shape == stack.shape
    # every original body row reappears (as a circular shift) exactly once, for both series jointly
    used = set()
    for b in range(7):
        found = None
        for j in range(7):
            if j in used:
                continue
            for s in range(20):
                if np.allclose(np.roll(stack[:, j, :], s, axis=1), out[:, b, :]):
                    found = j
                    break
            if found is not None:
                break
        assert found is not None
        used.add(found)


def _toy(cfg, plant=0.0, seed=0, T=120, B=30, P=40):
    rng = np.random.default_rng(seed)
    t = np.arange(T)
    L = (rng.uniform(0, 360, B)[:, None] + rng.uniform(0.15, 0.3, B)[:, None] * t[None, :]) % 360   # (B × T)
    Lu = (rng.uniform(0, 360, P)[:, None] + rng.uniform(0.15, 0.3, P)[:, None] * t[None, :]) % 360
    refs = {"FPOA": np.zeros(T)}
    for r in cfg["reference_points"]:
        if r["name"] != "FPOA":
            refs[r["name"]] = (rng.uniform(0, 360) + rng.uniform(0.01, 1.0) * t) % 360
    refs["Ketu"] = (refs["Rahu"] + 180) % 360
    indep = [r["name"] for r in cfg["reference_points"] if r["independent"]]
    thn = {r: separation(L, refs[r]) for r in refs}
    thu = {r: separation(Lu, refs[r]) for r in refs}
    N = rng.poisson(2.0, (B, T)).astype(float)
    if plant:
        N = np.round(N * np.clip(1 + plant * harmonic_kernel(thn["Sun"], cfg["harmonics"]).astype(float), 0, None))
    Nn, norm = l2_normalize_rows(N)
    series = {"N": Nn}
    p = rng.dirichlet([1, 1, 1], size=(B, T))
    series["N_pos"], series["N_neg"], series["N_neu"] = (l2_normalize_rows(N * p[:, :, i], norm)[0] for i in range(3))
    for lab in ("space", "air", "fire", "water", "earth"):
        series[f"N_{lab}"] = Nn / 5
    series["N_male"], series["N_female"] = Nn * 0.4, Nn * 0.3
    series["N_yang"], series["N_yin"] = Nn * 0.5, Nn * 0.5
    series["N_cardinal"], series["N_fixed"], series["N_mutable"] = Nn / 3, Nn / 3, Nn / 3
    Kn = Kernels.build(indep, thn, cfg, L)
    Ku = Kernels.build(indep, thu, cfg, Lu)
    planets = {r["name"]: r for r in cfg["reference_points"] if r["kind"] == "major"}
    return series, Kn, Ku, planets


def test_registered_statistics_shape_and_null_run(cfg):
    series, Kn, Ku, planets = _toy(cfg)
    obs = registered_statistics(series, Kn, cfg, planets, cfg["acf_lags"])
    for k in ("D", "T_FPOA", "ACF2", "Delta_pol", "G_elem", "G_gen", "Y", "M", "F", "D_Sun", "ACF2_Moon"):
        assert k in obs
    assert "D_Ketu" not in obs                      # Ketu is derived, not an independent test
    nulls = monte_carlo(series, Kn, Ku, cfg, planets, cfg["acf_lags"], n_rep=25, seed=1)
    assert nulls["compound"]["D"].shape == (25,) and nulls["unnamed"]["D"].shape == (25,)
    s = summarise(obs["D"], nulls["compound"]["D"])
    assert 0 < s["p_one_sided"] <= 1
    # with the classes summing to N, G_elem is exactly zero when every class is N/5
    assert abs(obs["G_elem"]) < 1e-9


def test_planted_sun_signal_is_detected(cfg):
    series, Kn, Ku, planets = _toy(cfg, plant=0.5, seed=5, T=200, B=60, P=80)
    obs = registered_statistics(series, Kn, cfg, planets, cfg["acf_lags"])
    nulls = monte_carlo(series, Kn, Ku, cfg, planets, cfg["acf_lags"], n_rep=60, seed=2)
    s_sun = summarise(obs["D_Sun"], nulls["compound"]["D_Sun"])
    s_moon = summarise(obs["D_Moon"], nulls["compound"]["D_Moon"])
    assert s_sun["p_one_sided"] < 0.05 and s_sun["d"] > 3
    assert s_moon["p_one_sided"] > 0.05


def test_unnamed_draw_shapes(cfg):
    series, Kn, Ku, planets = _toy(cfg)
    keys = list(series)
    stack = np.stack([series[k] for k in keys])
    padded, rows = unnamed_draw(stack, Ku, np.random.default_rng(0))
    P = Ku.n_bodies
    assert padded.shape == (stack.shape[0], P, stack.shape[2]) and len(set(rows.tolist())) == stack.shape[1]
    # scattered form on the full pool == materialised subset form
    scat = registered_statistics(dict(zip(keys, padded)), Ku, cfg, planets, cfg["acf_lags"], occupied_rows=rows)
    K2 = Ku.subset(rows)
    mat = registered_statistics(dict(zip(keys, padded[:, rows, :])), K2, cfg, planets, cfg["acf_lags"])
    for k in scat:
        assert np.isclose(scat[k], mat[k]), k
    # the precomputed-dot-product form reproduces the direct form for the same draw
    un = UnnamedNull(series, Ku, planets, cfg["acf_lags"], free_pool_kernels=False)
    rng1, rng2 = np.random.default_rng(9), np.random.default_rng(9)
    fast = un.draw(rng1)
    padded2, rows2 = unnamed_draw(stack, Ku, rng2)      # same rng consumption order: rows, then perm
    direct = registered_statistics(dict(zip(keys, padded2)), Ku, cfg, planets, cfg["acf_lags"], occupied_rows=rows2)
    for k in fast:
        assert np.isclose(fast[k], direct[k], rtol=1e-6, atol=1e-9), k
