"""Turn raw export tables into analysis tables, one documented step at a time.

Every change to the data is a step with an id (E01, W02, ...), a title and
the reason for it. Each build records how many rows every step touched, so
the transformation log doubles as the audit trail for the analysis.

Generic rules live here (public). Anything about a specific record lives in
the private overrides file (see overrides.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .overrides import Overrides

POSITIVE = {"good behavior"}
RETIRED_CATEGORY_MAP = {"good": "good behavior"}  # "good" was retired in favour of "good behavior"
SCHOOL_BREAK = "school break/day off"

# Clock blocks used for time-of-day analysis. Dose times are only trusted to
# about an hour, so analysis should work at this level, not minute level.
TIME_BLOCKS = [  # (label, start "HH:MM") -- each block runs until the next one starts
    ("night", "00:00"),
    ("early_morning", "05:00"),   # wake-up, AM dose, getting out the door
    ("midday", "08:30"),          # school hours on school days
    ("afternoon", "14:00"),       # pickup / bus / after school
    ("evening", "16:30"),
    ("bedtime", "19:30"),
]
# Labels are clock-based on purpose; combine with days.is_school_day for context.


@dataclass
class Params:
    impute_good_day_rating: float = 4.0       # D02
    other_response_cutoff: str = "2026-10-21"  # W01: "other" logged before this date -> "not observed"
    local_tz: str = "America/New_York"
    time_default_until: str = "2026-10-16"     # E06: entry time defaulted to "now" before this date
    time_default_window_min: float = 3.0       # E06
    latency_implausible_min: float = 120.0     # D03
    through: str | None = None                 # last complete day; None -> inferred (D01)


@dataclass
class StepRecord:
    id: str
    title: str
    why: str
    rows: int
    detail: str = ""


@dataclass
class Result:
    tables: dict[str, pd.DataFrame]
    log: list[StepRecord] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    params: Params = field(default_factory=Params)
    overrides_source: str = "(none)"


# ---------------------------------------------------------------- helpers

def _clock_min(s: pd.Series) -> pd.Series:
    """'HH:MM[:SS]' -> minutes after midnight (float); blank -> NaN."""
    def f(v):
        if not isinstance(v, str) or not v.strip():
            return np.nan
        h, m, *_ = v.split(":")
        return int(h) * 60 + int(m)
    return s.map(f).astype(float)


def _block_starts() -> list[tuple[str, int]]:
    return [(lab, int(t[:2]) * 60 + int(t[3:])) for lab, t in TIME_BLOCKS]


def time_block(minutes: pd.Series) -> pd.Series:
    starts = _block_starts()
    def f(m):
        if pd.isna(m):
            return None
        lab = starts[0][0]
        for name, s in starts:
            if m >= s:
                lab = name
        return lab
    return minutes.map(f)


def _split(v: str) -> list[str]:
    return [x.strip() for x in v.split(";") if x.strip()] if isinstance(v, str) else []


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.replace("", np.nan), errors="coerce")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


_MED_RE = re.compile(r"^(?P<drug>.+?)\s+(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>mg|mcg|mls?|g)\b\s*(?:\((?P<form>[^)]*)\))?\s*$", re.I)


def parse_medication(name: str) -> dict:
    """'methylphenidate 10mg (short-acting)' -> drug, amount, unit, formulation."""
    m = _MED_RE.match(name.strip())
    if not m:
        return {"drug": name.strip(), "amount": np.nan, "unit": None, "formulation": None}
    unit = m["unit"].lower()
    unit = "ml" if unit.startswith("ml") else unit
    return {"drug": m["drug"].strip(), "amount": float(m["amount"]), "unit": unit, "formulation": m["form"]}


# ---------------------------------------------------------------- build

class _Builder:
    def __init__(self, raw: dict[str, pd.DataFrame], ov: Overrides, p: Params, export_name: str | None):
        self.raw, self.ov, self.p, self.export_name = raw, ov, p, export_name
        self.log: list[StepRecord] = []
        self.pending = list(ov.pending)
        self.t: dict[str, pd.DataFrame] = {}

    def rec(self, id, title, why, rows, detail=""):
        self.log.append(StepRecord(id, title, why, int(rows), detail))

    def local(self, s: pd.Series) -> pd.Series:
        return pd.to_datetime(s.replace("", np.nan), utc=True, format="ISO8601").dt.tz_convert(self.p.local_tz)

    # ---- entries
    def entries(self):
        e = self.raw["entries"].copy()
        if e.empty:
            self.t["entries"] = e
            self.t["entry_categories"] = pd.DataFrame(columns=["entry_id", "entry_date", "category"])
            return
        e["categories_raw"] = e["categories"]
        e["categories"] = e["categories"].map(_split)
        e["situations"] = e["situations"].map(_split)
        self.rec("E01", "Split categories and situations into lists",
                 "The export stores multi-select fields as '; '-joined text.", len(e))

        cmap = {**RETIRED_CATEGORY_MAP, **self.ov.category_map}
        changed = e["categories"].map(lambda cs: any(c in cmap for c in cs))
        e["categories"] = e["categories"].map(lambda cs: list(dict.fromkeys(cmap.get(c, c) for c in cs)))
        self.rec("E02", "Map retired categories",
                 "Retired names (e.g. 'good') are merged into their current equivalent so counts aren't split.",
                 changed.sum(), f"mapping: {cmap}")

        e["excluded"] = e["id"].isin(self.ov.exclude_entries)
        e["exclude_reason"] = e["id"].map(self.ov.exclude_entries)
        self.rec("E03", "Flag entries excluded by private overrides",
                 "Some records aren't behavior events (e.g. a day summary logged as an entry). "
                 "Flagged rather than deleted so they can be inspected.", e["excluded"].sum())

        e["positive_only"] = e["categories"].map(lambda cs: bool(cs) and all(c in POSITIVE for c in cs))
        e["intensity"] = _num(e["intensity"])
        e["duration_minutes"] = _num(e["duration_minutes"])
        n_pos = (e["positive_only"] & e["intensity"].notna()).sum()
        e.loc[e["positive_only"], "intensity"] = np.nan
        self.rec("E04", "Clear intensity on positive-only entries",
                 "Intensity is a severity scale for negative behavior; positive entries logged before "
                 "'n/a' existed carry a meaningless value.", n_pos)

        neg = ~e["positive_only"]
        e["logged_by"] = e["logged_by"].replace("", np.nan)
        miss = {
            "intensity": int((neg & e["intensity"].isna()).sum()),
            "duration_minutes": int(e["duration_minutes"].isna().sum()),
            "logged_by": int(e["logged_by"].isna().sum()),
            "situations": int((neg & (e["situations"].map(len) == 0)).sum()),
        }
        self.rec("E05", "Blank fields are missing, never zero",
                 "A blank intensity/duration means 'not recorded'. Trigger analysis uses only entries "
                 "with a situation tagged.", sum(miss.values()), f"missing counts: {miss}")

        e["time_min"] = _clock_min(e["entry_time"])
        e["time_block"] = time_block(e["time_min"])
        created = self.local(e["created_at"])
        stated = pd.to_datetime(e["entry_date"] + " " + e["entry_time"]).dt.tz_localize(self.p.local_tz)
        gap = (created - stated).abs().dt.total_seconds() / 60
        before = created < pd.Timestamp(self.p.time_default_until, tz=self.p.local_tz)
        e["time_maybe_default"] = before & (gap <= self.p.time_default_window_min)
        self.rec("E06", "Flag entry times that may be an unchanged 'now' default",
                 f"Before {self.p.time_default_until} the time field defaulted to the save time. A time "
                 f"within {self.p.time_default_window_min:g} min of saving is either live logging or an "
                 "untouched default -- down-weight in time-of-day analysis.", e["time_maybe_default"].sum())

        long = e.loc[~e["excluded"], ["id", "entry_date", "categories", "positive_only"]].explode("categories")
        long = long.rename(columns={"id": "entry_id", "categories": "category"}).dropna(subset=["category"])
        self.rec("E07", "Multi-label category table",
                 "About half of entries have several categories. entry_categories has one row per "
                 "(entry, category) for per-category questions; day-level counts use entries once each.",
                 len(long))
        self.t["entries"] = e
        self.t["entry_categories"] = long.reset_index(drop=True)

    # ---- wetting
    def wetting(self):
        w = self.raw["wetting_incidents"].copy()
        if w.empty:
            self.t["wetting"] = w
            return
        w["response_raw"] = w["response"]
        ov = w["id"].map(self.ov.wetting_response)
        w.loc[ov.notna(), "response"] = ov[ov.notna()]
        self.rec("W01a", "Apply per-incident response overrides",
                 "Where the notes show how she actually responded.", ov.notna().sum())
        created = self.local(w["created_at"])
        cutoff = pd.Timestamp(self.p.other_response_cutoff, tz=self.p.local_tz)
        rule = ov.isna() & (w["response"] == "other") & (created < cutoff)
        w.loc[rule, "response"] = "not observed"
        self.rec("W01b", "Historic 'other' responses -> 'not observed'",
                 f"Before {self.p.other_response_cutoff}, 'other' was used almost entirely for incidents "
                 "nobody saw. Later uses of 'other' are left alone.", rule.sum())

        ta = w["time_approximate"].str.lower()
        w["time_basis"] = np.select([ta == "true", ta == "false"], ["noticed", "happened"], "noticed")
        w["time_basis_assumed"] = ~ta.isin(["true", "false"])
        self.rec("W02", "Unknown time basis -> 'noticed'",
                 "If we don't know whether the time is when it happened or when it was noticed, assume "
                 "noticed: the event happened at or before that time. Biases timing later, never earlier.",
                 w["time_basis_assumed"].sum())

        w["time_min"] = _clock_min(w["incident_time"])
        w["time_block"] = time_block(w["time_min"])
        w["excluded"] = w["id"].isin(self.ov.wetting_exclude)
        w["exclude_reason"] = w["id"].map(self.ov.wetting_exclude)
        self.rec("W03", "Flag incidents excluded by private overrides",
                 "E.g. overnight accidents, which likely have different drivers from daytime wetting.",
                 w["excluded"].sum())
        self.t["wetting"] = w

    # ---- medications
    def doses(self):
        m = self.raw["medication_doses"].copy()
        if m.empty:
            self.t["doses"] = m
            self.t["med_changes"] = pd.DataFrame(columns=["date", "drug", "change", "from", "to"])
            return
        m["medication"] = m["medications"].map(_split)
        d = m.explode("medication").dropna(subset=["medication"])
        parsed = pd.DataFrame([parse_medication(x) for x in d["medication"]], index=d.index)
        d = pd.concat([d, parsed], axis=1)
        d["skipped"] = d["skipped"].str.lower() == "true"
        d["time_confirmed"] = d["time_confirmed"].str.lower().map({"true": True, "false": False})
        self.rec("M01", "One row per medication per dose",
                 "A single dose record can list several medications; each is parsed into drug, amount, "
                 "unit and formulation.", len(d))

        d["time_min"] = _clock_min(d["taken_time"])
        d["time_block"] = time_block(d["time_min"])
        self.rec("M02", "Dose times trusted at clock-block level",
                 "Decision 2026-10-19: logged times are the best available (weekday AM doses are given at "
                 "school). Unconfirmed and backfilled times are kept, but analysis uses time_block or "
                 "hour-level, not minutes.", d["time_confirmed"].ne(True).sum(),
                 f"confirmed={int(d['time_confirmed'].eq(True).sum())}, "
                 f"unconfirmed={int(d['time_confirmed'].eq(False).sum())}, unknown={int(d['time_confirmed'].isna().sum())}")

        # regimen = set of (amount, unit, formulation) recorded for a drug on a day (skipped included:
        # a skipped dose still says what the regimen was). A day whose set is a strict subset of the
        # running regimen is treated as incomplete logging, not a change.
        changes = []
        for drug, g in d.groupby("drug"):
            by_day = g.groupby("entry_date").apply(
                lambda x: frozenset(zip(x["amount"].fillna(-1.0), x["unit"].fillna(""), x["formulation"].fillna(""))),
                include_groups=False
            ).sort_index()
            cur = None
            for day, reg in by_day.items():
                if cur is None:
                    cur = reg
                    if day > d["entry_date"].min():
                        changes.append((day, drug, "started", "", _fmt(reg)))
                    continue
                if reg != cur and not reg < cur:
                    changes.append((day, drug, "changed", _fmt(cur), _fmt(reg)))
                    cur = reg
            last = by_day.index.max()
            if last < self.through:
                stop = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
                changes.append((stop, drug, "stopped", _fmt(cur), ""))
        mc = pd.DataFrame(changes, columns=["date", "drug", "change", "from", "to"]).sort_values("date")
        self.rec("M03", "Detect regimen changes from the dose log",
                 "Dose changes are prime suspects for phase shifts. Deriving them from the dose log means "
                 "they're marked even when no context event was added.", len(mc))
        self.t["doses"] = d.reset_index(drop=True)
        self.t["med_changes"] = mc.reset_index(drop=True)

    # ---- context
    def context(self):
        c = self.raw["context_events"].copy()
        rows = []
        for _, r in c.iterrows():
            end = r["end_date"] or r["start_date"]
            for dd in pd.date_range(r["start_date"], end):
                rows.append({"date": dd.date().isoformat(), "category": r["category"],
                             "description": r["description"] or None, "event_id": r["id"]})
        cd = pd.DataFrame(rows, columns=["date", "category", "description", "event_id"])
        self.rec("C01", "Expand context events to one row per day",
                 "Start and end dates are inclusive; a blank end date means a single day.", len(cd),
                 f"{int((c['description'] == '').sum()) if len(c) else 0} events have no description")
        self.t["context_days"] = cd

    # ---- days
    def infer_through(self) -> str:
        if self.p.through:
            return self.p.through
        if self.export_name:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", self.export_name)
            if m:
                return (date.fromisoformat(m[1]) - timedelta(days=1)).isoformat()
        stamps = pd.concat([self.local(t["created_at"]) for t in self.raw.values() if "created_at" in t and len(t)])
        return (stamps.max().date() - timedelta(days=1)).isoformat()

    def days(self):
        dl = self.raw["daily"].copy()
        starts = [t["entry_date"].min() for k, t in self.raw.items() if "entry_date" in t and len(t)]
        start = min(starts)
        idx = [x.date().isoformat() for x in pd.date_range(start, self.through)]
        D = pd.DataFrame({"date": idx})
        D["weekday"] = pd.to_datetime(D["date"]).dt.day_name()
        dl = dl.rename(columns={"entry_date": "date"})
        D = D.merge(dl, on="date", how="left").fillna({c: "" for c in dl.columns if c != "date"})
        self.rec("D01", "One row per complete day",
                 "The day of the export is partial and dropped; days with no daily record still get a row.",
                 len(D), f"{start} -> {self.through}")

        D["good_day"] = D["good_day"].str.lower() == "true"
        D["rating"] = _num(D["day_rating"])
        imp = D["rating"].isna() & D["good_day"]
        D["rating_filled"] = D["rating"].where(~imp, self.p.impute_good_day_rating)
        D["rating_imputed"] = imp
        self.rec("D02", f"Good-day-only days -> rating {self.p.impute_good_day_rating:g} (flagged)",
                 "Decision 2026-10-19: dropping them would bias the phase line toward bad days, since most "
                 "are calm September backfill. Every result should be checked with and without imputed days.",
                 imp.sum())

        bed = _clock_min(D["bedtime"]); bed = bed.where(bed >= 12 * 60, bed + 1440)
        fell = _clock_min(D["fell_asleep_time"]); fell = fell.where(fell >= 12 * 60, fell + 1440)
        # next morning's wake time, looked up in the raw daily table so the last night isn't lost
        wake_by_date = dict(zip(dl["date"], _clock_min(dl["wake_time"])))
        nxt = [(date.fromisoformat(x) + timedelta(days=1)).isoformat() for x in D["date"]]
        wake_next = pd.Series([wake_by_date.get(n, np.nan) for n in nxt], index=D.index) + 1440
        excl = D["date"].isin(self.ov.sleep_exclude)
        bed[excl] = np.nan; fell[excl] = np.nan
        D["bedtime_min"] = bed
        D["fell_asleep_min"] = fell
        D["wake_min"] = _clock_min(D["wake_time"])
        D["sleep_latency_min"] = fell - bed
        onset = fell.fillna(bed)
        D["night_sleep_hr"] = (wake_next - onset) / 60
        D["night_onset_from_bedtime"] = fell.isna() & bed.notna()
        D["sleep_prev_night_hr"] = D["night_sleep_hr"].shift(1)
        D["sleep_implausible"] = (D["sleep_latency_min"] > self.p.latency_implausible_min) | (D["sleep_latency_min"] < 0)
        self.rec("D03", "Sleep: missing stays missing; derive latency and duration",
                 "Decision 2026-10-21: unremembered sleep times are not filled. Night D = bedtime D -> wake "
                 "D+1; when fell-asleep is blank, bedtime is used as onset (flagged). sleep_prev_night_hr is "
                 "the lagged predictor for day D.", int(D["night_sleep_hr"].isna().sum()),
                 f"implausible latency on {D.loc[D['sleep_implausible'], 'date'].tolist()}; "
                 f"excluded by override: {D.loc[excl, 'date'].tolist()}")

        D["night_awakenings"] = _num(D["night_awakenings"])
        self.rec("D04", "Night awakenings: blank is missing, not 0",
                 "Before the 'None' chip a blank meant 'none OR not recorded'.",
                 int(D["night_awakenings"].isna().sum()))

        # aggregates
        e = self.t["entries"]
        e = e[~e["excluded"]] if len(e) else e
        neg = e[~e["positive_only"]] if len(e) else e
        D = D.merge(e.groupby("entry_date").size().rename("n_entries"), left_on="date", right_index=True, how="left")
        D = D.merge(neg.groupby("entry_date").agg(n_negative=("id", "size"), max_intensity=("intensity", "max"),
                                                  negative_minutes=("duration_minutes", "sum")),
                    left_on="date", right_index=True, how="left")
        D = D.merge(e[e["positive_only"]].groupby("entry_date").size().rename("n_positive"),
                    left_on="date", right_index=True, how="left") if len(e) else D
        w = self.t["wetting"]
        w = w[~w["excluded"]] if len(w) else w
        D = D.merge(w.groupby("entry_date").size().rename("n_wetting"), left_on="date", right_index=True, how="left")
        for c in ["n_entries", "n_negative", "n_positive", "n_wetting", "negative_minutes"]:
            if c in D:
                D[c] = D[c].fillna(0)

        dz = self.t["doses"]
        if len(dz):
            taken = dz[~dz["skipped"]]
            tot = taken.pivot_table(index="entry_date", columns="drug", values="amount", aggfunc="sum")
            tot.columns = [f"dose_{_slug(c)}" for c in tot.columns]
            D = D.merge(tot, left_on="date", right_index=True, how="left")
            D = D.merge(dz[dz["skipped"]].groupby("entry_date").size().rename("n_skipped_doses"),
                        left_on="date", right_index=True, how="left").fillna({"n_skipped_doses": 0})
        mc = self.t["med_changes"]
        D["med_change"] = D["date"].isin(mc["date"])
        D["med_change_desc"] = D["date"].map(
            mc.assign(s=mc["drug"] + " " + mc["change"] + " " + mc["from"] + "->" + mc["to"])
              .groupby("date")["s"].agg("; ".join))
        last = None; since = []
        for dt, ch in zip(D["date"], D["med_change"]):
            if ch:
                last = dt
            since.append((date.fromisoformat(dt) - date.fromisoformat(last)).days if last else np.nan)
        D["days_since_med_change"] = since

        cd = self.t["context_days"]
        for cat in sorted(cd["category"].unique()):
            D[f"ctx_{_slug(cat)}"] = D["date"].isin(cd.loc[cd["category"] == cat, "date"])
        D["ctx_desc"] = D["date"].map(cd.dropna(subset=["description"]).groupby("date")["description"].agg("; ".join))
        brk = D.get(f"ctx_{_slug(SCHOOL_BREAK)}", pd.Series(False, index=D.index))
        D["is_school_day"] = ~D["weekday"].isin(["Saturday", "Sunday"]) & ~brk
        D["imputed_no_entries"] = D["rating_imputed"] & (D["n_entries"] == 0)
        self.rec("D05", "Join entries, wetting, doses and context onto days",
                 "Excluded records are left out of counts. imputed_no_entries marks days where 'good day' and "
                 "'no entries' are the same backfilled fact, not two independent signals. is_school_day = "
                 "weekday and no school-break context event.", len(D))
        drop = ["day_rating", "wake_time", "bedtime", "fell_asleep_time"]
        self.t["days"] = D.drop(columns=[c for c in drop if c in D])

    def run(self) -> Result:
        self.through = self.infer_through()
        self.entries()
        self.wetting()
        self.doses()
        self.context()
        self.days()
        return Result(self.t, self.log, self.pending, self.p, self.ov.source)


def _fmt(reg) -> str:
    parts = []
    for amount, unit, form in sorted(reg, key=lambda x: (x[2], x[0])):
        a = "" if amount < 0 else f"{amount:g}{unit}"
        parts.append(f"{a} {form}".strip() if form else a)
    return "+".join(p for p in parts if p)  # "" for drugs logged without a strength


def build(raw: dict[str, pd.DataFrame], overrides: Overrides | None = None, params: Params | None = None,
          export_name: str | None = None) -> Result:
    return _Builder(raw, overrides or Overrides(), params or Params(), export_name).run()
