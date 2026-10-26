"""Offline regressions for unavailable historical Northern Ireland results."""
import copy
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_ni


class NorthernIrelandFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads((ROOT / "data/ni-2024.json").read_text())
        # Model runs update this file; give each test explicit source provenance.
        cls.baseline["meta"]["generated_at"] = "2026-10-25T10:00:00+00:00"
        cls.baseline["meta"].pop("results_source", None)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.path = self.data / "ni-2024.json"
        self.write_cache(self.baseline)
        for name, value in (("ROOT", self.root), ("DATA", self.data)):
            override = patch.object(build_ni, name, value)
            override.start()
            self.addCleanup(override.stop)

    def write_cache(self, payload):
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def test_http_403_and_timeout_keep_all_18_constituencies_and_warn(self):
        for error in (requests.HTTPError("403 Forbidden"), requests.Timeout("timeout")):
            with self.subTest(error=type(error).__name__):
                self.write_cache(self.baseline)
                output = io.StringIO()
                with patch.object(build_ni, "fetch_csv", side_effect=error), redirect_stdout(output):
                    self.assertEqual(build_ni.main(), 0)
                payload = json.loads(self.path.read_text())
                self.assertEqual(payload["constituencies"], self.baseline["constituencies"])
                self.assertEqual(len(payload["constituencies"]), 18)
                self.assertEqual(payload["winner_counts_2024"],
                                 {"sf": 7, "dup": 5, "sdlp": 2, "alliance": 1, "uup": 1, "tuv": 1, "ind": 1})
                self.assertEqual(payload["target_shares"]["sf"], 25.29285)
                self.assertEqual(payload["meta"]["results_source"]["status"], "validated_saved_baseline")
                self.assertEqual(payload["meta"]["results_source"]["baseline_generated_at"],
                                 self.baseline["meta"]["generated_at"])
                self.assertIn("WARNING", output.getvalue())

    def test_fallback_recomputes_current_signal_and_keeps_original_source_date(self):
        self.baseline_copy = copy.deepcopy(self.baseline)
        self.baseline_copy["target_shares"]["sf"] = 0  # Never trust old derived projections.
        self.write_cache(self.baseline_copy)
        with patch.object(build_ni, "fetch_csv", side_effect=requests.Timeout("timeout")):
            first = build_ni.build()
            self.write_cache(first)
            second = build_ni.build()
        self.assertEqual(second["target_shares"]["sf"], 25.29285)
        self.assertEqual(second["meta"]["results_source"]["baseline_generated_at"],
                         self.baseline["meta"]["generated_at"])

    def test_invalid_saved_baselines_are_rejected_without_overwriting_them(self):
        mutations = {
            "missing seat": lambda p: p["constituencies"].pop(),
            "duplicate id": lambda p: p["constituencies"][0].update(id="N05000002"),
            "wrong country": lambda p: p["constituencies"][0].update(country="England"),
            "wrong version": lambda p: p["meta"].update(version="unknown"),
            "bad total": lambda p: p["constituencies"][0].update(valid_votes=0),
            "bad votes": lambda p: p["constituencies"][0]["party_votes"].update(dup=-1),
            "wrong shares": lambda p: p["constituencies"][0]["shares"].update(dup=1),
            "nan shares": lambda p: p["constituencies"][0]["shares"].update(dup=float("nan")),
            "wrong winner": lambda p: p["constituencies"][0].update(winner2024="sf"),
            "wrong national": lambda p: p["national_2024"].update(sf=1),
            "wrong winner totals": lambda p: p["winner_counts_2024"].update(sf=6),
            "missing eligibility": lambda p: p["constituencies"][0].pop("eligible_parties"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                payload = copy.deepcopy(self.baseline)
                mutate(payload)
                self.write_cache(payload)
                before = self.path.read_bytes()
                with patch.object(build_ni, "fetch_csv", side_effect=requests.HTTPError("403 Forbidden")):
                    with self.assertRaises(RuntimeError):
                        build_ni.main()
                self.assertEqual(self.path.read_bytes(), before)

    def test_already_cached_results_preserve_source_date_after_another_rebuild(self):
        cached = copy.deepcopy(self.baseline)
        cached["meta"]["generated_at"] = "2026-10-26T11:00:00+00:00"
        cached["meta"]["results_source"] = {
            "status": "validated_saved_baseline",
            "baseline_generated_at": "2026-10-25T10:00:00+00:00",
        }
        self.write_cache(cached)
        with patch.object(build_ni, "fetch_csv", side_effect=requests.HTTPError("403 Forbidden")):
            rebuilt = build_ni.build()
        self.assertEqual(rebuilt["meta"]["results_source"]["baseline_generated_at"],
                         "2026-10-25T10:00:00+00:00")
        self.assertEqual(rebuilt["constituencies"], cached["constituencies"])

    def test_missing_or_malformed_cache_is_rejected(self):
        for content in (None, "not json", "null", "[]"):
            with self.subTest(content=content):
                if content is None:
                    self.path.unlink(missing_ok=True)
                else:
                    self.path.write_text(content)
                with patch.object(build_ni, "fetch_csv", side_effect=requests.Timeout("timeout")):
                    with self.assertRaises(RuntimeError):
                        build_ni.build()

    def test_valid_live_source_is_used_even_if_cache_is_invalid(self):
        self.path.write_text("invalid cache")
        stream = io.StringIO()
        fields = ["Country name", "ONS ID", "Constituency name", "Votes", "Party abbreviation",
                  "Party name", "Candidate first name", "Candidate surname"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for seat in self.baseline["constituencies"]:
            for party, votes in seat["party_votes"].items():
                writer.writerow(dict(zip(fields, ["Northern Ireland", seat["id"], seat["name"],
                                                votes, party, "Independent" if party == "ind" else party,
                                                "Candidate", party])))
        with patch.object(build_ni, "fetch_csv", return_value=stream.getvalue()):
            payload = build_ni.build()
        self.assertEqual(len(payload["constituencies"]), 18)
        self.assertEqual(payload["meta"]["results_source"]["status"], "downloaded")

    def test_bad_live_csv_and_programming_errors_are_not_hidden_by_cache(self):
        with patch.object(build_ni, "fetch_csv", return_value="unexpected,columns\na,b\n"):
            with self.assertRaisesRegex(RuntimeError, "Expected 18"):
                build_ni.build()
        with patch.object(build_ni, "fetch_csv", side_effect=ValueError("programming error")):
            with self.assertRaisesRegex(ValueError, "programming error"):
                build_ni.build()


if __name__ == "__main__":
    unittest.main()
