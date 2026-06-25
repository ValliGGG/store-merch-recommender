"""Tests for external-warehouse tiering (own > external-only > OOS)."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("_bs_test", ROOT / "scripts" / "03b_compute_bestsellers.py")
bs = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(bs)


class StockTier(unittest.TestCase):
    META = {
        "own": {"own_available": 1, "external_only": 0, "total_inventory": 5},
        "ext": {"own_available": 0, "external_only": 1, "total_inventory": 99},
        "oos": {"own_available": 0, "external_only": 0, "total_inventory": 0},
    }

    def test_tier_values(self):
        self.assertEqual(bs.stock_tier(self.META, "own"), 0)
        self.assertEqual(bs.stock_tier(self.META, "ext"), 1)
        self.assertEqual(bs.stock_tier(self.META, "oos"), 2)

    def test_in_stock_means_own_only(self):
        self.assertTrue(bs._in_stock(self.META, "own"))
        self.assertFalse(bs._in_stock(self.META, "ext"))   # external is NOT pinnable
        self.assertFalse(bs._in_stock(self.META, "oos"))

    def test_external_sorts_below_own_even_with_higher_score(self):
        scores = {"own": 1.0, "ext": 999.0}
        ranked = sorted(["ext", "own"], key=lambda p: (bs.stock_tier(self.META, p), -scores[p]))
        self.assertEqual(ranked, ["own", "ext"])   # own-stock always first

    def test_pre_migration_fallback_treats_inventory_as_own(self):
        meta = {"x": {"total_inventory": 3}}  # no own_available column yet
        self.assertEqual(bs.stock_tier(meta, "x"), 0)
        self.assertTrue(bs._in_stock(meta, "x"))


if __name__ == "__main__":
    unittest.main()
