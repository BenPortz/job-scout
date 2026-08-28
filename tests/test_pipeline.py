"""Tests for the FILTER stage.

Runs the real fixture through the real filter, asserting on which listings
survive and why each rejected one was rejected. This catches a filter that
drops the right listings for the wrong reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobscout import pipeline as p
from jobscout.config import load_profile

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE = load_profile("config/profile.example.yaml")


@pytest.fixture
def filtered() -> dict:
    raw = json.loads((FIXTURES / "raw_sample.json").read_text(encoding="utf-8"))
    return p.filter_raw(raw, PROFILE, recent_blob="")


def _by_company(block: dict, name: str) -> dict:
    return next(c for c in block["candidates"] if c["company"] == name)


def test_only_the_qualifying_listing_survives(filtered):
    business = filtered["topics"]["business"]
    passed = [c["company"] for c in business["candidates"] if c["passed"]]
    assert passed == ["Northwind Analytics"]


def test_rejected_listings_are_kept_for_audit(filtered):
    # Failures must remain inspectable: you should always be able to ask why a
    # listing did not reach the judge.
    assert len(filtered["topics"]["business"]["candidates"]) == 4


def test_senior_title_at_late_stage_fails_both_reasons(filtered):
    c = _by_company(filtered["topics"]["business"], "Kestrel Systems")
    assert c["filters"]["title_ok"] is False   # "Director"
    assert c["filters"]["stage_ok"] is False   # Series B
    assert c["passed"] is False


def test_in_office_listing_fails_on_remote_only(filtered):
    c = _by_company(filtered["topics"]["business"], "Halcyon Labs")
    assert c["filters"]["remote"] is False
    assert c["filters"]["stage_ok"] is True    # seed/small is fine; location is not


def test_stale_listing_fails_on_recency_only(filtered):
    c = _by_company(filtered["topics"]["business"], "Tessellate")
    assert c["filters"]["recent"] is False
    assert c["filters"]["remote"] is True
    assert c["filters"]["title_ok"] is True


def test_failed_find_is_carried_through_not_dropped(filtered):
    eng = filtered["topics"]["engineering"]
    assert eng["status"] == "find_failed"
    assert eng["candidates"] == []
    assert "selector" in eng["error"].lower() or "markup" in eng["error"].lower()


def test_source_is_preserved_per_listing(filtered):
    assert _by_company(filtered["topics"]["business"], "Tessellate")["source"] == "yc"
    assert _by_company(filtered["topics"]["business"], "Northwind Analytics")["source"] == "wellfound"


def test_job_ids_are_namespaced_so_boards_cannot_collide(filtered):
    ids = [c["job_id"] for c in filtered["topics"]["business"]["candidates"]]
    assert all(i.startswith(("wf_", "yc_")) for i in ids)
    assert len(set(ids)) == len(ids)


def test_jd_text_is_capped(filtered):
    for block in filtered["topics"].values():
        for c in block["candidates"]:
            assert len(c["jd_text"]) <= p.JD_TEXT_CAP


def test_dedup_suppresses_a_company_seen_recently():
    raw = json.loads((FIXTURES / "raw_sample.json").read_text(encoding="utf-8"))
    out = p.filter_raw(raw, PROFILE, recent_blob="| 2026-03-13 | northwind analytics |")
    c = _by_company(out["topics"]["business"], "Northwind Analytics")
    assert c["seen_recent"] is True
    assert c["passed"] is False   # would otherwise have passed


def test_output_validates_against_the_schema(filtered):
    pytest.importorskip("jsonschema")
    filtered["date"] = "2026-03-14"
    assert p.validate(filtered, Path("schemas/candidates.schema.json")) is None
