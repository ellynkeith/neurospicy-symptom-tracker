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

    for r in D.itertuples(index=False):
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
