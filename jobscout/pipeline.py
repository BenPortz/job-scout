"""FILTER stage: raw listings -> schema-validated candidates.

Consumes whatever the FIND stage produced (a browser agent driving the DOM
extractors in `jobscout/extractors/`), applies the deterministic knockouts from
`filters.py`, suppresses companies seen recently, and writes a candidates file
for the LLM stage.

No browser, no network, no model. The same raw file always produces the same
candidates file, so the judge can be re-run against a fixed candidate set while
you iterate on the prompt.

Usage:
    python -m jobscout.pipeline --raw data/raw/2026-08-27.json
    python -m jobscout.pipeline --date 2026-08-27 --profile config/profile.yaml
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from jobscout import filters as jf
from jobscout.config import Layout, Profile, ProfileError, load_profile

SCHEMA = Path("schemas/candidates.schema.json")
JD_TEXT_CAP = 4000  # keep the LLM stage's context bounded


def recent_index_text(index_path: Path, days: int, exclude_date: str = "") -> str:
    """Concatenated text of the last `days` index rows, for fuzzy dedup.

    `exclude_date` drops that date's own row. Without it a re-run deduplicates
    against itself: the first pass writes an index row naming today's picks, the
    second pass reads that row back, flags every pick as a duplicate, and
    silently empties the report.
    """
    if not index_path.is_file():
        return ""
    rows = [
        ln for ln in index_path.read_text(encoding="utf-8").splitlines()
        if ln.strip().startswith("|") and "-" in ln[:14]
        and not (exclude_date and ln.startswith(f"| {exclude_date} "))
    ]
    return "\n".join(rows[-days:]).lower()


def build_candidate(topic: str, listing: dict[str, Any], recent_blob: str,
                    profile: Profile) -> dict[str, Any]:
    """Parse, filter, and dedup-flag a single listing."""
    text = listing.get("jd_text") or listing.get("card_text") or ""
    title = listing.get("title", "")
    fields = jf.parse_fields(text, title)
    checks = jf.evaluate(fields, profile.topic(topic), profile.filters)

    company = listing.get("company", "")
    seen_recent = bool(company and company.lower() in recent_blob)

    return {
        "job_id": str(listing.get("job_id", "")),
        "source": listing.get("source", "unknown"),
        "url": listing.get("url", ""),
        "title": title or "",
        "company": company,
        "comp": fields["comp"],
        "size": fields["size"],
        "stage": fields["stage"],
        "age_days": fields["age_days"],
        "posted_date": listing.get("posted_date"),
        "location_remote": checks["remote"],
        "seen_recent": seen_recent,
        "jd_text": text[:JD_TEXT_CAP],
        "filters": checks,
        "passed": jf.passed(checks, profile.load_bearing) and not seen_recent,
    }


def filter_raw(raw: dict[str, Any], profile: Profile, recent_blob: str) -> dict[str, Any]:
    """Filter every topic in a raw file. Pure, no I/O."""
    out: dict[str, Any] = {"date": raw.get("date"), "topics": {}}
    for topic, block in raw.get("topics", {}).items():
        status = block.get("status", "ok")
        if status != "ok":
            # A failed FIND is recorded so the report can say the search broke
            # instead of showing no results.
            out["topics"][topic] = {
                "status": status,
                "eng_flavor": block.get("eng_flavor"),
                "error": block.get("error", ""),
                "candidates": [],
            }
            continue
        out["topics"][topic] = {
            "status": "ok",
            "eng_flavor": block.get("eng_flavor"),
            "candidates": [
                build_candidate(topic, ln, recent_blob, profile)
                for ln in block.get("listings", [])
            ],
        }
    return out


def validate(doc: dict[str, Any], schema_path: Path) -> str | None:
    """Validate against the JSON schema. Returns an error string, or None."""
    try:
        import jsonschema
    except ImportError:
        return None  # optional dependency; absence is not a failure
    if not schema_path.is_file():
        return None
    try:
        jsonschema.validate(doc, json.loads(schema_path.read_text(encoding="utf-8")))
    except Exception as e:  # noqa: BLE001 - surfaced to the caller as text
        return str(e)
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", help="Raw listings JSON (default: <data>/raw/<date>.json)")
    ap.add_argument("--out", help="Output path (default: <data>/candidates/<date>.json)")
    ap.add_argument("--profile", help="Profile YAML (default: config/profile.yaml)")
    ap.add_argument("--data", default="data", help="Data directory (default: data)")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--no-validate", action="store_true")
    args = ap.parse_args(argv)

    try:
        profile = load_profile(args.profile)
    except ProfileError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    layout = Layout(Path(args.data))
    raw_path = Path(args.raw) if args.raw else layout.for_date("raw", args.date)
    if not raw_path.is_file():
        print(f"ERROR: raw listings not found: {raw_path}", file=sys.stderr)
        return 1

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    recent_blob = recent_index_text(layout.index, profile.dedup_days,
                                    exclude_date=raw.get("date", args.date))
    out = filter_raw(raw, profile, recent_blob)
    out["date"] = out.get("date") or args.date

    if not args.no_validate:
        if err := validate(out, SCHEMA):
            print(f"ERROR: candidates failed schema validation: {err}", file=sys.stderr)
            return 2

    out_path = Path(args.out) if args.out else layout.for_date("candidates", out["date"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    for topic, block in out["topics"].items():
        cands = block["candidates"]
        n_passed = sum(1 for c in cands if c["passed"])
        print(f"  {topic}: status={block['status']} listings={len(cands)} "
              f"passed={n_passed}", file=sys.stderr)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
