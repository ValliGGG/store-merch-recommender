"""Unit tests for lib.scoring (pure, no I/O)."""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import scoring  # noqa: E402

WEIGHTS = {"cold_start_window_days": 60, "cold_start_weight": 5}


class ColdStartBonus(unittest.TestCase):
    def test_created_today_gets_full_window_bonus(self):
        today = date(2026, 6, 25)
        iso = "2026-06-25T10:00:00Z"
        # days=0 -> (60-0)*5 = 300
        self.assertEqual(scoring.cold_start_bonus(iso, WEIGHTS, today=today), 300.0)

    def test_decays_toward_window_edge(self):
        today = date(2026, 6, 25)
        iso = (today - timedelta(days=30)).isoformat() + "T00:00:00+00:00"
        # days=30 -> (60-30)*5 = 150
        self.assertEqual(scoring.cold_start_bonus(iso, WEIGHTS, today=today), 150.0)

    def test_at_or_past_window_is_zero(self):
        today = date(2026, 6, 25)
        iso = (today - timedelta(days=60)).isoformat() + "T00:00:00+00:00"
        self.assertEqual(scoring.cold_start_bonus(iso, WEIGHTS, today=today), 0.0)
        older = (today - timedelta(days=400)).isoformat() + "T00:00:00+00:00"
        self.assertEqual(scoring.cold_start_bonus(older, WEIGHTS, today=today), 0.0)

    def test_future_created_at_is_zero(self):
        today = date(2026, 6, 25)
        iso = (today + timedelta(days=3)).isoformat() + "T00:00:00+00:00"
        self.assertEqual(scoring.cold_start_bonus(iso, WEIGHTS, today=today), 0.0)

    def test_none_and_garbage_are_zero(self):
        today = date(2026, 6, 25)
        self.assertEqual(scoring.cold_start_bonus(None, WEIGHTS, today=today), 0.0)
        self.assertEqual(scoring.cold_start_bonus("not-a-date", WEIGHTS, today=today), 0.0)


if __name__ == "__main__":
    unittest.main()
