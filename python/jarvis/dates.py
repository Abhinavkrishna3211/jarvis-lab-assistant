"""Date resolution is done in code, never by the model."""
import re
from datetime import date, timedelta

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def resolve_due(phrase, today):
    """'Friday' -> next Friday (strictly after today); 'tomorrow'; 'in 3 days'; ISO date. None if unknown."""
    if not phrase:
        return None
    p = phrase.strip().lower()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p):
        try:
            d = date.fromisoformat(p)
            return d.isoformat() if d >= today else None
        except ValueError:
            return None
    if p == "today":
        return today.isoformat()
    if p == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    if p in ("next week",):
        return (today + timedelta(days=7)).isoformat()
    m = re.fullmatch(r"in (\d+) days?", p)
    if m:
        return (today + timedelta(days=int(m.group(1)))).isoformat()
    for i, name in enumerate(DAYS):
        if p in (name, "next " + name, "this " + name):
            ahead = (i - today.weekday()) % 7 or 7
            return (today + timedelta(days=ahead)).isoformat()
    return None


def speakable(iso):
    d = date.fromisoformat(iso)
    return f"{d:%A} {d.day} {d:%B}"  # not %-d: glibc-only, raises on Windows
