import random
import re

from mpclstr.matching import NameMatcher, name_pattern, normalize


def test_boundaries_and_possessive():
    m = NameMatcher(["Tyson"])
    assert m.match("Mike Tyson's comeback") == ["Tyson"]
    assert m.match("TYSON FOODS recall") == ["Tyson"]
    assert m.match("Tysons Corner mall") == []
    assert m.match("the tyson-era") == ["Tyson"]
    assert m.match("notyson") == []


def test_separators_and_diacritics():
    m = NameMatcher(["Ocasio-Cortez", "David O'Connor", "Mochihito-o", "Ohtani Hiroshi", "Lumiere"])
    assert m.match("Rep. Ocasio Cortez said") == ["Ocasio-Cortez"]
    assert m.match("Rep. Ocasio–Cortez said") == ["Ocasio-Cortez"]        # en dash
    assert m.match("OcasioCortez said") == ["Ocasio-Cortez"]              # separator optional
    assert m.match("David O’Connor won") == ["David O'Connor"]            # curly quote
    assert m.match("Ohtani Hiroshi spoke; Ohtani alone does not count") == ["Ohtani Hiroshi"]
    assert m.match("Lumière festival") == ["Lumiere"]                     # diacritic stripped
    assert m.match("Mochihito-o shrine") == ["Mochihito-o"]


def test_multiword_phrase_only():
    m = NameMatcher(["Tom Hanks", "Hanks"])
    assert m.match("Tom Hanks stars") == ["Tom Hanks", "Hanks"]
    assert m.match("Hanks stars") == ["Hanks"]
    assert m.match("Tom stars") == []


def test_prefilter_equals_bruteforce(names):
    m = NameMatcher(names)
    pats = {n: name_pattern(n) for n in names}
    rng = random.Random(1)
    vocab = [normalize(n).split(" ")[0] for n in names] + ["the", "and", "market", "storm", "court"]
    for _ in range(300):
        text = " ".join(rng.choice(vocab) for _ in range(12))
        brute = [n for n in names if pats[n].search(normalize(text))]
        assert m.match(text) == brute


def test_normalize_idempotent():
    s = "Élan‑vital’s  test"
    assert normalize(normalize(s)) == normalize(s)
    assert re.search(r"\s\s", normalize(s)) is None
