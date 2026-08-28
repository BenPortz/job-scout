"""Tests for the deterministic filter stage.

These cover the parsers against the messy real-world strings job boards emit,
and the knockout logic against the config shapes in profile.example.yaml.
Because the stage is pure, every case here is a plain input/output assertion.
"""

from __future__ import annotations

import pytest

from jobscout import filters as f


# --- parse_comp -----------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("$120k – $160k • 0.0% – 0.1%", "$120k – $160k"),
    ("$90,000 - $140,000 per year", "$90,000 - $140,000"),
    ("Salary: $150k", "$150k"),
    ("$120k—$160k", "$120k—$160k"),
])
def test_parse_comp_finds_bands(text, expected):
    assert f.parse_comp(text) == expected


@pytest.mark.parametrize("text", [
    "Competitive salary and equity",
    "0.5% - 1.5% equity only",
    "",
])
def test_parse_comp_returns_none_without_a_figure(text):
    assert f.parse_comp(text) is None


def test_parse_comp_prefers_range_over_single_figure():
    # A range appearing after a lone figure must still win, the range is the
    # more informative signal for salary calibration.
    assert f.parse_comp("Equity worth $50k. Base $120k – $160k.") == "$120k – $160k"


# --- parse_age_days -------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Posted today", 0),
    ("Posted yesterday", 1),
    ("Reposted: 7 days ago", 7),
    ("2 weeks ago", 14),
    ("1 month ago", 30),
    ("3 hours ago", 0),
])
def test_parse_age_days(text, expected):
    assert f.parse_age_days(text) == expected


def test_parse_age_days_none_when_absent():
    assert f.parse_age_days("Full Time · Remote") is None


# --- is_remote ------------------------------------------------------------

def test_is_remote_true_for_plain_remote():
    assert f.is_remote("Remote (United States)") is True


def test_is_remote_false_without_the_word():
    assert f.is_remote("San Francisco, CA · Full Time") is False


def test_is_remote_false_when_in_office_contradicts_the_tag():
    # The board tags this "remote" but the body requires office days. Without
    # an explicit remote phrase to override it, this must not survive.
    text = "Remote · Candidates must be in office 3 days a week"
    assert f.is_remote(text) is False


def test_is_remote_true_when_explicit_remote_phrase_overrides():
    text = "Hybrid in office, or remote for the right candidate"
    assert f.is_remote(text) is True


# --- stage_size_ok --------------------------------------------------------

SMALL_CO = {
    "allow": ["seed", "series a", "early stage"],
    "deny": ["growth stage", "series b"],
    "max_headcount": 50,
}


def test_stage_allow_matches():
    assert f.stage_size_ok(None, "Early Stage", SMALL_CO) is True


def test_stage_deny_matches():
    assert f.stage_size_ok(None, "Growth Stage", SMALL_CO) is False


def test_stage_deny_beats_allow():
    # A listing carrying both signals is treated as the later stage.
    assert f.stage_size_ok("200 Employees", "Series B", SMALL_CO) is False


def test_headcount_ceiling_applies_when_stage_is_unknown():
    assert f.stage_size_ok("11-50 Employees", None, SMALL_CO) is True
    assert f.stage_size_ok("500 Employees", None, SMALL_CO) is False


def test_unknown_stage_is_not_a_knockout():
    # Deliberate: an unrecognised vocabulary should cost a listing a review,
    # not silently drop it.
    assert f.stage_size_ok(None, None, SMALL_CO) is True


def test_any_policy_skips_the_check_entirely():
    assert f.stage_size_ok("5000 Employees", "Public Stage", {"any": True}) is True


# --- title_ok -------------------------------------------------------------

DENY = ["director", "\\bvp\\b", "account executive", "\\bae\\b"]


@pytest.mark.parametrize("title", [
    "Director of Operations",
    "VP, Business Operations",
    "Account Executive",
])
def test_title_deny_knocks_out(title):
    assert f.title_ok(title, DENY) is False


@pytest.mark.parametrize("title", [
    "Chief of Staff",
    "AI Ops Engineer - GTM",
    "Head of Operations",
])
def test_title_allows_targets(title):
    assert f.title_ok(title, DENY) is True


def test_word_boundary_prevents_substring_false_positive():
    # "\bae\b" must not fire inside an ordinary word.
    assert f.title_ok("Sales Engineer, Michael", DENY) is True
    assert f.title_ok("Praetorian Guard", DENY) is True


# --- evaluate / passed ----------------------------------------------------

FILTER_CFG = {"max_age_days": 14, "title_deny": DENY,
              "load_bearing": ["remote", "recent", "stage_ok", "title_ok"]}
TOPIC = {"stage": SMALL_CO}

GOOD_LISTING = (
    "Chief of Staff\n$120k – $160k • 0.0% – 0.1%\n"
    "Remote (United States)\nReposted: 7 days ago\nEarly Stage"
)


def test_evaluate_passes_a_clean_listing():
    fields = f.parse_fields(GOOD_LISTING, "Chief of Staff")
    result = f.evaluate(fields, TOPIC, FILTER_CFG)
    assert result == {"remote": True, "stage_ok": True, "title_ok": True,
                      "comp_ok": True, "recent": True}
    assert f.passed(result, FILTER_CFG["load_bearing"]) is True


def test_stale_listing_fails_recency():
    stale = GOOD_LISTING.replace("Reposted: 7 days ago", "1 month ago")
    fields = f.parse_fields(stale, "Chief of Staff")
    result = f.evaluate(fields, TOPIC, FILTER_CFG)
    assert result["recent"] is False
    assert f.passed(result, FILTER_CFG["load_bearing"]) is False


def test_missing_comp_does_not_drop_when_not_load_bearing():
    # comp_ok is evaluated and reported, but is absent from load_bearing, so a
    # strong early-stage posting with no band still reaches the LLM stage.
    no_comp = GOOD_LISTING.replace("$120k – $160k • 0.0% – 0.1%\n", "")
    fields = f.parse_fields(no_comp, "Chief of Staff")
    result = f.evaluate(fields, TOPIC, FILTER_CFG)
    assert result["comp_ok"] is False
    assert f.passed(result, FILTER_CFG["load_bearing"]) is True


def test_making_comp_load_bearing_drops_it():
    no_comp = GOOD_LISTING.replace("$120k – $160k • 0.0% – 0.1%\n", "")
    fields = f.parse_fields(no_comp, "Chief of Staff")
    result = f.evaluate(fields, TOPIC, FILTER_CFG)
    assert f.passed(result, ["remote", "recent", "comp_ok"]) is False


def test_unknown_date_is_not_a_knockout():
    # Some boards publish no posting date at all. Treating that as "too old"
    # made every listing from such a board unpassable regardless of quality.
    # Unknown is passed through for the LLM stage to weigh, matching how an
    # unrecognised stage is handled.
    undated = GOOD_LISTING.replace("Reposted: 7 days ago\n", "")
    fields = f.parse_fields(undated, "Chief of Staff")
    assert fields["age_days"] is None
    assert f.evaluate(fields, TOPIC, FILTER_CFG)["recent"] is True


def test_a_known_stale_date_still_fails():
    # Tolerating unknown must not tolerate explicitly old.
    stale = GOOD_LISTING.replace("Reposted: 7 days ago", "3 months ago")
    fields = f.parse_fields(stale, "Chief of Staff")
    assert fields["age_days"] == 90
    assert f.evaluate(fields, TOPIC, FILTER_CFG)["recent"] is False
