"""Deterministic parsing + hard-filter logic.

Pure functions, no I/O, no browser, no LLM. The same listing text always yields
the same parsed fields and the same filter verdict. Rules are applied here so
the LLM stage only sees listings that have already cleared them.

Search policy comes from configuration. Every threshold, allow-list, and deny-list is
supplied by the caller from a profile config (see `config/profile.example.yaml`),
so retargeting the scout at a different search means editing YAML, not Python.
"""

from __future__ import annotations

import re
from typing import Any

# --- Listing-text parsers -------------------------------------------------
# Job boards render these fields as free text on the card and the JD body, so
# they are recovered with regex, not from a structured API.

_COMP_RANGE_RE = re.compile(r"\$\s?\d[\d,]*\s?[kK]?\s*[–\-—]\s*\$?\s?\d[\d,]*\s?[kK]?")
_COMP_SINGLE_RE = re.compile(r"\$\s?\d[\d,]*\s?[kK]")
_SIZE_RE = re.compile(r"(\d+\+?(?:\s?[-–]\s?\d+)?)\s+Employees", re.I)
_AGE_RE = re.compile(r"(\d+)\s+(hour|day|week|month)s?\s+ago", re.I)
_STAGE_RE = re.compile(
    r"\b(Seed|Series\s+[A-D]|Early\s+Stage|Growth\s+Stage|Scale\s+Stage|Public\s+Stage)\b",
    re.I,
)

_AGE_UNIT_DAYS = {"hour": 0, "day": 1, "week": 7, "month": 30}


def parse_comp(text: str) -> str | None:
    """Return the compensation string, preferring a range over a single figure."""
    m = _COMP_RANGE_RE.search(text) or _COMP_SINGLE_RE.search(text)
    return m.group(0).strip() if m else None


def parse_size(text: str) -> str | None:
    m = _SIZE_RE.search(text)
    return m.group(0).strip() if m else None


def parse_stage(text: str) -> str | None:
    m = _STAGE_RE.search(text)
    return m.group(0).strip() if m else None


def parse_age_days(text: str) -> int | None:
    """Age of the posting in days, or None when the text carries no date signal."""
    t = text.lower()
    if any(s in t for s in ("posted today", "posted just now", "posted moments")):
        return 0
    if "yesterday" in t:
        return 1
    m = _AGE_RE.search(text)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    return n * _AGE_UNIT_DAYS[unit]


def is_remote(text: str) -> bool:
    """True when the listing reads as remote-eligible.

    Boards frequently tag a role "remote" in metadata while the body says
    otherwise, so an explicit in-office phrase demands an explicit remote
    phrase to survive.
    """
    t = text.lower()
    if "remote" not in t:
        return False
    if any(s in t for s in ("in office", "on-site only", "onsite only")):
        return any(
            s in t for s in ("or remote", "remote-first", "fully remote", "remote only")
        )
    return True


# --- Config-driven knockouts ----------------------------------------------


def stage_size_ok(size: str | None, stage: str | None, policy: dict[str, Any]) -> bool:
    """Company-stage knockout for one topic.

    `policy` accepts:
        any: true            -> topic does not filter on stage at all
        deny: [str, ...]     -> substrings that disqualify outright
        allow: [str, ...]    -> substrings that qualify outright
        max_headcount: int   -> ceiling applied to a parsed "N Employees" string

    An unrecognised stage is *not* a knockout; it is passed through for the
    LLM stage to weigh, so a board's unexpected vocabulary loses a listing to
    review instead of dropping it silently.
    """
    if policy.get("any"):
        return True

    blob = f"{size or ''} {stage or ''}".lower()
    if any(d.lower() in blob for d in policy.get("deny", [])):
        return False
    if any(a.lower() in blob for a in policy.get("allow", [])):
        return True

    cap = policy.get("max_headcount")
    if cap and size:
        m = re.search(r"(\d+)", size.replace(",", ""))
        if m:
            return int(m.group(1)) <= int(cap)
    return True


def title_ok(title: str, deny_patterns: list[str]) -> bool:
    """False when the title matches any deny pattern (regex, case-insensitive)."""
    t = (title or "").lower()
    return not any(re.search(p, t, re.I) for p in deny_patterns)


def parse_fields(text: str, title: str = "") -> dict[str, Any]:
    """Parse every structured field from a listing's text blob."""
    return {
        "comp": parse_comp(text),
        "size": parse_size(text),
        "stage": parse_stage(text),
        "age_days": parse_age_days(text),
        "remote": is_remote(text),
        "title": title,
    }


def evaluate(fields: dict[str, Any], topic_policy: dict[str, Any],
             filter_cfg: dict[str, Any]) -> dict[str, bool]:
    """Apply every hard filter, returning one boolean per named filter.

    An unknown posting age is not a knockout, matching how `stage_size_ok`
    treats an unrecognised stage. Some boards publish no date at all, and
    treating that as "too old" makes every listing from such a board unpassable
    no matter how good it is. Recency for those boards comes from the FIND step
    instead, which sorts by descending job id and takes the top N.
    """
    age = fields.get("age_days")
    max_age = filter_cfg.get("max_age_days", 14)
    return {
        "remote": bool(fields.get("remote")),
        "stage_ok": stage_size_ok(
            fields.get("size"), fields.get("stage"), topic_policy.get("stage", {})
        ),
        "title_ok": title_ok(fields.get("title", ""), filter_cfg.get("title_deny", [])),
        "comp_ok": fields.get("comp") is not None,
        "recent": age is None or age <= max_age,
    }


def passed(filters: dict[str, bool], load_bearing: list[str]) -> bool:
    """True when every load-bearing filter passed.

    Filters outside `load_bearing` are still reported so the LLM stage and the
    rendered report can cite them, but they do not by themselves drop a listing.
    """
    return all(filters.get(name, False) for name in load_bearing)
