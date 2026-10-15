from datetime import date, time
from typing import List, Optional

from pydantic import BaseModel, field_validator, model_validator

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
# Starter list for the context log -- slow-moving things nothing else
# captures, which are candidate drivers of multi-week good/bad phases.
# Growable, like categories/situations.
DEFAULT_EVENT_CATEGORIES = [
    "illness",
    "school break/day off",
    "schedule change",
    "visitors/travel",
    "medication change",
]

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
    # Day-level outcome. good_day: True = explicitly a good/quiet day;
    # None = not answered (never means "bad day"). day_rating is 1-5 and can
    # be set on any day.
    good_day: Optional[bool] = None
    day_rating: Optional[int] = None
    day_notes: Optional[str] = None

    @field_validator("good_day")
    @classmethod
    def good_day_true_or_none(cls, value: Optional[bool]) -> Optional[bool]:
        return True if value else None

    @field_validator("day_rating")
    @classmethod
    def valid_day_rating(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and not 1 <= value <= 5:
            raise ValueError("day_rating must be between 1 and 5")
        return value

    @field_validator("day_notes")
    @classmethod
    def blank_notes_to_none(cls, value: Optional[str]) -> Optional[str]:
        return value if value and value.strip() else None

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
    # Freeform, optional -- anything the time/where/response fields don't
    # capture (e.g. what was going on right before, how she reacted after).
    notes: Optional[str] = None

    @field_validator("response")
    @classmethod
    def valid_response(cls, value: str) -> str:
        cleaned = (value or "").strip().lower()
        if cleaned not in ALLOWED_WETTING_RESPONSES:
            raise ValueError(f"response must be one of {sorted(ALLOWED_WETTING_RESPONSES)}")
        return cleaned


class MedicationIn(BaseModel):
    name: str


class MedicationVisibilityIn(BaseModel):
    """Hide/unhide a medication in the picker. Hidden meds are never
    deleted -- their historical doses keep rendering as normal."""
    name: str
    active: bool


class MedicationDoseIn(BaseModel):
    """A taken dose of one or more medications at the same time. Any number
    per day, mirroring wetting incidents.

    Only taken doses get logged (no "skipped" entry), so a day with nothing
    logged is ambiguous -- a missed dose looks identical to a day nobody
    opened the app. Insights built on this data must treat no-dose-logged as
    missing, not as skipped.
    """
    entry_date: date
    taken_time: Optional[time] = None
    # Free text, not an FK into medications -- dose lives in the name (e.g.
    # "Methylphenidate 10mg"), so a dose change is a new medication rather
    # than a rename, keeping history accurate.
    # One or more, for meds taken together at the same time.
    medications: List[str]
    notes: Optional[str] = None
    # True = deliberately not taken. Recorded so "skipped" and "never
    # logged" stop looking identical.
    skipped: bool = False
    # Was taken_time actually observed/entered (True), or carried over from a
    # previous day by "same as previous day" (False)? None = unknown (doses
    # logged before this existed) or no time at all. Dose-timing analysis
    # should only trust True.
    time_confirmed: Optional[bool] = None

    @field_validator("medications")
    @classmethod
    def clean_medications(cls, value: List[str]) -> List[str]:
        deduped = _clean_tag_list(value)
        if not deduped:
            raise ValueError("At least one medication is required")
        return deduped


class GapsOkIn(BaseModel):
    """Mark one or more days as "nothing more to add" (or undo that), so
    gaps that can't be filled in stop being flagged as missing."""
    dates: List[date]
    ok: bool = True

    @field_validator("dates")
    @classmethod
    def dates_not_empty(cls, value: List[date]) -> List[date]:
        if not value:
            raise ValueError("At least one date is required")
        if len(value) > 400:
            raise ValueError("Too many dates")
        return value


class EventCategoryIn(BaseModel):
    name: str


class ContextEventIn(BaseModel):
    """A dated context-log event: one day (end_date omitted) or a span of
    days (start_date..end_date, inclusive)."""
    start_date: date
    end_date: Optional[date] = None
    category: str
    description: Optional[str] = None

    @field_validator("category")
    @classmethod
    def category_not_empty(cls, value: str) -> str:
        cleaned = (value or "").strip().lower()
        if not cleaned:
            raise ValueError("category is required")
        return cleaned

    @field_validator("description")
    @classmethod
    def blank_description_to_none(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value and value.strip() else None

    @model_validator(mode="after")
    def end_not_before_start(self):
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date can't be before start_date")
        if self.end_date == self.start_date:
            self.end_date = None
        return self
