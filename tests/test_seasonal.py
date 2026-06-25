"""Unit tests for lib.seasonal (computus, windows, occasion mapping)."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import seasonal  # noqa: E402

SEASON_CFG = {
    "occasion_to_season": {
        "Vianoce": "season:christmas",
        "Veľká noc": "season:easter",
        "Valentín": "season:valentine",
    },
    "windows": {
        "season:christmas": {"from": "10-15", "to": "01-06"},
        "season:valentine": {"from": "01-20", "to": "02-14"},
        "season:easter": {"relative_to": "easter", "from_offset_weeks": -6, "to_offset_days": 7},
    },
}


class Computus(unittest.TestCase):
    def test_known_easter_dates(self):
        # Canonical Gregorian Easter Sundays
        self.assertEqual(seasonal.easter_date(2024), date(2024, 3, 31))
        self.assertEqual(seasonal.easter_date(2025), date(2025, 4, 20))
        self.assertEqual(seasonal.easter_date(2026), date(2026, 4, 5))


class StaticWindow(unittest.TestCase):
    def test_non_wrapping_window(self):
        self.assertTrue(seasonal.in_window_static(date(2026, 2, 1), "01-20", "02-14"))
        self.assertFalse(seasonal.in_window_static(date(2026, 3, 1), "01-20", "02-14"))

    def test_wrapping_window_spans_year_boundary(self):
        # christmas: 10-15 -> 01-06
        self.assertTrue(seasonal.in_window_static(date(2026, 12, 25), "10-15", "01-06"))
        self.assertTrue(seasonal.in_window_static(date(2026, 1, 3), "10-15", "01-06"))
        self.assertFalse(seasonal.in_window_static(date(2026, 7, 1), "10-15", "01-06"))


class EasterWindow(unittest.TestCase):
    def test_in_and_out_of_easter_window(self):
        # 2026 Easter = Apr 5; window = [-6 weeks, +7 days] = [Feb 22, Apr 12]
        self.assertTrue(seasonal.is_in_season("season:easter", SEASON_CFG, date(2026, 3, 15)))
        self.assertFalse(seasonal.is_in_season("season:easter", SEASON_CFG, date(2026, 5, 1)))


class IsInSeason(unittest.TestCase):
    def test_unknown_season_defaults_to_in_season(self):
        # unknown tag -> don't hide
        self.assertTrue(seasonal.is_in_season("season:nonexistent", SEASON_CFG, date(2026, 6, 1)))


class OccasionMapping(unittest.TestCase):
    def test_maps_and_dedupes(self):
        out = seasonal.occasions_to_seasons(["Vianoce", "Valentín", "Vianoce"], SEASON_CFG)
        self.assertEqual(out, ["season:christmas", "season:valentine"])

    def test_unmapped_occasion_ignored(self):
        self.assertEqual(seasonal.occasions_to_seasons(["totally-unknown"], SEASON_CFG), [])

    def test_comma_combined_value_is_split(self):
        # A single occasion value may be comma-joined (e.g. Czech data).
        cfg = {"occasion_to_season": {"vánoce": "season:christmas", "velikonoce": "season:easter"},
               "windows": SEASON_CFG["windows"]}
        out = seasonal.occasions_to_seasons(["Vánoce, Velikonoce"], cfg)
        self.assertEqual(sorted(out), ["season:christmas", "season:easter"])

    def test_case_insensitive_match(self):
        cfg = {"occasion_to_season": {"vánoce": "season:christmas"}, "windows": {}}
        self.assertEqual(seasonal.occasions_to_seasons(["VÁNOCE"], cfg), ["season:christmas"])


if __name__ == "__main__":
    unittest.main()
