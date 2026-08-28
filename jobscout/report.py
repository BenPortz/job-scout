"""WRITE stage: verdicts -> a dated Markdown report + an index row.

A deterministic render. The judging model writes the prose (the match
rationale, the gaps, the draft outreach note) and stores it as data in the
verdicts file; this module formats it. Report structure therefore stays
consistent between runs, and a formatting change costs no model calls.

Idempotent: re-running a date replaces that report and its index row.

Usage:
    python -m jobscout.report --verdicts data/verdicts/2026-08-27.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from jobscout.config import Layout, Profile, ProfileError, load_profile

SCHEMA = Path("schemas/verdicts.schema.json")
NONE_REASON_CAP = 50  # index rows stay one line per day

INDEX_HEADER = (
    "# Job Scout: Index\n\n"
    "One row per run. `applied:` tracks which pick (if any) was acted on.\n\n"
    "| Date | Topics | Picks (verdict) | Applied |\n"
    "|------|--------|-----------------|---------|\n"
)


def _abbr(label: str) -> str:
    """Short tag for the index row, derived from the topic's profile label."""
    return label.split("/")[0].split("(")[0].strip()[:12]


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [v for v in value if v]
    return [value] if value else []


def section_label(topic: str, block: dict[str, Any], profile: Profile) -> str:
    """Topic label, qualified by today's flavor when that adds anything.

    A profile label may already name the flavor, so it is only appended when
    absent; otherwise a rotating topic renders as "Engineering (broad) (broad)".
    """
    label = profile.label(topic)
    flavor = block.get("eng_flavor")
    if flavor and flavor.lower() not in label.lower():
        label += f" ({flavor})"
    return label


def render_section(topic: str, block: dict[str, Any], profile: Profile) -> str:
    lines = [f"## {section_label(topic, block, profile)}\n"]

    if block.get("status", "ok") != "ok":
        err = (block.get("error") or "the search stage did not complete").rstrip(".")
        lines.append(f"_Search did not run: {err}._\n")
        return "\n".join(lines)

    pick = block.get("pick")
    if not pick:
        lines.append(
            f"_No qualifying pick: {block.get('none_reason', 'nothing cleared the filters')}._\n"
        )
        return "\n".join(lines)

    lines.append(
        f"### {pick['title']} @ {pick['company']}, "
        f"**{pick['verdict'].upper()}** (fit {pick['fit_score']}/5)\n"
    )
    lines.append(f"- **JD:** [{pick['url']}]({pick['url']})")

    meta = [m for m in (
        f"Posted {pick['posted']}" if pick.get("posted") else "",
        f"Comp {pick['comp']}" if pick.get("comp") else "",
        pick.get("size_stage", ""),
    ) if m]
    if meta:
        lines.append(f"- {' · '.join(meta)}")

    if recap := pick.get("hard_filter_recap"):
        lines.append(f"- **Hard-filter check:** {recap}")

    if strongest := pick.get("where_strongest"):
        lines.append("- **Strongest match:**")
        for item in strongest:
            ref = f" ({item['pool_id']})" if item.get("pool_id") else ""
            lines.append(f"  - {item['text']}{ref}")

    # Gaps are full sentences, so they get their own bullets instead of being
    # run together on one line.
    if gaps := _as_list(pick.get("gaps")):
        if len(gaps) == 1:
            lines.append(f"- **Gaps / watch-outs:** {gaps[0]}")
        else:
            lines.append("- **Gaps / watch-outs:**")
            lines.extend(f"  - {g}" for g in gaps)

    if choice := pick.get("resume_choice"):
        lines.append(f"- **Résumé:** {choice}")

    if note := pick.get("cover_note"):
        lines.append("- **Draft outreach note** (a starting point, write your own):")
        lines.extend(f"  > {ln}" for ln in note.splitlines() or [note])

    lines.append("")
    return "\n".join(lines)


def render_report(verdicts: dict[str, Any], profile: Profile) -> str:
    date = verdicts["date"]
    weekday = dt.date.fromisoformat(date).strftime("%A")
    topics = verdicts.get("topics", {})
    order = [t for t in profile.topics if t in topics] + \
            [t for t in topics if t not in profile.topics]

    lines = [f"# Job Scout: {date} ({weekday})\n", "## Summary", ""]
    for topic in order:
        block = topics[topic]
        label = section_label(topic, block, profile)
        pick = block.get("pick")
        if pick:
            lines.append(f"- **{label}:** {pick['title']} @ {pick['company']}, "
                         f"{pick['verdict']} (fit {pick['fit_score']}/5)")
        else:
            lines.append(f"- **{label}:** none "
                         f"({block.get('none_reason', 'no fit')})")

    lines += ["", "---\n"]
    lines += [render_section(t, topics[t], profile) for t in order]
    lines.append("---")

    footer = f"**Run cost:** {verdicts.get('run_cost_note', 'not recorded')}"
    if model := verdicts.get("model"):
        footer += f" · model: {model}"
    lines.append(footer)
    return "\n".join(lines) + "\n"


def index_row(verdicts: dict[str, Any], profile: Profile) -> str:
    parts = []
    for topic, block in verdicts.get("topics", {}).items():
        tag = _abbr(profile.label(topic))
        if flavor := block.get("eng_flavor"):
            tag += f"/{flavor}"
        pick = block.get("pick")
        if pick:
            parts.append(f"{tag}: {pick['title']}@{pick['company']} "
                         f"({pick['verdict']} {pick['fit_score']}/5)")
        else:
            reason = block.get("none_reason", "no fit")
            if len(reason) > NONE_REASON_CAP:
                reason = reason[:NONE_REASON_CAP - 2].rstrip() + "…"
            parts.append(f"{tag}: none ({reason})")
    n = len(verdicts.get("topics", {}))
    return f"| {verdicts['date']} | {n}-topic | {' · '.join(parts)} | none |"


def upsert_index(index_path: Path, date: str, row: str) -> None:
    """Insert or replace this date's row, so re-runs never duplicate."""
    if not index_path.is_file():
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(INDEX_HEADER, encoding="utf-8")
    lines = index_path.read_text(encoding="utf-8").splitlines()
    prefix = f"| {date} "
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = row
            break
    else:
        lines.append(row)
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verdicts", help="Verdicts JSON (default: <data>/verdicts/<date>.json)")
    ap.add_argument("--out", help="Report path (default: <data>/reports/<date>.md)")
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
    vpath = Path(args.verdicts) if args.verdicts else layout.for_date("verdicts", args.date)
    if not vpath.is_file():
        print(f"ERROR: verdicts not found: {vpath}", file=sys.stderr)
        return 1
    verdicts = json.loads(vpath.read_text(encoding="utf-8"))

    if not args.no_validate:
        from jobscout.pipeline import validate
        if err := validate(verdicts, SCHEMA):
            print(f"ERROR: verdicts failed schema validation: {err}", file=sys.stderr)
            return 2

    out_path = Path(args.out) if args.out else \
        layout.for_date("reports", verdicts["date"], ".md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_report(verdicts, profile), encoding="utf-8")
    upsert_index(layout.index, verdicts["date"], index_row(verdicts, profile))

    print(f"Wrote {out_path} and updated {layout.index}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
