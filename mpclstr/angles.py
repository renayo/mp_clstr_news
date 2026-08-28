"""Separations, harmonics and sign membership (PREREGISTRATION.md §3.4, §6).

All longitudes are degrees in [0, 360). ``theta = (body - reference) mod 360``
is the signed separation; the integer bin is ``floor(theta + 0.5) mod 360``.
"""
from __future__ import annotations

import numpy as np

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
         "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
MODALITY = ["cardinal", "fixed", "mutable"] * 4              # by sign index
ELEMENT = ["fire", "earth", "air", "water"] * 3              # by sign index
POLARITY = ["yang", "yin"] * 6                               # odd signs (index even) are yang


def separation(lon_body: np.ndarray, lon_ref: np.ndarray) -> np.ndarray:
    """(B×T) body longitudes minus (T,) reference longitudes, mod 360 (time is the last axis)."""
    lon_ref = np.asarray(lon_ref, dtype=float)
    return (np.asarray(lon_body, dtype=float) - lon_ref[None, :]) % 360.0


def ketu_from_rahu(rahu: np.ndarray) -> np.ndarray:
    return (np.asarray(rahu, dtype=float) + 180.0) % 360.0


def bins(theta: np.ndarray) -> np.ndarray:
    return (np.floor(np.asarray(theta, dtype=float) + 0.5).astype(np.int64)) % 360


def sidereal(lon: np.ndarray, ayanamsa_deg: float) -> np.ndarray:
    return (np.asarray(lon, dtype=float) - ayanamsa_deg) % 360.0


def sign_index(lon: np.ndarray) -> np.ndarray:
    return (np.floor(np.asarray(lon, dtype=float) / 30.0).astype(np.int64)) % 12


def sign_polarity(lon: np.ndarray) -> np.ndarray:
    """1 for yang (odd signs: Aries, Gemini, ...), 0 for yin."""
    return 1 - (sign_index(lon) % 2)


def sign_modality(lon: np.ndarray) -> np.ndarray:
    """0 cardinal, 1 fixed, 2 mutable."""
    return sign_index(lon) % 3


def sign_element(lon: np.ndarray) -> np.ndarray:
    """0 fire, 1 earth, 2 air, 3 water."""
    return sign_index(lon) % 4


def harmonic_kernel(theta: np.ndarray, harmonics: list[int], dtype=np.float32) -> np.ndarray:
    """Σ_n cos(n·theta) over the given harmonics — the kernel of the directional statistic D."""
    th = np.deg2rad(np.asarray(theta, dtype=float))
    out = np.zeros(th.shape, dtype=np.float64)
    for n in harmonics:
        out += np.cos(n * th)
    return out.astype(dtype)


def phase_locked_kernel(lon: np.ndarray, harmonic: int, centre_deg: float, dtype=np.float32) -> np.ndarray:
    """cos(h·(L − φ)): +1 at the centres of the h-fold family anchored at φ."""
    return np.cos(harmonic * np.deg2rad(np.asarray(lon, dtype=float) - centre_deg)).astype(dtype)
