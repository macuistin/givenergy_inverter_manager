# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""Dynamic price files: the day-file format and its index, which depend on `lib` alone.

Kept apart from `test_prices.py`, whose update and feed tests need `scripts/`, so a project that
copies `lib/tariffstore` can copy these tests with it.
"""
from __future__ import annotations

import json
import unittest
from datetime import date

from custom_components.givenergy_inverter_manager.lib.tariffstore import prices as fmt


def doc(day="2026-11-17", count=48, **more) -> dict:
    base = {"schema": 1, "feed": "octopus-agile", "area": "a", "date": day, "timezone": "Europe/London",
            "interval_minutes": 30, "prices": ["0.2"] * count}
    base.update(more)
    return base


class Format(unittest.TestCase):
    def test_a_good_day_has_no_errors(self) -> None:
        self.assertEqual(fmt.validate_day(doc()), [])

    def test_clock_changes_have_a_different_number_of_prices(self) -> None:
        self.assertEqual(fmt.slots_in_day(date(2026, 3, 29), "Europe/London", 30), 46)
        self.assertEqual(fmt.slots_in_day(date(2026, 10, 25), "Europe/London", 30), 50)
        self.assertEqual(fmt.validate_day(doc("2026-10-25", 50)), [])
        self.assertTrue(fmt.validate_day(doc("2026-10-25", 48)))

    def test_every_refusal(self) -> None:
        cases = {
            "not an object": [],
            "unknown field": {**doc(), "extra": 1},
            "missing field": {k: v for k, v in doc().items() if k != "area"},
            "schema": doc(schema=2),
            "slug": doc(feed="Bad Feed"),
            "interval": doc(interval_minutes=20),
            "date": doc(day="2026-13-01"),
            "date shape": doc(day="17/11/2026"),
            "zone": doc(timezone="Nowhere/Land"),
            "decimals": doc(prices=[0.2] * 48),
            "count": doc(count=47),
            "range": doc(prices=["0.2"] * 47 + ["20"]),
        }
        for name, bad in cases.items():
            with self.subTest(name):
                self.assertTrue(fmt.validate_day(bad))

    def test_paths_and_the_index(self) -> None:
        self.assertEqual(fmt.day_path("GB", "octopus-agile", "a", "2026-11-07"), "gb/octopus-agile/a/2026/11/07.json")
        self.assertEqual(fmt.index_path("GB", "octopus-agile", "a"), "gb/octopus-agile/a/index.json")
        index = fmt.feed_index("octopus-agile", "a", {"2026-10-31": "sha256:a", "2026-11-01": "sha256:b",
                                                      "2026-11-02": "sha256:c"})
        self.assertEqual((index["latest"], sorted(index["months"])), ("2026-11-02", ["2026-10", "2026-11"]))
        self.assertEqual(fmt.feed_index("f", "a", {})["latest"], None)
        self.assertNotEqual(fmt.month_checksum({"2026-11-01": "sha256:b"}), fmt.month_checksum({"2026-11-01": "sha256:x"}))

    def test_a_file_is_written_one_price_to_a_line(self) -> None:
        text = fmt.dumps_day(doc(count=2))
        self.assertEqual(json.loads(text)["prices"], ["0.2", "0.2"])
        self.assertIn('  "prices": [\n    "0.2",\n    "0.2"\n  ]\n}\n', text)


class FormatDocExample(unittest.TestCase):
    def test_the_day_and_index_in_the_format_doc(self) -> None:
        """docs/format.md, "An example day file": the day validates and gives that index."""
        day = doc("2026-11-16", feed="agile", area="c", prices=["0.10"] * 16 + ["0.30"] * 32)
        self.assertEqual(fmt.validate_day(day), [])
        self.assertEqual(fmt.day_path("GB", "agile", "c", "2026-11-16"), "gb/agile/c/2026/11/16.json")
        index = fmt.feed_index("agile", "c", {"2026-11-16": fmt.day_checksum(fmt.dumps_day(day))})
        self.assertEqual(index["months"]["2026-11"],
                         "sha256:c993b4baff37bda61075e95e3f07549b052a46b8688ef16ad5bc8d40b012643e")
