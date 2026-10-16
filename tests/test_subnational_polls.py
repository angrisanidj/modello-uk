"""Offline regressions for the Wikipedia Westminster polling source split."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_data


SCOTLAND_PAGE = "Opinion_polling_in_Scotland_for_the_next_United_Kingdom_general_election"


def poll_table(pollster, *, country="Scotland"):
    """Small source-shaped table; values deliberately differ by party."""
    regional_party = "SNP" if country == "Scotland" else "PC"
    return f"""<table><tr><th>Date(s) conducted</th><th>Pollster</th>
    <th>Client</th><th>Sample size</th><th>Lab</th><th>{regional_party}</th>
    <th>Con</th><th>LD</th><th>Ref</th><th>Grn</th><th>Others</th></tr>
    <tr><td>18 Sep – 12 Oct 2026</td><td>{pollster}[1]</td><td>Client</td>
    <td>2,039</td><td>20%</td><td>34%</td><td>12%</td><td>8%</td>
    <td>18%</td><td>6%</td><td>2%</td></tr>
    <tr><td>13–24 Aug 2026</td><td>{pollster}</td><td>Client</td>
    <td>2,036</td><td>19%</td><td>34%</td><td>11%</td><td>8%</td>
    <td>18%</td><td>5%</td><td>5%</td></tr></table>"""


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 15, tzinfo=timezone.utc)


class SubnationalPollingTests(unittest.TestCase):
    def setUp(self):
        self.main = (
            '<h2>Sub-national poll results</h2><h3>Scotland</h3>'
            '<p>Main article: Scottish Westminster polling</p><h3>Wales</h3>'
            + poll_table("Welsh poll", country="Wales")
            + '<h3>London</h3>' + poll_table("London poll", country="Wales")
            + '<h3>Greater Manchester</h3>' + poll_table("Manchester poll", country="Wales")
            + '<h2>Individual constituency poll results</h2>' + poll_table("Constituency poll")
        )
        self.scotland = (
            '<h2>Graphical summary</h2><h2>Polls</h2>' + poll_table("Scottish poll")
            + '<h2>UK polls with Scottish sub-samples</h2><h3>2026</h3>'
            + poll_table("Scottish sub-sample")
            + '<h2>MRP polls showing results for Scotland</h2>' + poll_table("Scottish MRP")
        )
        self.pages = {build_data.POLL_PAGE: self.main, SCOTLAND_PAGE: self.scotland}
        self.clock = patch.object(build_data, "datetime", FrozenDateTime)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def fetch(self):
        def response(url, *, params):
            html = self.pages[params["page"]]
            return SimpleNamespace(json=lambda: {"parse": {"text": {"*": html}}})

        with patch.object(build_data, "get", side_effect=response):
            return build_data.fetch_subnational_polls()

    def add_legacy_scotland(self):
        self.pages[build_data.POLL_PAGE] = self.main.replace(
            '<h3>Scotland</h3>', '<h3>Scotland</h3>' + poll_table("Legacy Scottish poll")
        )

    def test_fetches_scottish_polls_from_the_dedicated_page(self):
        rows = self.fetch()
        self.assertEqual({r["pollster"] for r in rows}, {"Scottish poll", "Welsh poll"})
        row = next(r for r in rows if r["country"] == "Scotland" and r["date"] == "2026-10-12")
        self.assertEqual(
            {k: row[k] for k in ("area", "sample", "lab", "snp", "con", "ld", "ref", "green", "pc")},
            dict(area="SCOTLAND", sample=2039, lab=20, snp=34, con=12, ld=8, ref=18, green=6, pc=None),
        )

    def test_english_tables_are_never_labelled_as_welsh(self):
        self.add_legacy_scotland()
        rows = self.fetch()
        self.assertEqual([r["pollster"] for r in rows if r["country"] == "Wales"], ["Welsh poll"] * 2)

    def test_scottish_subsamples_and_mrp_are_excluded(self):
        self.add_legacy_scotland()
        rows = self.fetch()
        self.assertEqual({r["pollster"] for r in rows if r["country"] == "Scotland"}, {"Scottish poll"})

    def test_duplicate_polls_are_removed_and_dates_sorted(self):
        self.pages[SCOTLAND_PAGE] = '<h2>Polls</h2>' + poll_table("Scottish poll") * 2
        rows = self.fetch()
        self.assertEqual(len(rows), 4)
        self.assertEqual([r["date"] for r in rows], sorted([r["date"] for r in rows], reverse=True))

    def test_missing_country_or_primary_section_is_rejected(self):
        for country in ("Scotland", "Wales"):
            with self.subTest(country=country):
                pages = dict(self.pages)
                if country == "Scotland":
                    self.pages[SCOTLAND_PAGE] = '<h2>UK polls with Scottish sub-samples</h2>' + poll_table("Subsample")
                else:
                    self.pages[build_data.POLL_PAGE] = self.main.replace('<h3>Wales</h3>', '<h3>London</h3>')
                with self.assertRaisesRegex(RuntimeError, "Subnational polling parse too small"):
                    self.fetch()
                self.pages = pages

    def test_network_failure_is_not_hidden_by_incomplete_data(self):
        with patch.object(build_data, "get", side_effect=RuntimeError("source unavailable")):
            with self.assertRaisesRegex(RuntimeError, "source unavailable"):
                build_data.fetch_subnational_polls()


if __name__ == "__main__":
    unittest.main()
