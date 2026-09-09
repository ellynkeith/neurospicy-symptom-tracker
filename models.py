from datetime import date, time
from typing import List, Optional

from pydantic import BaseModel, field_validator

# Taxonomy retired 2026-09-09: it was autism-coded (sensory processing,
# stimming, shutdown), which doesn't match this kid's actual evaluated
# profile (ADHD + ODD; specifically assessed for and ruled out for ASD).
# Kept here only so migrate_category_taxonomy() knows exactly which rows to
# remove from an existing deployment's `categories` table -- never inserted.
RETIRED_DEFAULT_CATEGORIES = [
    "meltdown",
    "shutdown",
    "sensory seeking",
    "sensory avoidance",
    "stimming",
    "anxiety",
    "rigidity",
    "aggression",
]

# DSM-5 ODD's three symptom clusters (angry/irritable mood,
# argumentative/defiant behavior, vindictiveness) plus the three ADHD
# presentations (impulsive, inattentive, hyperactive/restless).
DEFAULT_CATEGORIES = [
    "angry/irritable",
    "argumentative/defiant",
    "vindictive",
    "impulsive",
    "inattentive",
    "hyperactive/restless",
]

# Starter vocabulary for the situation/demand picker, replacing the old
# freeform "trigger" text field. Modeled on Ross Greene's Collaborative &
# Proactive Solutions framework: naming the specific unsolved
# demand/situation (not just "he got upset") is what makes the log useful
# for spotting patterns. Grows over time via the same "+ new" chip pattern
# as categories.
DEFAULT_SITUATIONS = [
    "told no",
    "asked to transition off preferred activity",
    "non-preferred task demand",
    "sibling conflict",
    "unexpected change in plans",
    "waiting/turn-taking",
]

# Exercise type is a small, fixed clinical distinction rather than a growable
# vocabulary like categories/situations -- cognitively-engaging activity
# (e.g. martial arts, dance, a sport with strategy) has the strongest
# evidenced effect on emotion regulation specifically, distinct from simple
# aerobic activity (e.g. running, biking). Kept as a closed set on purpose.
ALLOWED_EXERCISE_TYPES = {"cognitively-engaging", "aerobic", "other/mixed"}


def _clean_tag_list(value: List[str]) -> List[str]:
    cleaned = [c.strip().lower() for c in value if c and c.strip()]
    # de-dupe while preserving order
    seen = set()
    deduped = []
    for c in cleaned:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    return deduped


class EntryIn(BaseModel):
    entry_date: date
    entry_time: Optional[time] = None
    categories: List[str]
    setting: Optional[str] = None
    duration_minutes: Optional[int] = None
    intensity: Optional[int] = None
    # Optional, unlike categories -- a specific situation/demand isn't always
    # identifiable for a given entry.
    situations: List[str] = []
    notes: Optional[str] = None
    logged_by: Optional[str] = None

    @field_validator("categories")
    @classmethod
    def categories_not_empty(cls, value: List[str]) -> List[str]:
        deduped = _clean_tag_list(value)
        if not deduped:
            raise ValueError("At least one category is required")
        return deduped

    @field_validator("situations")
    @classmethod
    def clean_situations(cls, value: List[str]) -> List[str]:
        return _clean_tag_list(value)


class CategoryIn(BaseModel):
    name: str


class SituationIn(BaseModel):
    name: str


class DailyLogIn(BaseModel):
    """Sleep + exercise context for a single day, independent of how many
    behavior entries exist for that date. Everything but entry_date is
    optional -- there's no obligation to fill in sleep on a day you only
    logged exercise, or vice versa."""
    entry_date: date
    bedtime: Optional[time] = None
    # Distinct from bedtime -- when they actually fell asleep vs. when they
    # got into bed. Sleep-onset latency (the gap between the two) is its
    # own useful signal, not just total time in bed.
    fell_asleep_time: Optional[time] = None
    wake_time: Optional[time] = None
    night_awakenings: Optional[int] = None
    exercise_minutes: Optional[int] = None
    exercise_type: Optional[str] = None

    @field_validator("night_awakenings", "exercise_minutes")
    @classmethod
    def non_negative(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 0:
            raise ValueError("must be zero or greater")
        return value

    @field_validator("exercise_type")
    @classmethod
    def valid_exercise_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        cleaned = value.strip().lower()
        if cleaned not in ALLOWED_EXERCISE_TYPES:
            raise ValueError(f"exercise_type must be one of {sorted(ALLOWED_EXERCISE_TYPES)}")
        return cleaned


# How she responded to a wetting incident is a small, fixed clinical
# distinction, like exercise_type, rather than a growable vocabulary --
# keeping it to a closed set is what makes a compliant-vs-noncompliant
# pattern easy to spot over time.
ALLOWED_WETTING_RESPONSES = {"compliant", "noncompliant", "other"}


class WettingIncidentIn(BaseModel):
    """A single wetting incident. Unlike sleep/exercise (one value per day),
    there can be any number of these on a given day, so each incident is its
    own row rather than a field on DailyLogIn."""
    entry_date: date
    incident_time: Optional[time] = None
    # Reuses the same setting vocabulary as EntryIn.setting (home/school/
    # transitions/public/other) for consistency, on the same freeform
    # convention -- not enforced here either.
    setting: Optional[str] = None
    response: str

    @field_validator("response")
    @classmethod
    def valid_response(cls, value: str) -> str:
        cleaned = (value or "").strip().lower()
        if cleaned not in ALLOWED_WETTING_RESPONSES:
            raise ValueError(f"response must be one of {sorted(ALLOWED_WETTING_RESPONSES)}")
        return cleaned
