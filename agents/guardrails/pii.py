"""Lightweight, regex-based PII detection — no ML models, runs in microseconds.

Deliberately conservative: prefers missing an edge case over false-positiving
on ordinary product specs (e.g. "50W power", "8 ohm") that happen to contain
digits.
"""
import re

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[-\s]?)?[6-9]\d{9}(?!\d)")
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,16}(?!\d)")
_AADHAAR_RE = re.compile(r"(?<!\d)\d{4}[ -]\d{4}[ -]\d{4}(?!\d)")
_PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")

# Narrower set used for the *output* guard: business contact info (email/phone)
# is legitimate content for a dealer chatbot to surface, so only redact
# high-risk identifiers there.
HIGH_RISK_TYPES = {"credit_card", "aadhaar", "pan"}
ALL_TYPES = {"email", "phone", "credit_card", "aadhaar", "pan"}


def _luhn_valid(digits: str) -> bool:
    digits = re.sub(r"[ -]", "", digits)
    if not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def detect(text: str, types: set[str] | None = None) -> list[dict]:
    types = types or ALL_TYPES
    matches: list[dict] = []

    if "email" in types:
        for m in _EMAIL_RE.finditer(text):
            matches.append({"type": "email", "match": m.group(), "start": m.start(), "end": m.end()})
    if "phone" in types:
        for m in _PHONE_RE.finditer(text):
            matches.append({"type": "phone", "match": m.group(), "start": m.start(), "end": m.end()})
    if "aadhaar" in types:
        for m in _AADHAAR_RE.finditer(text):
            matches.append({"type": "aadhaar", "match": m.group(), "start": m.start(), "end": m.end()})
    if "pan" in types:
        for m in _PAN_RE.finditer(text):
            matches.append({"type": "pan", "match": m.group(), "start": m.start(), "end": m.end()})
    if "credit_card" in types:
        for m in _CARD_RE.finditer(text):
            if _luhn_valid(m.group()):
                matches.append({"type": "credit_card", "match": m.group(), "start": m.start(), "end": m.end()})

    # A card number's digit run can also satisfy the (shorter) Aadhaar
    # pattern at the same start position — resolve overlaps by keeping the
    # longest match at each position so redaction doesn't leave a fragment
    # of the number un-redacted.
    matches.sort(key=lambda x: (x["start"], -(x["end"] - x["start"])))
    resolved: list[dict] = []
    cursor = 0
    for m in matches:
        if m["start"] < cursor:
            continue
        resolved.append(m)
        cursor = m["end"]
    return resolved


def redact(text: str, types: set[str] | None = None) -> tuple[str, list[dict]]:
    matches = detect(text, types)
    if not matches:
        return text, []

    out = []
    cursor = 0
    for m in matches:
        if m["start"] < cursor:
            continue  # overlapping match, already covered
        out.append(text[cursor:m["start"]])
        out.append(f"[REDACTED_{m['type'].upper()}]")
        cursor = m["end"]
    out.append(text[cursor:])
    return "".join(out), matches
