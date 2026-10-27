# Analysis

Turns a tracker export (`GET /api/export`) into tidy tables for analysis, with
every data transformation written down as a named step.

## Privacy: what lives where

This repo is public. **Only code and generic rules live here.**

| Where | What |
|---|---|
| `analysis/` (public) | Loader, transformation steps, tests on synthetic data, this README |
| `Claude outputs/data/` (gitignored) | Export zips |
| `Claude outputs/analysis/overrides.json` (gitignored) | Record-specific overrides and open decisions |
| `Claude outputs/analysis/build/` (gitignored) | Built tables and the transformation log for each build |
| `Claude outputs/analysis/*.ipynb` (gitignored) | Notebooks (their outputs contain real data) |

Never commit a built table, a notebook with outputs, or a test that uses real rows.

## Run

```
cd analysis
python3 -m tracker_analysis                 # newest export in Claude outputs/data/
python3 -m tracker_analysis path/to/export.zip --through 2026-10-18
python3 -m unittest discover tests
```

Needs pandas (see `requirements.txt`). The app's requirements pin pandas too, because the Insights tab runs this package on the server.

## Output tables

| Table | One row per | Notes |
|---|---|---|
| `days` | calendar day | Outcome (`rating_filled`), sleep, counts, doses, med changes, context flags |
| `entries` | behavior entry | Cleaned; `excluded` rows kept for inspection but left out of counts |
| `entry_categories` | (entry, category) | Multi-label long table |
| `wetting` | incident | `response` cleaned, `time_basis`, `time_block` |
| `doses` | medication per dose | Parsed drug / amount / unit / formulation |
| `med_changes` | regimen change | Derived from the dose log |
| `context_days` | (day, context event) | Inclusive date ranges expanded |

Each build also writes `transformation_log.md`: every step, why it exists, how
many rows it touched, plus the pending decisions from the overrides file.

## Transformation steps

| Step | Rule | Why |
|---|---|---|
| E01 | Split `categories` / `situations` on `;` | Multi-select fields are exported as joined text |
| E02 | Retired categories mapped (`good` → `good behavior`, plus private `category_map`) | Don't split counts across old and new names |
| E03 | Entries in private `exclude_entries` flagged `excluded` | E.g. a day summary logged as an entry |
| E04 | Intensity cleared on positive-only entries | Intensity is a severity scale; old positive entries carry a meaningless value |
| E05 | Blank intensity / duration / logged-by / situation = missing, never 0 | "Not recorded" isn't "none" |
| E06 | `time_maybe_default`: entry time within 3 min of save time, before 2026-10-16 | The time field used to default to "now"; down-weight in time-of-day analysis |
| E07 | `entry_categories` long table | ~half of entries have several categories; day-level counts use each entry once |
| W01a | Private per-incident response overrides | Where the notes show the actual response |
| W01b | `other` logged before 2026-10-21 → `not observed` | Historic "other" meant nobody saw it; later uses left alone |
| W02 | Unknown happened/noticed → `noticed` (`time_basis_assumed`) | Event happened at or before the logged time; biases later, never earlier |
| W03 | Incidents in private `wetting_exclude` flagged | E.g. overnight accidents, likely different drivers |
| M01 | One row per medication per dose, parsed | A dose record can list several medications |
| M02 | Dose times kept, analysed at clock-block level | Times are best-available (weekday AM doses given at school); not minute-accurate |
| M03 | Regimen changes derived from the dose log | Marks dose changes even with no context event. A day logging a strict subset of the regimen counts as incomplete logging, not a change |
| C01 | Context events → one row per day, inclusive | Blank end date = single day |
| D01 | One row per complete day; export day dropped | Partial days distort counts |
| D02 | Good-day-only days → rating 4, `rating_imputed` | Dropping them biases toward bad days. Check every result with and without |
| D03 | Sleep: missing stays missing; latency and duration derived; implausible latency (>120 min or <0) flagged | Night D = bedtime D → wake D+1; blank fell-asleep uses bedtime as onset (flagged) |
| D04 | Blank night awakenings = missing | Before the "None" chip, blank meant "none or not recorded" |
| D05 | Join everything onto days; `is_school_day`; `imputed_no_entries` | Excluded records left out; for backfilled days "good day" and "no entries" are one fact, not two |

Clock blocks (`time_block`): night 00:00, early_morning 05:00, midday 08:30,
afternoon 14:00, evening 16:30, bedtime 19:30. Labels are clock-based; pair
with `is_school_day`.

## Overrides file

Shape documented in `tracker_analysis/overrides.py`; a fake example is in
`overrides.example.json`. Unknown keys are rejected so typos fail loudly.

## In the app (Insights tab)

`GET /api/insights` builds the same tables from the live data (the CSVs `/api/export`
would produce, read with `load_tables`) and returns `insights.phase_line(result)`:

- **Phase line**: centred 7-day mean of the day rating, needing at least 4 rated
  days in the window, with and without imputed good-day-only days (D02). Same
  definition as the notebook.
- Context events and medication changes (M03) in the plotted range.
- Today is passed as a partial day: its counts are incomplete, and a "stopped"
  medication dated today only means today's doses aren't logged yet, so it's dropped.

Overrides come from the `ANALYSIS_OVERRIDES` environment variable (the contents of
`overrides.json`). Unset means generic rules only; invalid JSON or unknown keys are
logged and ignored, and the tab shows a warning. The demo login never uses them.
