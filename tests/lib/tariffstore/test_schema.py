# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""The stored format: what a tariff file and a country block may hold."""
from __future__ import annotations

import unittest

from custom_components.givenergy_inverter_manager.lib.tariffstore.schema import (canonical, checksum, stamp_ok, validate_country, validate_tariff,
                                    validate_unavailable, vat_on)
from .fixtures import country, export, holidays, tariff


def errors_for(**changes) -> list[str]:
    return validate_tariff(tariff(**changes))


class TariffFile(unittest.TestCase):
    def test_the_small_tariff_is_valid(self) -> None:
        self.assertEqual(validate_tariff(tariff()), [])
        self.assertEqual(validate_tariff(export()), [])

    def test_a_file_must_be_an_object_with_every_required_key(self) -> None:
        self.assertEqual(validate_tariff([]), ["document: must be an object"])
        for key in ("schema", "name", "provider", "effective_from", "source", "bands", "areas"):
            doc = tariff()
            del doc[key]
            self.assertEqual(validate_tariff(doc), [f"{key}: missing"])

    def test_the_tariff_holds_nothing_the_path_or_the_country_says(self) -> None:
        for key in ("currency", "country", "id", "revision", "import", "checksum", "vat_percent"):
            self.assertIn(f"{key}: not allowed", errors_for(**{key: "x"}))

    def test_scalars_are_checked(self) -> None:
        self.assertIn("schema: must be 1", errors_for(schema=2))
        self.assertIn("name: must be text", errors_for(name=""))
        self.assertIn("provider: must be text", errors_for(provider=7))
        self.assertIn("effective_from: not an ISO date", errors_for(effective_from="1 May"))
        self.assertIn("effective_to: not an ISO date", errors_for(effective_to="soon"))
        self.assertIn("effective_to: must be after effective_from", errors_for(effective_to="2026-11-01"))
        self.assertEqual(errors_for(effective_to="2026-11-02"), [])
        self.assertIn("direction: must be export when present", errors_for(direction="both"))
        self.assertIn("prices_include_tax: write it only when false", errors_for(prices_include_tax=True))
        self.assertEqual(errors_for(prices_include_tax=False), [])
        self.assertTrue(any(e.startswith("service:") for e in errors_for(service="electricity")))
        self.assertTrue(any(e.startswith("customer_class:") for e in errors_for(customer_class="residential")))
        self.assertEqual(errors_for(customer_class="commercial"), [])
        self.assertIn("timezone: not an IANA time zone", errors_for(timezone="Mars/Base"))
        self.assertEqual(errors_for(timezone="Australia/Brisbane"), [])

    def test_the_source_is_an_id_and_an_https_link(self) -> None:
        for bad in (None, {"id": "x"}, {"id": "Not A Slug", "url": "https://x.test"},
                    {"id": "x", "url": "http://x.test"}, {"id": "x", "url": "https://x.test", "more": 1}):
            self.assertTrue(any(e.startswith("source:") for e in errors_for(source=bad)), bad)

    def test_bands(self) -> None:
        self.assertIn("bands: needs at least one band", errors_for(bands=[]))
        self.assertTrue(any("bands[0]" in e for e in errors_for(
            bands=[{"name": "Day", "hours": "00:00-23:00"}, {"name": "Night", "hours": "23:00-08:00"}])))
        for hours in ("2300-0800", "24:00-08:00", "08:00-08:00", None):
            found = errors_for(bands=[{"name": "Day"}, {"name": "Night", "hours": hours}])
            self.assertTrue(any("bands[1].hours" in e for e in found), hours)
        self.assertIn("bands: names must be unique", errors_for(
            bands=[{"name": "Day"}, {"name": "Day", "hours": "23:00-08:00"}]))
        self.assertTrue(any("bands[1]" in e for e in errors_for(
            bands=[{"name": "Day"}, {"name": "Night", "hours": "23:00-08:00", "price": "1"}])))
        self.assertTrue(any("bands[1]" in e for e in errors_for(bands=[{"name": "Day"}, "Night"])))

    def test_a_band_can_be_limited_to_days_and_months(self) -> None:
        def band(**more):
            return [{"name": "Day"}, {"name": "Night", "hours": "23:00-08:00", **more}]
        self.assertEqual(errors_for(bands=band(days=["sat", "sun"], months=[6, 7, 8],
                                               holidays="weekend")), [])
        self.assertTrue(any("days" in e for e in errors_for(bands=band(days=["saturday"]))))
        self.assertTrue(any("days" in e for e in errors_for(bands=band(days=["sat", "sat"]))))
        self.assertTrue(any("days" in e for e in errors_for(bands=band(days=[]))))
        self.assertTrue(any("months" in e for e in errors_for(bands=band(months=[13]))))
        self.assertTrue(any("months" in e for e in errors_for(bands=band(months=[True]))))
        self.assertTrue(any("holidays" in e for e in errors_for(bands=band(holidays="normal"))))

    def test_areas_price_exactly_the_bands(self) -> None:
        self.assertIn("areas: needs at least one area", errors_for(areas={}))
        doc = tariff()
        doc["areas"]["urban"]["rates"]["Night"] = 0.1
        self.assertIn("areas.urban.rates.Night: must be a decimal string", validate_tariff(doc))
        doc = tariff()
        del doc["areas"]["rural"]["rates"]["Night"]
        self.assertTrue(any("areas.rural.rates" in e for e in validate_tariff(doc)))
        doc = tariff()
        del doc["areas"]["urban"]["standing"]
        self.assertIn("areas.urban.standing: must be a decimal string", validate_tariff(doc))
        doc = tariff()
        del doc["areas"]["urban"]["label"]
        self.assertIn("areas.urban.label: missing", validate_tariff(doc))
        doc = tariff()
        doc["areas"]["urban"]["colour"] = "red"
        self.assertTrue(any("areas.urban: only" in e for e in validate_tariff(doc)))
        doc = tariff()
        doc["areas"]["Not A Slug"] = doc["areas"].pop("urban")
        self.assertTrue(any("key must be a slug" in e for e in validate_tariff(doc)))

    def test_an_export_file_has_no_standing_bill_or_export(self) -> None:
        doc = export()
        doc["areas"]["all"]["standing"] = "1"
        self.assertTrue(any("export has no standing" in e for e in validate_tariff(doc)))
        self.assertTrue(any(e.startswith("bill:") for e in validate_tariff(
            export(bill={"total": {"kind": "export_credit"}}))))
        self.assertTrue(any(e.startswith("export:") for e in validate_tariff(export(export="p/out"))))
        self.assertEqual(errors_for(export="p/out"), [])
        self.assertTrue(any(e.startswith("export:") for e in errors_for(export="just-a-name")))

    def test_a_tariff_bill_uses_only_known_nodes(self) -> None:
        good = {"total": {"kind": "sum", "of": {
            "energy": {"kind": "energy_by_band"},
            "fee": {"kind": "per_period", "amount": "5", "share": "whole"},
            "levy": {"kind": "adjust", "name": "Levy", "percent": "$country.levy",
                     "of": {"kind": "per_day", "amount": "0.1"}}}}}
        self.assertEqual(errors_for(bill=good), [])
        self.assertIn("bill: needs total, period or both", errors_for(bill={}))
        self.assertIn("bill: needs total, period or both", errors_for(bill={"tree": good["total"]}))
        self.assertIn("bill.total.per: must be month or period", errors_for(
            bill={"total": {"kind": "per_period", "amount": "5", "share": "whole", "per": "year"}}))
        self.assertIn("bill.total: unknown node kind", errors_for(bill={"total": {"kind": "formula"}}))
        self.assertIn("bill.total.script: not allowed on per_day",
                      errors_for(bill={"total": {"kind": "per_day", "script": "x"}}))
        self.assertIn("bill.total.amount: must be a decimal string",
                      errors_for(bill={"total": {"kind": "per_day", "amount": 1.5}}))
        self.assertIn("bill.total.mode: must be added or included", errors_for(
            bill={"total": {"kind": "tax", "name": "VAT", "percent": "9", "mode": "maybe",
                            "of": {"kind": "per_day"}}}))
        self.assertIn("bill.total.of: sum needs one or more named children",
                      errors_for(bill={"total": {"kind": "sum", "of": {}}}))
        deep = {"kind": "per_day"}
        for _ in range(10):
            deep = {"kind": "adjust", "name": "x", "percent": "1", "of": deep}
        self.assertTrue(any("tree too deep" in e for e in errors_for(bill={"total": deep})))

    def test_a_bill_period_and_inputs(self) -> None:
        total = {"kind": "per_day"}
        self.assertEqual(errors_for(bill={"period": {"rule": "monthly", "start_day": 5}, "total": total}), [])
        self.assertIn("bill.period: rule must be monthly",
                      errors_for(bill={"period": {"rule": "weekly", "start_day": 1}, "total": total}))
        self.assertIn("bill.period.start_day: must be a day number from 1 to 28 or a reference",
                      errors_for(bill={"period": {"rule": "monthly", "start_day": "first"}, "total": total}))

    def test_a_bill_period_longer_than_a_month(self) -> None:
        def period(**values) -> list[str]:
            return errors_for(bill={"period": {"rule": "monthly", "start_day": 1, **values}})

        self.assertEqual(period(months=2, start_month=2), [])
        self.assertEqual(period(months="$input.bill_months", start_month="$input.first_month"), [])
        self.assertIn("bill.period.months: must be 1, 2, 3, 4, 6 or 12, or a reference",
                      period(months=5))
        self.assertIn("bill.period.months: must be 1, 2, 3, 4, 6 or 12, or a reference",
                      period(months=True))
        self.assertIn("bill.period.start_month: must be a month number or a reference",
                      period(start_month=13))
        self.assertIn("bill.period.every: not allowed", period(every=2))

    def test_a_country_bill_needs_its_tree(self) -> None:
        block = country()
        del block["bill"]["total"]
        self.assertEqual(validate_country(block), ["bill: needs total and optional period"])
        self.assertEqual(errors_for(inputs={"day": {"type": "integer", "min": 1, "max": 28, "default": 1}}), [])
        self.assertIn("inputs: must be an object", errors_for(inputs=[]))
        self.assertTrue(any(e.startswith("inputs.day") for e in errors_for(inputs={"day": {"type": "text"}})))
        self.assertIn("checks: must be an object", errors_for(checks=[]))


class CountryBlock(unittest.TestCase):
    def test_a_block_is_valid(self) -> None:
        self.assertEqual(validate_country(country()), [])
        self.assertEqual(validate_country([]), ["country block: must be an object"])

    def test_missing_and_malformed_values_are_named(self) -> None:
        for key in ("country", "currency", "timezone", "vat_percent", "bill"):
            block = country()
            del block[key]
            self.assertEqual(validate_country(block), [f"{key}: missing"])
        self.assertTrue(any(e.startswith("country:") for e in validate_country(country(code="Ireland"))))
        self.assertTrue(any(e.startswith("currency:") for e in validate_country({**country(), "currency": "euro"})))
        self.assertTrue(any(e.startswith("timezone:") for e in validate_country({**country(), "timezone": "Dublin"})))
        self.assertIn("vat_percent: must be a decimal string", validate_country(country("nine")))
        self.assertIn("inputs: must be an object", validate_country({**country(), "inputs": 3}))

    def test_any_other_value_is_a_decimal_a_bill_can_use(self) -> None:
        self.assertEqual(validate_country({**country(), "pso_levy": "3.23"}), [])
        self.assertIn("pso_levy: must be a decimal string", validate_country({**country(), "pso_levy": 3.23}))

    def test_public_holidays_are_held_by_year_with_their_source(self) -> None:
        self.assertEqual(validate_country({**country(), "holidays": holidays()}), [])
        regional = holidays(IE_D={"2026": ["2026-01-01", "2026-01-02"]})
        self.assertEqual(validate_country({**country(), "holidays": regional}), [])

    def test_malformed_public_holidays_are_named(self) -> None:
        def refusals(**changes) -> list[str]:
            return validate_country({**country(), "holidays": {**holidays(), **changes}})
        self.assertEqual(validate_country({**country(), "holidays": ["2026-01-01"]}),
                         ["holidays: needs source and years, and may have regions"])
        self.assertEqual(refusals(note="x"), ["holidays: needs source and years, and may have regions"])
        self.assertIn("holidays.source: must be the https address the dates are published at",
                      refusals(source="a calendar"))
        self.assertEqual(refusals(years={}), ["holidays.years: must be an object of year to dates"])
        self.assertEqual(refusals(years={"2026": []}),
                         ["holidays.years.2026: must be a year with a list of dates"])
        self.assertEqual(refusals(years={"26": ["2026-01-01"]}),
                         ["holidays.years.26: must be a year with a list of dates"])
        self.assertEqual(refusals(years={"2026": ["2027-01-01"]}),
                         ["holidays.years.2026: every entry must be a date in 2026"])
        self.assertEqual(refusals(years={"2026": ["2026-01-01T00:00:00Z"]}),
                         ["holidays.years.2026: every entry must be a date in 2026"])
        for days in (["2026-12-25", "2026-01-01"], ["2026-01-01", "2026-01-01"]):
            self.assertEqual(refusals(years={"2026": days}),
                             ["holidays.years.2026: dates must be in order with none repeated"])

    def test_a_region_of_another_country_or_a_malformed_one_is_refused(self) -> None:
        def refusals(regions: object) -> list[str]:
            return validate_country({**country(), "holidays": {**holidays(), "regions": regions}})
        self.assertEqual(refusals(["IE-D"]), ["holidays.regions: must be an object of region to years"])
        for code in ("GB-SCT", "Dublin"):
            self.assertEqual(refusals({code: {"2026": ["2026-01-01"]}}),
                             [f"holidays.regions.{code}: must be an ISO 3166-2 code of this country"])
        self.assertEqual(refusals({"IE-D": {"2026": "all"}}),
                         ["holidays.regions.IE-D.2026: must be a year with a list of dates"])

    def test_vat_can_change_by_date_and_falls_back(self) -> None:
        dated = [{"percent": "5"},
                 {"percent": "0", "effective_from": "2026-10-01", "effective_to": "2027-04-01"}]
        block = country(dated)
        self.assertEqual(validate_country(block), [])
        self.assertEqual(vat_on(block, "2026-09-30"), "5")
        self.assertEqual(vat_on(block, "2026-10-01"), "0")
        self.assertEqual(vat_on(block, "2027-03-31"), "0")
        self.assertEqual(vat_on(block, "2027-04-01"), "5")
        self.assertEqual(vat_on(country("9"), "2030-01-01"), "9")
        self.assertIsNone(vat_on(country([{"percent": "0", "effective_to": "2026-01-01"}]), "2026-06-01"))
        bad = country([{"percent": "x", "effective_from": "soon"}, "five"])
        found = validate_country(bad)
        self.assertIn("vat_percent[0].percent: must be a decimal string", found)
        self.assertIn("vat_percent[0].effective_from: not an ISO date", found)
        self.assertIn("vat_percent[1].percent: must be a decimal string", found)

    def test_availability_needs_a_reason_when_partial(self) -> None:
        self.assertEqual(validate_country({**country(), "availability": "partial", "reason": "Some"}), [])
        self.assertIn("reason: a partial country says what is missing",
                      validate_country({**country(), "availability": "partial"}))
        self.assertTrue(any(e.startswith("availability") for e in validate_country(
            {**country(), "availability": "unavailable"})))


class Unavailable(unittest.TestCase):
    def test_the_unavailable_list_is_validated(self) -> None:
        self.assertEqual(validate_unavailable({"schema": 1, "countries": {
            "XX": {"reason": "No source", "checked": "2026-11-10"}}}), [])
        self.assertEqual(validate_unavailable({"countries": {}}), ["unavailable: needs schema 1 and countries"])
        errors = validate_unavailable({"schema": 1, "countries": {
            "XX": {"reason": " ", "checked": "2026-11-10"},
            "yy": {"reason": "No source", "checked": "soon"}, "ZZ": {"reason": "x"}}})
        self.assertIn("unavailable.XX.reason: say why", errors)
        self.assertIn("unavailable.yy: key must be an ISO 3166-1 alpha-2 code", errors)
        self.assertIn("unavailable.yy.checked: not a date", errors)
        self.assertIn("unavailable.ZZ: needs reason and checked", errors)

    def test_stamp_rules(self) -> None:
        self.assertTrue(stamp_ok("2026-11-10"))
        self.assertTrue(stamp_ok("2026-11-10T08:15:00Z"))
        for bad in ("2026-13-40", "10/11/2026", 20261110, "2026-11-10T08:15"):
            self.assertFalse(stamp_ok(bad))


class Checksum(unittest.TestCase):
    def test_key_order_and_spacing_do_not_change_it(self) -> None:
        a = {"b": 1, "a": {"y": "é", "x": [1, 2]}}
        b = {"a": {"x": [1, 2], "y": "é"}, "b": 1}
        self.assertEqual(canonical(a), b'{"a":{"x":[1,2],"y":"\xc3\xa9"},"b":1}')
        self.assertEqual(checksum(a), checksum(b))
        self.assertRegex(checksum(a), r"^sha256:[0-9a-f]{64}$")
        self.assertNotEqual(checksum(a), checksum({**a, "b": 2}))


if __name__ == "__main__":
    unittest.main()
