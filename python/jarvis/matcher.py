"""Fuzzy-match a transcript against the inventory so the LLM only sees ~10 candidates."""
import re
from difflib import SequenceMatcher

_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}
NUM_WORDS = {**_ONES, **_TENS}


def words_to_digits(text):
    """'esp thirty two' -> 'esp 32', 'two' -> '2'. Joins tens+ones."""
    toks, out, i = text.lower().replace("-", " ").split(), [], 0
    while i < len(toks):
        t = toks[i]
        if t in _TENS and i + 1 < len(toks) and toks[i + 1] in _ONES and 0 < _ONES[toks[i + 1]] < 10:
            out.append(str(_TENS[t] + _ONES[toks[i + 1]])); i += 2; continue
        out.append(str(NUM_WORDS[t]) if t in NUM_WORDS else t); i += 1
    return " ".join(out)


def normalise(text):
    text = words_to_digits(text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact(text):
    return normalise(text).replace(" ", "")


def _terms(item):
    names = [item["name"]] + [a for a in item["aliases"].split(",") if a]
    return [compact(n) for n in names]


def score(transcript, item):
    """0..1. Alias/name found as a (possibly plural) substring, else best fuzzy window, else 'uses' overlap."""
    ct = compact(transcript)
    best = 0.0
    for term in _terms(item):
        if not term:
            continue
        if term in ct:
            best = max(best, 1.0 if len(term) > 3 else 0.9)
            continue
        n = len(term)
        if n <= 3:  # 'esp' fuzzy-matched the 'es' in 'yes' at 0.76: short terms must match exactly
            continue
        for k in (n - 1, n, n + 1, n + 2):
            for s in range(0, max(1, len(ct) - k + 1)):
                r = SequenceMatcher(None, term, ct[s:s + k]).ratio()
                if r > best:
                    best = r * 0.95
    toks = set(normalise(transcript).split())
    for use in filter(None, item.get("uses", "").split(",")):
        ut = set(normalise(use).split()) - {"the", "a"}
        if ut and len(ut & toks) >= max(1, len(ut) - 1):
            best = max(best, 0.7)
    return best


def candidates(transcript, items, k=10, floor=0.55):
    scored = sorted(((score(transcript, it), it) for it in items), key=lambda x: -x[0])
    out = [it for s, it in scored if s >= floor][:k]
    return out


def best_item(transcript, items, floor=0.75):
    scored = sorted(((score(transcript, it), it) for it in items), key=lambda x: -x[0])
    return scored[0][1] if scored and scored[0][0] >= floor else None
