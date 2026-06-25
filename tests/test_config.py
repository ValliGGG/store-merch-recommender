"""Unit tests for lib.config helpers (pure parts)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import config  # noqa: E402


class DeepMerge(unittest.TestCase):
    def test_override_wins_and_nested_merges(self):
        base = {"a": 1, "scoring": {"x": 1, "y": 2}, "paths": {"db": "d"}}
        over = {"a": 2, "scoring": {"y": 9, "z": 3}}
        out = config._deep_merge(base, over)
        self.assertEqual(out["a"], 2)
        self.assertEqual(out["scoring"], {"x": 1, "y": 9, "z": 3})  # nested deep-merged
        self.assertEqual(out["paths"], {"db": "d"})                  # untouched

    def test_does_not_mutate_base(self):
        base = {"scoring": {"x": 1}}
        config._deep_merge(base, {"scoring": {"x": 2}})
        self.assertEqual(base["scoring"]["x"], 1)


class StoreRegistry(unittest.TestCase):
    def test_config_yaml_lists_eight_stores_without_bg(self):
        stores = config.available_stores()
        self.assertNotIn("bg", stores)
        self.assertEqual(
            sorted(stores), ["ba", "cz", "hu", "mk", "pl", "ro", "rs", "sk"]
        )


class PerStoreSeasonalMerge(unittest.TestCase):
    """B6: per-store occasion maps merge onto (not replace) the Slovak base."""

    def _seasonal(self, store):
        import yaml
        raw = yaml.safe_load(config.CONFIG_FILE.read_text(encoding="utf-8"))
        return config._deep_merge(raw["defaults"], raw["stores"][store])["seasonal"]["occasion_to_season"]

    def test_cz_has_czech_and_slovak_terms(self):
        m = self._seasonal("cz")
        self.assertEqual(m.get("vánoce"), "season:christmas")   # Czech (added)
        self.assertEqual(m.get("Vianoce"), "season:christmas")  # Slovak base (kept)

    def test_borrow_stores_have_localized_christmas(self):
        for store, term in [("pl", "Boże Narodzenie"), ("mk", "Божиќ"), ("rs", "Božić")]:
            self.assertEqual(self._seasonal(store).get(term), "season:christmas", store)


if __name__ == "__main__":
    unittest.main()
