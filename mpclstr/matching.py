"""The name-matching protocol (PREREGISTRATION.md §4.5).

A text matches a name when it contains the name as a whole phrase after both
sides are normalised: Unicode NFKD, combining marks removed, case folded,
typographic quotes and dashes mapped to ASCII. Inside a name, a space, hyphen
or apostrophe matches an optional space, hyphen or apostrophe. The match must
start and end at a boundary between a letter-or-digit and anything else, so
"Tyson's" matches "Tyson" and "Tysons" does not. No stemming, no aliases.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

_QUOTES = dict.fromkeys(map(ord, "‘’‚‛′ʼʹ`´"), "'")
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−­"), "-")
_SEP_CLASS = r"[ \-']?"


def normalize(text: str) -> str:
    """NFKD -> strip combining marks -> casefold -> ASCII quotes/dashes -> collapse whitespace."""
    if text is None:
        return ""
    t = unicodedata.normalize("NFKD", str(text))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.translate(_QUOTES).translate(_DASHES).casefold()
    return re.sub(r"\s+", " ", t).strip()


def name_pattern(name: str) -> re.Pattern:
    """Compile the registered pattern for one name (applied to normalised text)."""
    norm = normalize(name)
    parts = re.split(r"[ \-']+", norm)
    parts = [re.escape(p) for p in parts if p]
    body = _SEP_CLASS.join(parts)
    # boundary: not preceded / followed by a letter or digit ("\w" minus underscore)
    return re.compile(r"(?<![^\W_])" + body + r"(?![^\W_])")


_TOKEN = re.compile(r"[^\W_]+")


def first_token(name: str) -> str:
    toks = _TOKEN.findall(normalize(name))
    return toks[0] if toks else ""


class NameMatcher:
    """Match a fixed list of names against arbitrary text, deterministically.

    A token prefilter makes this fast without changing the result: a name can
    only match starting at a letter/digit boundary, so its first alphanumeric
    token must be a prefix of some whole token of the text (a prefix rather
    than the whole token because the separator inside a name is optional:
    "OcasioCortez" is one text token). Only names passing that check are run
    through their full registered pattern, which decides.
    """

    def __init__(self, names: Iterable[str]):
        self.names = list(names)
        self._order = {n: i for i, n in enumerate(self.names)}
        self._patterns = {n: name_pattern(n) for n in self.names}
        self._by_token: dict[str, list[str]] = {}
        for n in self.names:
            self._by_token.setdefault(first_token(n), []).append(n)
        self._max_first = max((len(k) for k in self._by_token), default=0)

    def _candidates(self, norm: str) -> set[str]:
        cands: set[str] = set()
        for tok in set(_TOKEN.findall(norm)):
            for L in range(1, min(len(tok), self._max_first) + 1):
                hit = self._by_token.get(tok[:L])
                if hit:
                    cands.update(hit)
        return cands

    def match(self, text: str) -> list[str]:
        """Names (in registered order) that occur in ``text`` as whole phrases."""
        norm = normalize(text)
        if not norm:
            return []
        found = [n for n in self._candidates(norm) if self._patterns[n].search(norm)]
        return sorted(found, key=self._order.__getitem__)

    def match_fields(self, *fields: str | None) -> list[str]:
        """Match against the concatenation of several text fields."""
        return self.match(" \n ".join(f for f in fields if f))
