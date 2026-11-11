# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""The indexes: derived from the files alone, and refusing a set of files that disagrees."""
from __future__ import annotations

import unittest

from custom_components.givenergy_inverter_manager.lib.tariffstore import index as idx
from custom_components.givenergy_inverter_manager.lib.tariffstore import layout
from custom_components.givenergy_inverter_manager.lib.tariffstore.schema import checksum
from .fixtures import country, export, flat, holidays, tariff

UNAVAILABLE = {"schema": 1, "countries": {"XX": {"reason": "No source", "checked": "2026-11-10"}}}


def problems(files: dict, block: dict | None = None) -> list[str]:
    return idx.problems("IE", block or country(), files)


class Problems(unittest.TestCase):
    def test_a_good_country_has_none(self) -> None:
        self.assertEqual(problems({"p/plan/1.json": tariff(export="p/out"), "p/out/1.json": export()}), [])

    def test_the_block_and_every_file_are_validated(self) -> None:
        self.assertIn("country block: currency: missing",
                      problems({}, {k: v for k, v in country().items() if k != "currency"}))
        self.assertEqual(idx.problems("GB", country(), {}), ["country block: country must be GB"])
        self.assertIn("p/plan/1.json: schema: must be 1", problems({"p/plan/1.json": tariff(schema=3)}))

    def test_a_band_that_counts_holidays_needs_the_country_to_hold_them(self) -> None:
        bands = [{"name": "Day"}, {"name": "Night", "hours": "23:00-08:00", "days": ["sat", "sun"],
                                   "holidays": "weekend"}]
        files = {"p/plan/1.json": tariff(bands=bands)}
        self.assertEqual(problems(files), [
            "p/plan/1: a band counts public holidays, and the country block holds none"])
        self.assertEqual(problems(files, {**country(), "holidays": holidays()}), [])

    def test_a_file_in_the_wrong_place_is_named(self) -> None:
        for path in ("plan.json", "p/plan/one.json", "p/plan/0.json", "P/plan/1.json", "p/x/y/1.json"):
            self.assertTrue(any("must be <provider-id>" in e for e in problems({path: tariff()})), path)

    def test_revisions_are_numbered_in_date_order_without_gaps(self) -> None:
        self.assertEqual(problems({"p/flat/1.json": flat(), "p/flat/2.json": flat("0.3", "2026-06-01")}), [])
        self.assertTrue(any("none missing" in e for e in problems(
            {"p/flat/1.json": flat(), "p/flat/3.json": flat("0.3", "2026-06-01")})))
        self.assertTrue(any("must start after revision 1" in e for e in problems(
            {"p/flat/1.json": flat(), "p/flat/2.json": flat("0.3", "2026-01-01")})))
        self.assertTrue(any("starts before revision 1 ends" in e for e in problems(
            {"p/flat/1.json": flat(effective_to="2026-09-01"), "p/flat/2.json": flat("0.3", "2026-06-01")})))
        self.assertTrue(any("cannot change direction" in e for e in problems(
            {"p/out/1.json": export(), "p/out/2.json": flat("0.3", "2026-06-01")})))

    def test_an_export_reference_must_resolve(self) -> None:
        self.assertTrue(any("does not exist" in e for e in problems({"p/plan/1.json": tariff(export="p/out")})))
        self.assertTrue(any("is not an export file" in e for e in problems(
            {"p/plan/1.json": tariff(export="p/flat"), "p/flat/1.json": flat()})))
        self.assertTrue(any("no revision overlapping" in e for e in problems(
            {"p/plan/1.json": tariff(export="p/out"), "p/out/1.json": export(effective_to="2026-06-01")})))

    def test_every_area_must_compile(self) -> None:
        block = country([{"percent": "9", "effective_from": "2027-01-01"}])
        found = problems({"p/plan/1.json": tariff()}, block)
        self.assertEqual(len(found), 2)
        self.assertIn("area urban does not compile", found[0])

    def test_an_undefined_country_value_is_a_problem(self) -> None:
        doc = tariff(bill={"total": {"kind": "per_period", "amount": "$country.levy"}})
        self.assertTrue(any("$country.levy is not in the country block" in e
                            for e in problems({"p/plan/1.json": doc})))


class CountryIndex(unittest.TestCase):
    def setUp(self) -> None:
        self.files = {"p/flat/1.json": flat(), "p/flat/2.json": flat("0.3", "2026-06-01", provider="P Power"),
                      "p/out/1.json": export(effective_to="2026-12-01"), "q/plan/1.json": tariff(provider="Q")}
        self.index = idx.country_index(country(), self.files)

    def test_country_values_come_first_and_the_collection_last(self) -> None:
        self.assertEqual(idx.block_of(self.index), {**country(), "schema": 1})
        keys = list(__import__("json").loads(layout.dumps_index(self.index)))
        self.assertEqual(keys[:5], ["schema", "country", "currency", "timezone", "vat_percent"])
        self.assertEqual(keys[-1], "providers")

    def test_each_revision_has_its_dates_and_checksum_and_no_prices(self) -> None:
        revisions = self.index["providers"]["p"]["tariffs"]["flat"]["revisions"]
        self.assertEqual(revisions["1"], {"effective_from": "2026-01-01", "effective_to": "2026-06-01",
                                          "checksum": checksum(self.files["p/flat/1.json"])})
        self.assertEqual(revisions["2"]["effective_to"], None)
        self.assertNotIn("0.25", layout.dumps_index(self.index))

    def test_a_revision_ends_when_the_next_starts_or_when_it_says(self) -> None:
        out = self.index["providers"]["p"]["tariffs"]["out"]
        self.assertEqual(out["revisions"]["1"]["effective_to"], "2026-12-01")
        self.assertEqual(out["direction"], "export")
        self.assertNotIn("direction", self.index["providers"]["p"]["tariffs"]["flat"])

    def test_names_come_from_the_newest_file(self) -> None:
        self.assertEqual(self.index["providers"]["p"]["name"], "P Power")
        self.assertEqual(self.index["providers"]["q"]["name"], "Q")
        self.assertEqual(self.index["providers"]["p"]["tariffs"]["flat"]["name"], "Flat")

    def test_the_same_files_give_the_same_bytes(self) -> None:
        again = idx.country_index(country(), dict(reversed(list(self.files.items()))))
        self.assertEqual(layout.dumps_index(again), layout.dumps_index(self.index))


class RootIndex(unittest.TestCase):
    def test_it_summarises_each_country_and_lists_the_unavailable(self) -> None:
        index = idx.country_index({**country(), "availability": "partial", "reason": "Some"},
                                  {"p/flat/1.json": flat()})
        root = idx.root_index({"IE": index}, UNAVAILABLE)
        self.assertEqual(root["countries"]["IE"], {
            "availability": "partial", "reason": "Some", "path": "ie/index.json",
            "checksum": checksum(index), "providers": 1, "tariffs": 1})
        self.assertEqual(root["countries"]["XX"], {"availability": "unavailable", "reason": "No source",
                                                   "checked": "2026-11-10"})
        self.assertEqual(list(root["countries"]), ["IE", "XX"])
        plain = idx.root_index({"IE": idx.country_index(country(), {})}, UNAVAILABLE)["countries"]["IE"]
        self.assertEqual(plain["availability"], "available")
        self.assertNotIn("reason", plain)

    def test_a_country_cannot_be_both_held_and_unavailable(self) -> None:
        with self.assertRaisesRegex(ValueError, "IE has tariff files"):
            idx.root_index({"IE": idx.country_index(country(), {})},
                           {"schema": 1, "countries": {"IE": {"reason": "x", "checked": "2026-11-10"}}})
        with self.assertRaisesRegex(ValueError, "needs schema 1"):
            idx.root_index({}, {})


if __name__ == "__main__":
    unittest.main()
