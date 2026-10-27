"""Tests on synthetic data only -- this repo is public, never put real export rows here.

Run from analysis/:  python3 -m unittest discover tests
"""
import unittest

import pandas as pd

from tracker_analysis import Overrides, Params, build
from tracker_analysis.transform import parse_medication, time_block


def df(rows, cols):
    return pd.DataFrame([dict(zip(cols, r)) for r in rows], columns=cols, dtype=str)


E_COLS = ["id", "entry_date", "entry_time", "categories", "setting", "duration_minutes", "intensity",
          "situations", "notes", "logged_by", "created_at"]
D_COLS = ["entry_date", "good_day", "day_rating", "day_notes", "wake_time", "bedtime", "fell_asleep_time",
          "night_awakenings", "exercise_minutes", "exercise_type", "gaps_ok"]
W_COLS = ["id", "entry_date", "incident_time", "time_approximate", "setting", "response", "notes", "created_at"]
C_COLS = ["id", "start_date", "end_date", "category", "description", "created_at"]
M_COLS = ["id", "entry_date", "taken_time", "time_confirmed", "medications", "skipped", "notes", "created_at"]


def raw():
    return {
        "entries": df([
            ["1", "2026-01-05", "07:00:00", "defiant; good", "home", "10", "3", "told no", "", "A", "2026-01-05 15:00:00+00:00"],
            ["2", "2026-01-05", "18:00:00", "good behavior", "home", "5", "2", "", "", "", "2026-01-05 23:01:00+00:00"],
            ["3", "2026-01-06", "09:00:00", "defiant", "home", "", "", "", "", "B", "2026-01-06 20:00:00+00:00"],
            ["4", "2026-01-06", "10:00:00", "good", "home", "1", "4", "", "day summary", "B", "2026-01-06 20:00:00+00:00"],
        ], E_COLS),
        "daily": df([
            ["2026-01-05", "", "2", "", "07:00:00", "20:00:00", "20:30:00", "", "", "", ""],
            ["2026-01-06", "true", "", "", "06:30:00", "20:15:00", "", "0", "", "", ""],
            ["2026-01-07", "", "", "", "07:15:00", "", "", "", "", "", ""],
        ], D_COLS),
        "wetting_incidents": df([
            ["1", "2026-01-05", "15:00:00", "", "school", "other", "", "2026-01-05 21:00:00+00:00"],
            ["2", "2026-01-06", "19:00:00", "false", "home", "other", "", "2026-01-07 01:00:00+00:00"],
            ["3", "2026-01-07", "15:30:00", "true", "home", "other", "", "2026-02-01 01:00:00+00:00"],
        ], W_COLS),
        "context_events": df([
            ["1", "2026-01-06", "2026-01-07", "school break/day off", "", "2026-01-05 00:00:00+00:00"],
        ], C_COLS),
        "medication_doses": df([
            ["1", "2026-01-05", "07:30:00", "false", "drugA 1mg; supp", "false", "", "2026-01-05 13:00:00+00:00"],
            ["2", "2026-01-06", "07:30:00", "", "drugA 2mg", "false", "", "2026-01-06 13:00:00+00:00"],
            ["3", "2026-01-07", "", "", "drugA 2mg", "true", "", "2026-01-07 13:00:00+00:00"],
        ], M_COLS),
    }


class TransformTests(unittest.TestCase):
    def setUp(self):
        ov = Overrides(wetting_response={"2": "compliant"}, exclude_entries={"4": "day summary"},
                       pending=["decide something"])
        self.r = build(raw(), ov, Params(through="2026-01-07", other_response_cutoff="2026-01-20"))
        self.t = self.r.tables
        self.days = self.t["days"].set_index("date")

    def step(self, sid):
        return next(s for s in self.r.log if s.id == sid)

    def test_retired_category_mapped(self):
        e = self.t["entries"].set_index("id")
        self.assertEqual(e.loc["1", "categories"], ["defiant", "good behavior"])

    def test_positive_only_intensity_cleared_but_mixed_kept(self):
        e = self.t["entries"].set_index("id")
        self.assertTrue(pd.isna(e.loc["2", "intensity"]))
        self.assertEqual(e.loc["1", "intensity"], 3)

    def test_blank_intensity_is_missing_not_zero(self):
        self.assertTrue(pd.isna(self.t["entries"].set_index("id").loc["3", "intensity"]))

    def test_excluded_entry_not_counted(self):
        self.assertEqual(self.days.loc["2026-01-06", "n_entries"], 1)
        self.assertNotIn("4", set(self.t["entry_categories"]["entry_id"]))

    def test_time_default_flag(self):
        e = self.t["entries"].set_index("id")
        self.assertTrue(e.loc["2", "time_maybe_default"])    # 18:00 local, saved 18:01 local
        self.assertFalse(e.loc["1", "time_maybe_default"])

    def test_wetting_response_rules(self):
        w = self.t["wetting"].set_index("id")
        self.assertEqual(w.loc["1", "response"], "not observed")   # historic other
        self.assertEqual(w.loc["2", "response"], "compliant")      # override wins
        self.assertEqual(w.loc["3", "response"], "other")          # after cutoff: untouched

    def test_wetting_time_basis(self):
        w = self.t["wetting"].set_index("id")
        self.assertEqual(list(w["time_basis"]), ["noticed", "happened", "noticed"])
        self.assertEqual(list(w["time_basis_assumed"]), [True, False, False])

    def test_rating_imputation_flagged(self):
        self.assertEqual(self.days.loc["2026-01-06", "rating_filled"], 4.0)
        self.assertTrue(self.days.loc["2026-01-06", "rating_imputed"])
        self.assertTrue(pd.isna(self.days.loc["2026-01-07", "rating_filled"]))  # no rating, no good day

    def test_sleep(self):
        d = self.days
        self.assertEqual(d.loc["2026-01-05", "sleep_latency_min"], 30)
        self.assertAlmostEqual(d.loc["2026-01-05", "night_sleep_hr"], 10.0)        # 20:30 -> 06:30
        self.assertTrue(d.loc["2026-01-06", "night_onset_from_bedtime"])
        self.assertAlmostEqual(d.loc["2026-01-06", "night_sleep_hr"], 11.0)        # 20:15 -> 07:15
        self.assertAlmostEqual(d.loc["2026-01-06", "sleep_prev_night_hr"], 10.0)
        self.assertTrue(pd.isna(d.loc["2026-01-07", "night_sleep_hr"]))            # no bedtime: missing

    def test_night_awakenings_blank_is_missing(self):
        self.assertTrue(pd.isna(self.days.loc["2026-01-05", "night_awakenings"]))
        self.assertEqual(self.days.loc["2026-01-06", "night_awakenings"], 0)

    def test_med_change_detected_and_skip_is_not_a_change(self):
        mc = self.t["med_changes"]
        a = mc[mc["drug"] == "drugA"]
        self.assertEqual(a[["date", "change", "from", "to"]].values.tolist(), [["2026-01-06", "changed", "1mg", "2mg"]])
        self.assertTrue(self.days.loc["2026-01-06", "med_change"])
        self.assertTrue(pd.isna(self.days.loc["2026-01-07", "dose_druga"]))       # skipped: no amount taken
        self.assertEqual(self.days.loc["2026-01-07", "n_skipped_doses"], 1)
        supp = mc[mc["drug"] == "supp"]
        self.assertEqual(supp["change"].tolist(), ["stopped"])

    def test_context_inclusive_and_school_day(self):
        d = self.days
        self.assertTrue(d.loc["2026-01-05", "is_school_day"])     # Monday
        self.assertFalse(d.loc["2026-01-06", "is_school_day"])    # break
        self.assertFalse(d.loc["2026-01-07", "is_school_day"])    # break end date is inclusive

    def test_log_and_pending(self):
        self.assertEqual(self.step("W01b").rows, 1)
        self.assertEqual(self.r.pending, ["decide something"])
        self.assertEqual(len({s.id for s in self.r.log}), len(self.r.log))


class HelperTests(unittest.TestCase):
    def test_parse_medication(self):
        self.assertEqual(parse_medication("methylphenidate 18mg (long-acting)"),
                         {"drug": "methylphenidate", "amount": 18.0, "unit": "mg", "formulation": "long-acting"})
        self.assertEqual(parse_medication("syrup 10mls")["unit"], "ml")
        self.assertTrue(pd.isna(parse_medication("l-theanine/magnesium")["amount"]))

    def test_time_block(self):
        self.assertEqual(time_block(pd.Series([7 * 60, 8 * 60 + 30, 15 * 60, 21 * 60])).tolist(),
                         ["early_morning", "midday", "afternoon", "bedtime"])


class OverridesTests(unittest.TestCase):
    def test_unknown_key_rejected(self):
        import json, tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"wetting_responses": {}}, f)
        try:
            with self.assertRaises(ValueError):
                Overrides.load(f.name)
        finally:
            os.unlink(f.name)

    def test_missing_file_is_empty(self):
        self.assertEqual(Overrides.load("/nonexistent.json").source, "(none)")


if __name__ == "__main__":
    unittest.main()
