"""Tests for the WRITE stage.

The renderer is a pure function of the verdicts file, so these assert on
rendered text directly. They also cover two behaviours that are easy to break:
a failed search must not read as an empty result, and re-running a date must not
duplicate its index row.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobscout import report as r
from jobscout.config import Profile

FIXTURES = Path(__file__).parent / "fixtures"

PROFILE = Profile(
    filters={},
    topics={
        "business": {"label": "Operations / Chief of Staff"},
        "ai": {"label": "AI Tooling / Automation"},
        "engineering": {"label": "Engineering"},
    },
    dedup={},
)


@pytest.fixture
def verdicts() -> dict:
    return json.loads((FIXTURES / "verdicts_sample.json").read_text(encoding="utf-8"))


@pytest.fixture
def rendered(verdicts) -> str:
    return r.render_report(verdicts, PROFILE)


# --- section_label --------------------------------------------------------

def test_flavor_appended_when_label_lacks_it():
    block = {"eng_flavor": "mechanical"}
    assert r.section_label("engineering", block, PROFILE) == "Engineering (mechanical)"


def test_flavor_not_duplicated_when_label_already_names_it():
    # Guards the "Engineering (broad) (broad)" regression.
    profile = Profile(filters={}, topics={"e": {"label": "Engineering (broad)"}}, dedup={})
    assert r.section_label("e", {"eng_flavor": "broad"}, profile) == "Engineering (broad)"


def test_label_falls_back_to_topic_name():
    profile = Profile(filters={}, topics={}, dedup={})
    assert r.section_label("right_hand", {}, profile) == "Right Hand"


# --- rendering ------------------------------------------------------------

def test_picks_render_with_verdict_and_score(rendered):
    assert "Chief of Staff @ Northwind Analytics, **STRETCH** (fit 4/5)" in rendered
    assert "AI Operations Engineer @ Bellweather, **APPLY** (fit 5/5)" in rendered


def test_multiple_gaps_render_as_separate_bullets(rendered):
    # Two gap sentences must not be run together on one line.
    assert "- **Gaps / watch-outs:**\n  - No fundraising" in rendered
    assert "problem.;" not in rendered


def test_single_gap_renders_inline(rendered):
    assert "- **Gaps / watch-outs:** No production ML tenure" in rendered


def test_failed_search_does_not_read_as_an_empty_market(rendered):
    # The distinction that matters: broken tooling vs. genuinely no jobs.
    assert "_Search did not run:" in rendered
    assert "No qualifying pick" not in rendered.split("## Engineering")[1]


def test_failed_search_has_no_doubled_period(rendered):
    assert ".._" not in rendered


def test_honest_none_renders_its_reason():
    verdicts = {"date": "2026-03-14", "topics": {
        "ai": {"pick": None, "none_reason": "nothing cleared the filters"}}}
    out = r.render_report(verdicts, PROFILE)
    assert "_No qualifying pick: nothing cleared the filters._" in out


def test_cover_note_is_blockquoted(rendered):
    assert "  > Hi [Founder]," in rendered


def test_footer_carries_cost_and_model(rendered):
    assert "**Run cost:**" in rendered
    assert "model: example-model" in rendered


# --- index ----------------------------------------------------------------

def test_index_row_summarises_every_topic(verdicts):
    row = r.index_row(verdicts, PROFILE)
    assert row.startswith("| 2026-03-14 | 3-topic |")
    assert "Northwind Analytics (stretch 4/5)" in row
    assert "Bellweather (apply 5/5)" in row


def test_index_row_truncates_a_long_none_reason(verdicts):
    row = r.index_row(verdicts, PROFILE)
    assert "…" in row
    assert len(row.splitlines()) == 1


def test_upsert_replaces_rather_than_duplicates(tmp_path):
    index = tmp_path / "INDEX.md"
    r.upsert_index(index, "2026-03-14", "| 2026-03-14 | first |")
    r.upsert_index(index, "2026-03-14", "| 2026-03-14 | second |")
    text = index.read_text(encoding="utf-8")
    assert text.count("2026-03-14") == 1
    assert "second" in text and "first" not in text


def test_upsert_appends_a_new_date(tmp_path):
    index = tmp_path / "INDEX.md"
    r.upsert_index(index, "2026-03-14", "| 2026-03-14 | a |")
    r.upsert_index(index, "2026-03-15", "| 2026-03-15 | b |")
    text = index.read_text(encoding="utf-8")
    assert "2026-03-14" in text and "2026-03-15" in text
