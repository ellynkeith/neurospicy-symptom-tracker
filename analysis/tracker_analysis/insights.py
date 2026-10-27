"""Summaries for the app's Insights tab, built from a transform Result.

These live here (not in the app) so the app and the notebooks compute the
same thing from the same cleaned tables. Output is plain JSON-safe dicts:
NaN becomes None, dates are ISO strings.
"""
from __future__ import annotations

import math

import pandas as pd

from .transform import Result

# Phase line: same definition as the notebook -- a centred 7-day mean of the
# day rating, needing at least 4 rated days in the window, computed both with
# and without the imputed good-day-only days (decision D02).
WINDOW = 7
MIN_DAYS = 4


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "item"):  # numpy scalar -> python
        v = v.item()
        if isinstance(v, float) and math.isnan(v):
            return None
    return v


def _round(v, n=2):
    v = _clean(v)
    return round(v, n) if isinstance(v, float) else v


def phase_line(result: Result, partial_day: str | None = None) -> dict:
    """Daily ratings, the 7-day phase line, context events and med changes.

    partial_day: a day still in progress (the app passes today). Its counts are
    incomplete, and a medication "stopped" on it only means today's doses
    aren't logged yet, so those are dropped.
    """
    D = result.tables["days"].copy()
    mean_all = D["rating_filled"].rolling(WINDOW, center=True, min_periods=MIN_DAYS).mean()
    mean_rated = D["rating"].rolling(WINDOW, center=True, min_periods=MIN_DAYS).mean()
    D["mean"] = mean_all
    D["mean_rated"] = mean_rated
    # Sleep shown on day D is the night BEFORE D (bedtime D-1 -> wake D), the
    # same alignment as transform's sleep_prev_night_hr, so a rough night sits
    # under the day that followed it. Clock values are minutes after midnight
    # of D-1: bedtime/onset are already in that frame (D03), wake gets +1440.
    # Days are consecutive, so shift(1) is "the previous evening".
    prev = D[["bedtime_min", "fell_asleep_min", "sleep_latency_min", "night_sleep_hr",
              "sleep_implausible", "night_onset_from_bedtime"]].shift(1)
    wake = D["wake_min"] + 1440

    rated = D["rating_filled"].notna()
    out = {
        "window": WINDOW, "min_days": MIN_DAYS, "partial_day": partial_day,
        "days": [], "events": [], "med_changes": [],
        "summary": {"rated_days": int(D["rating"].notna().sum()),
                    "imputed_days": int(D["rating_imputed"].sum()),
                    "first_day": None, "last_day": None},
    }
    if not rated.any():
        return out

    # Start at the first day with a rating: earlier rows have nothing to plot.
    D = D.loc[rated.idxmax():]
    first, last = D["date"].iloc[0], D["date"].iloc[-1]
    out["summary"].update(first_day=first, last_day=last)

    prev = prev.loc[D.index]
    wake = wake.loc[D.index]
    for (r, (_, p), w) in zip(D.itertuples(index=False), prev.iterrows(), wake):
        sleep = None
        if pd.notna(p["bedtime_min"]) or pd.notna(p["fell_asleep_min"]) or pd.notna(w):
            sleep = {
                "bed": _clean(p["bedtime_min"]),
                "asleep": _clean(p["fell_asleep_min"]),
                "wake": _clean(w),
                "hours": _round(p["night_sleep_hr"]),
                "latency": _clean(p["sleep_latency_min"]),
                "flagged": bool(p["sleep_implausible"]) if pd.notna(p["sleep_implausible"]) else False,
                "onset_is_bedtime": bool(p["night_onset_from_bedtime"]) if pd.notna(p["night_onset_from_bedtime"]) else False,
            }
        out["days"].append({
            "date": r.date,
            "rating": _clean(r.rating_filled),
            "imputed": bool(r.rating_imputed),
            "mean": _round(r.mean),
            "mean_rated": _round(r.mean_rated),
            "n_negative": int(r.n_negative) if "n_negative" in D else 0,
            "n_positive": int(r.n_positive) if "n_positive" in D else 0,
            "max_intensity": _clean(getattr(r, "max_intensity", None)),
            "partial": r.date == partial_day,
            "sleep": sleep,  # the night before this day; None if nothing logged
        })

    cd = result.tables["context_days"]
    if len(cd):
        ev = (cd.groupby("event_id")
                .agg(start=("date", "min"), end=("date", "max"),
                     category=("category", "first"), description=("description", "first"))
                .reset_index().sort_values(["start", "event_id"]))
        ev = ev[(ev["end"] >= first) & (ev["start"] <= last)]
        out["events"] = [{"start": r.start, "end": r.end, "category": r.category,
                          "description": _clean(r.description)} for r in ev.itertuples(index=False)]

    mc = result.tables["med_changes"]
    if len(mc):
        mc = mc[(mc["date"] >= first) & (mc["date"] <= last)]
        if partial_day:
            mc = mc[~((mc["change"] == "stopped") & (mc["date"] >= partial_day))]
        out["med_changes"] = [{"date": r.date, "drug": r.drug, "change": r.change,
                               "from": r[3] or None, "to": r[4] or None}
                              for r in mc.itertuples(index=False)]
    return out
