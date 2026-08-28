"""Profile loading and the on-disk layout of a run.

A profile describes *what you are looking for*; it is the only place personal
search criteria live. `config/profile.yaml` is gitignored, so a fork of this
repo carries the example and never the author's real search.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PROFILE = Path("config/profile.yaml")
EXAMPLE_PROFILE = Path("config/profile.example.yaml")


class ProfileError(RuntimeError):
    """Raised when a profile is missing or structurally unusable."""


@dataclass(frozen=True)
class Profile:
    """A validated search profile."""

    filters: dict[str, Any]
    topics: dict[str, dict[str, Any]]
    dedup: dict[str, Any]

    def topic(self, name: str) -> dict[str, Any]:
        """Policy block for one topic, or an empty policy for an unknown one.

        Unknown topics are tolerated instead of fatal: a raw file may carry a
        lane the profile no longer defines, and losing that lane to the default
        policy is better than failing the whole run.
        """
        return self.topics.get(name, {})

    def label(self, name: str) -> str:
        return self.topic(name).get("label", name.replace("_", " ").title())

    @property
    def load_bearing(self) -> list[str]:
        return self.filters.get(
            "load_bearing", ["remote", "recent", "stage_ok", "title_ok"]
        )

    @property
    def dedup_days(self) -> int:
        return int(self.dedup.get("window_days", 7))


def load_profile(path: Path | str | None = None) -> Profile:
    """Load a profile, falling back to the committed example.

    The fallback keeps a fresh clone runnable: `pytest` and a demo run work
    before the user has written their own profile.
    """
    p = Path(path) if path else DEFAULT_PROFILE
    if not p.is_file():
        if path is None and EXAMPLE_PROFILE.is_file():
            p = EXAMPLE_PROFILE
        else:
            raise ProfileError(
                f"No profile at {p}. Copy {EXAMPLE_PROFILE} to {DEFAULT_PROFILE} and edit it."
            )

    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ProfileError(f"{p} did not parse to a mapping.")
    topics = data.get("topics") or {}
    if not topics:
        raise ProfileError(f"{p} defines no topics; the scout would have nothing to search.")

    return Profile(
        filters=data.get("filters") or {},
        topics=topics,
        dedup=data.get("dedup") or {},
    )


@dataclass(frozen=True)
class Layout:
    """Where a run reads and writes.

    One dated file per stage, so any stage can be re-run against a previous
    stage's output without repeating the expensive steps before it.
    """

    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def candidates(self) -> Path:
        return self.root / "candidates"

    @property
    def verdicts(self) -> Path:
        return self.root / "verdicts"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def index(self) -> Path:
        return self.reports / "INDEX.md"

    def for_date(self, stage: str, date: str, suffix: str = ".json") -> Path:
        return getattr(self, stage) / f"{date}{suffix}"
