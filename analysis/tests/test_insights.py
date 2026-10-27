"""Tests on synthetic data only -- this repo is public, never put real export rows here."""
import json
import unittest

import pandas as pd

from tracker_analysis import Overrides, Params, build, load_tables, phase_line
from test_transform import C_COLS, D_COLS, E_COLS, M_COLS, W_COLS, df


def raw(ratings, doses=()):
    """Days from 2026-03-01 with the given ratings ("" = unrated, "g" = good-day only)."""
    days = []
    for i, r in enumerate(ratings):
        d = f"2026-03-{i + 1:02d}"
        days.append([d, "true" if r == "g" else "", "" if r in ("", "g") else r, "", "", "", "", "", "", "", ""])
    return {
        "entries": df([["1", "2026-03-02", "09:00:00", "defiant", "home", "", "3", "", "", "A",
                        "2026-03-02 14:00:00+00:00"]], E_COLS),
        "daily": df(days, D_COLS),
        "wetting_incidents": df([], W_COLS),
        "context_events": df([["1", "2026-03-03", "2026-03-04", "illness", "cold", "2026-03-03 00:00:00+00:00"],
                              ["2", "2026-02-01", "", "illness", "", "2026-02-01 00:00:00+00:00"]], C_COLS),
        "medication_doses": df(list(doses), M_COLS),
    }


class PhaseLineTests(unittest.TestCase):
    def phase(self, ratings, through, partial=None, doses=()):
        res = build(raw(ratings, doses), Overrides(), Params(through=through))
        return phase_line(res, partial_day=partial)

    def test_matches_centred_rolling_mean(self):
        ratings = ["2", "3", "g", "5", "1", "", "4", "3"]
        out = self.phase(ratings, "2026-03-08")
        filled = pd.Series([2, 3, 4, 5, 1, None, 4, 3], dtype=float)
        expect = filled.rolling(7, center=True, min_periods=4).mean().round(2)
        got = [d["mean"] for d in out["days"]]
        self.assertEqual(got, [None if pd.isna(v) else v for v in expect])

    def test_with_and_without_imputed(self):
        out = self.phase(["g", "g", "g", "2", "g", "g", "g"], "2026-03-07")
        mid = out["days"][3]
        self.assertEqual(mid["mean"], round((4 * 6 + 2) / 7, 2))
        self.assertIsNone(mid["mean_rated"])  # one real rating < 4 needed
        self.assertTrue(out["days"][0]["imputed"])
        self.assertEqual(out["summary"], {"rated_days": 1, "imputed_days": 6,
                                          "first_day": "2026-03-01", "last_day": "2026-03-07"})

    def test_starts_at_first_rating_and_clips_events(self):
        out = self.phase(["", "", "3", "3"], "2026-03-04")
        self.assertEqual(out["days"][0]["date"], "2026-03-03")
        self.assertEqual(out["events"], [{"start": "2026-03-03", "end": "2026-03-04",
                                          "category": "illness", "description": "cold"}])

    def test_no_ratings_is_empty_not_error(self):
        out = self.phase(["", ""], "2026-03-02")
        self.assertEqual(out["days"], [])
        json.dumps(out)

    def test_partial_day_drops_spurious_stop(self):
        doses = [["1", "2026-03-01", "08:00:00", "", "drugA 1mg", "false", "", "2026-03-01 13:00:00+00:00"],
                 ["2", "2026-03-02", "08:00:00", "", "drugA 1mg", "false", "", "2026-03-02 13:00:00+00:00"]]
        out = self.phase(["3", "3", "3"], "2026-03-03", partial="2026-03-03", doses=doses)
        self.assertEqual(out["med_changes"], [])  # today's dose just isn't logged yet
        self.assertTrue(out["days"][-1]["partial"])
        out = self.phase(["3", "3", "3"], "2026-03-03", doses=doses)
        self.assertEqual([m["change"] for m in out["med_changes"]], ["stopped"])

    def test_counts_and_json_safe(self):
        out = self.phase(["3", "3"], "2026-03-02")
        self.assertEqual(out["days"][1]["n_negative"], 1)
        self.assertEqual(out["days"][1]["max_intensity"], 3)
        json.dumps(out)


class LoadAndOverrideTests(unittest.TestCase):
    def test_load_tables_reads_bom_csv_as_strings(self):
        t = load_tables({"daily": "﻿entry_date,day_rating\n2026-03-01,\n".encode("utf-8")})
        self.assertEqual(list(t["daily"].columns), ["entry_date", "day_rating"])
        self.assertEqual(t["daily"].iloc[0]["day_rating"], "")
        self.assertTrue(t["entries"].empty)

    def test_from_dict(self):
        o = Overrides.from_dict({"_comment": "x", "exclude_entries": {7: "why"}}, source="env")
        self.assertEqual(o.exclude_entries, {"7": "why"})
        self.assertEqual(o.source, "env")
        with self.assertRaises(ValueError):
            Overrides.from_dict({"exclude_entry": {}})


if __name__ == "__main__":
    unittest.main()
