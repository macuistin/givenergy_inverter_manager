# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""Compile: a tariff file plus its country block gives the document the bill engine reads."""
from __future__ import annotations

import unittest

from custom_components.givenergy_inverter_manager.lib.tariffstore.compile import CompileError, check_references, compile_area, export_prices
from custom_components.givenergy_inverter_manager.lib.tariffstore.schema import validate_tariff
from .fixtures import META, country, export, tariff


class Compile(unittest.TestCase):
    def compiled(self, area="urban", block=None, doc=None, meta=META, **kw):
        return compile_area(doc or tariff(), area, block=block or country(), meta=meta,
                            on="2026-11-10", **kw)

    def test_country_values_are_passed_in(self) -> None:
        out = self.compiled()
        self.assertEqual((out["currency"], out["timezone"], out["country"]),
                         ("EUR", "Europe/Dublin", "IE"))
        self.assertEqual(out["bill"]["total"]["percent"], "9")
        self.assertEqual(out["bill"]["period"]["start_day"], {"input": "bill_start_day"})
        self.assertEqual(out["inputs"]["bill_start_day"]["default"], 1)

    def test_identity_comes_from_the_path_and_the_file(self) -> None:
        out = self.compiled("rural", meta={**META, "revision": 3, "effective_to": "2027-01-01"})
        self.assertEqual((out["id"], out["revision"], out["supersedes"]), ("plan-rural", 3, 2))
        self.assertEqual(out["provider"], {"id": "p", "name": "P Energy"})
        self.assertEqual(out["name"], "Plan (Rural)")
        self.assertEqual(out["effective_to"], "2027-01-01")
        self.assertEqual(out["source_url"], "https://example.test/prices")
        self.assertEqual((out["service"], out["customer_class"], out["completeness"]),
                         ("electricity", "residential", "partial"))
        first = self.compiled()
        self.assertIsNone(first["supersedes"])
        self.assertIsNone(first["effective_to"])

    def test_area_rates_and_standing_fill_the_bill(self) -> None:
        out = self.compiled("rural")
        self.assertEqual(out["import"]["base"], {"name": "Day", "price": "0.32"})
        self.assertEqual(out["import"]["zones"], [{"name": "Night", "priority": 1,
                                                   "hours": "23:00-08:00", "price": "0.16"}])
        self.assertEqual(out["bill"]["total"]["of"]["of"]["standing"]["amount"], "1.1")

    def test_an_unknown_area_names_the_ones_there_are(self) -> None:
        with self.assertRaisesRegex(CompileError, "urban, rural"):
            self.compiled("all")

    def test_a_single_area_tariff_keeps_its_own_name(self) -> None:
        doc = tariff(areas={"all": {"standing": "1", "rates": {"Day": "0.3", "Night": "0.1"}}})
        out = self.compiled("all", doc=doc)
        self.assertEqual((out["id"], out["name"]), ("plan", "Plan"))

    def test_days_months_and_holidays_reach_the_engine(self) -> None:
        doc = tariff(bands=[{"name": "Day"}, {"name": "Night", "hours": "23:00-08:00",
                                              "days": ["sat", "sun"], "months": [6, 7],
                                              "holidays": "weekend"}])
        self.assertEqual(validate_tariff(doc), [])
        zone = self.compiled(doc=doc)["import"]["zones"][0]
        self.assertEqual((zone["days"], zone["months"], zone["holidays"]),
                         (["sat", "sun"], [6, 7], "weekend"))

    def test_a_tariff_can_carry_its_own_time_zone(self) -> None:
        self.assertEqual(self.compiled(doc=tariff(timezone="Europe/London"))["timezone"], "Europe/London")

    def test_a_vat_change_is_one_edit_in_the_country_block(self) -> None:
        self.assertEqual(self.compiled(block=country("23"))["bill"]["total"]["percent"], "23")

    def test_a_date_with_no_rate_is_refused_not_priced_at_zero(self) -> None:
        with self.assertRaises(CompileError):
            self.compiled(block=country([{"percent": "0", "effective_to": "2026-01-01"}]))

    def test_an_undefined_country_value_is_reported(self) -> None:
        block = country()
        self.assertEqual(check_references(tariff(), block), [])
        block["bill"]["total"]["percent"] = "$country.nothing"
        self.assertEqual(check_references(tariff(), block),
                         ["country bill: $country.nothing is not in the country block"])
        with self.assertRaises(CompileError):
            self.compiled(block=block)

    def test_an_input_is_only_the_bill_start_day(self) -> None:
        block = country()
        block["bill"]["total"]["percent"] = "$input.bill_start_day"
        with self.assertRaisesRegex(CompileError, "only allowed as the bill start day"):
            self.compiled(block=block)
        block = country()
        block["bill"]["period"]["start_day"] = "$input.unknown"
        with self.assertRaisesRegex(CompileError, "not a declared input"):
            self.compiled(block=block)
        block = country()
        block["bill"]["period"]["start_day"] = 7
        self.assertEqual(self.compiled(block=block)["bill"]["period"]["start_day"], 7)

    def test_a_tariff_can_replace_the_bill_and_use_a_country_value(self) -> None:
        doc = tariff(bill={"total": {"kind": "sum", "of": {
            "energy": {"kind": "energy_by_band"},
            "levy": {"kind": "per_period", "amount": "$country.pso_levy"}}}})
        self.assertEqual(validate_tariff(doc), [])
        out = self.compiled(doc=doc, block={**country(), "pso_levy": "3.23"})
        self.assertEqual(out["bill"]["total"]["of"]["levy"]["amount"], "3.23")
        self.assertEqual(out["bill"]["period"]["start_day"], {"input": "bill_start_day"})

    def test_a_worked_bill_makes_it_complete(self) -> None:
        doc = tariff(checks={"october": {"period_days": 30}})
        self.assertEqual(self.compiled(doc=doc)["completeness"], "complete")

    def test_a_paired_flat_export_adds_a_credit_line(self) -> None:
        out = self.compiled(export_file=export())
        self.assertEqual(out["export"]["base"], {"name": "Flat", "price": "0.12"})
        self.assertEqual(out["bill"]["total"]["of"]["of"]["export"], {"kind": "export_credit"})
        self.assertEqual(self.compiled()["export"]["base"]["price"], "0")

    def test_an_export_needs_a_sum_to_join(self) -> None:
        doc = tariff(bill={"total": {"kind": "per_day", "amount": "1"}})
        with self.assertRaisesRegex(CompileError, "no sum"):
            self.compiled(doc=doc, export_file=export())

    def test_a_banded_export_becomes_export_zones(self) -> None:
        banded = export(bands=[{"name": "Off"}, {"name": "Peak", "hours": "16:00-19:00", "days": ["mon"]}],
                        areas={"all": {"rates": {"Off": "0.09", "Peak": "0.16"}}})
        self.assertEqual(export_prices(banded), {
            "base": {"name": "Off", "price": "0.09"},
            "zones": [{"name": "Peak", "priority": 1, "hours": "16:00-19:00", "price": "0.16",
                       "days": ["mon"]}]})
        self.assertEqual(self.compiled(export_file=banded)["export"]["zones"][0]["name"], "Peak")

    def test_an_export_pays_the_row_of_the_same_area(self) -> None:
        by_area = export(areas={"north": {"label": "North", "rates": {"Flat": "0.10"}},
                                "south": {"label": "South", "rates": {"Flat": "0.14"}}})
        self.assertEqual(export_prices(by_area, "south")["base"]["price"], "0.14")
        self.assertEqual(export_prices(by_area, "elsewhere")["base"]["price"], "0.10")


if __name__ == "__main__":
    unittest.main()
