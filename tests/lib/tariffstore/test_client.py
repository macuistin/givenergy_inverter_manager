# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""The client: from a country code, a provider and a tariff to a checked file and a definition."""
from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from unittest import mock

from custom_components.givenergy_inverter_manager.lib.tariffstore import FolderCache, MemoryCache, Store, StoreError, client, folder_reader, url_reader
from .building import build_store
from .fixtures import country, export, flat, tariff, write_store

DAY = date(2026, 11, 10)
FILES = {"p/plan/1.json": tariff(export="p/out"), "p/out/1.json": export(),
         "p/flat/1.json": flat(), "p/flat/2.json": flat("0.3", "2026-06-01"),
         "q/old/1.json": flat(effective_to="2026-03-01", provider="Q Power")}


class StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tariffs = write_store(Path(tmp.name), FILES)
        build_store(self.tariffs)
        self.reads: list[str] = []
        reader = folder_reader(self.tariffs)

        def read(path: str) -> bytes:
            self.reads.append(path)
            return reader(path)
        self.cache = MemoryCache()
        self.store = Store(read, self.cache)


class Finding(StoreCase):
    def test_countries_then_providers_then_tariffs(self) -> None:
        countries = self.store.countries()
        self.assertEqual(countries["IE"]["availability"], "available")
        self.assertEqual(countries["XX"]["availability"], "unavailable")
        self.assertEqual(self.store.providers("ie"), {"p": "P Energy", "q": "Q Power"})
        self.assertEqual(self.store.tariffs("IE", "p"), {"plan": "Plan", "flat": "Flat"})
        self.assertEqual(self.store.tariffs("IE", "p", direction="export"), {"out": "Out"})
        self.assertEqual(self.reads, ["index.json", "ie/index.json"])  # no tariff file was needed

    def test_tariffs_on_offer_on_a_day(self) -> None:
        self.assertEqual(self.store.tariffs("IE", "q"), {"old": "Flat"})
        self.assertEqual(self.store.tariffs("IE", "q", on=DAY), {})
        self.assertEqual(self.store.tariffs("IE", "q", on=date(2026, 2, 1)), {"old": "Flat"})

    def test_the_country_values_are_there_for_a_caller(self) -> None:
        index = self.store.country("IE")
        self.assertEqual((index["currency"], index["timezone"], index["vat_percent"]),
                         ("EUR", "Europe/Dublin", "9"))

    def test_what_is_not_held_says_so(self) -> None:
        with self.assertRaisesRegex(StoreError, "XX: no tariffs are held: No source"):
            self.store.country("XX")
        with self.assertRaisesRegex(StoreError, "ZZ: no tariffs are held$"):
            self.store.country("ZZ")
        with self.assertRaisesRegex(StoreError, "no provider nobody"):
            self.store.tariffs("IE", "nobody")
        with self.assertRaisesRegex(StoreError, "no tariff p/nothing"):
            self.store.revision("IE", "p", "nothing", DAY)
        with self.assertRaisesRegex(StoreError, "no revision is in force on 2025-01-01"):
            self.store.revision("IE", "p", "flat", date(2025, 1, 1))

    def test_the_revision_in_force_follows_the_date(self) -> None:
        self.assertEqual(self.store.revision("IE", "p", "flat", date(2026, 5, 31))[0], 1)
        self.assertEqual(self.store.revision("IE", "p", "flat", date(2026, 6, 1))[0], 2)


class Fetching(StoreCase):
    def test_a_tariff_file_is_checked_and_downloaded_once(self) -> None:
        number, doc = self.store.tariff("IE", "p", "flat", DAY)
        self.assertEqual((number, doc["areas"]["all"]["rates"]), (2, {"All day": "0.3"}))
        self.store.tariff("IE", "p", "flat", DAY)
        self.assertEqual(self.reads.count("ie/p/flat/2.json"), 1)
        again = Store(folder_reader(Path("/nonexistent")), self.cache)
        self.assertEqual(again.tariff("IE", "p", "flat", DAY)[0], 2)  # served from the cache alone

    def test_areas_are_listed_for_a_choice(self) -> None:
        self.assertEqual(self.store.areas("IE", "p", "plan", DAY), {"urban": "Urban", "rural": "Rural"})
        self.assertEqual(self.store.areas("IE", "p", "flat", DAY), {"all": "Flat"})

    def test_a_changed_file_is_refused(self) -> None:
        path = self.tariffs / "ie/p/flat/2.json"
        path.write_text(path.read_text().replace('"0.3"', '"0.03"'))
        with self.assertRaisesRegex(StoreError, "does not match its checksum"):
            self.store.tariff("IE", "p", "flat", DAY)

    def test_a_changed_country_index_is_refused(self) -> None:
        path = self.tariffs / "ie/index.json"
        path.write_text(path.read_text().replace('"9"', '"0"'))
        with self.assertRaisesRegex(StoreError, "ie/index.json: does not match its checksum"):
            self.store.country("IE")

    def test_unreadable_files_are_reported_not_raised_raw(self) -> None:
        (self.tariffs / "ie/p/flat/2.json").unlink()
        with self.assertRaisesRegex(StoreError, "cannot be read"):
            self.store.tariff("IE", "p", "flat", DAY)
        (self.tariffs / "ie/p/flat/1.json").write_text("{not json")
        with self.assertRaisesRegex(StoreError, "not JSON"):
            self.store.tariff("IE", "p", "flat", date(2026, 2, 1))
        for text, message in (("[]", "not a JSON object"), ("{bad", "not JSON"),
                              ('{"schema": 9}', "not a schema 1 countries index")):
            (self.tariffs / "index.json").write_text(text)
            with self.assertRaisesRegex(StoreError, message):
                Store(folder_reader(self.tariffs)).countries()

    def test_a_file_that_matches_but_is_not_valid_is_refused(self) -> None:
        bad = flat(schema=5)
        (self.tariffs / "ie/p/flat/2.json").write_text(json.dumps(bad))
        index = json.loads((self.tariffs / "ie/index.json").read_text())
        index["providers"]["p"]["tariffs"]["flat"]["revisions"]["2"]["checksum"] = client.checksum(bad)
        self.store._root = self.store.countries()
        self.store._countries["IE"] = index
        with self.assertRaisesRegex(StoreError, "schema: must be 1"):
            self.store.tariff("IE", "p", "flat", DAY)

    def test_refresh_reads_the_indexes_again(self) -> None:
        self.store.providers("IE")
        self.store.refresh()
        self.store.providers("IE")
        self.assertEqual(self.reads.count("index.json"), 2)


class Definition(StoreCase):
    def test_a_definition_carries_the_country_values_and_the_paired_export(self) -> None:
        out = self.store.definition("ie", "p", "plan", DAY, area="rural")
        self.assertEqual((out["country"], out["currency"], out["id"]), ("IE", "EUR", "plan-rural"))
        self.assertEqual(out["bill"]["total"]["percent"], "9")
        self.assertEqual(out["export"]["base"]["price"], "0.12")

    def test_the_caller_can_choose_the_export_tariff(self) -> None:
        out = self.store.definition("IE", "p", "flat", DAY, export="p/out")
        self.assertEqual(out["export"]["base"]["price"], "0.12")
        self.assertEqual(self.store.definition("IE", "p", "flat", DAY)["export"]["base"]["price"], "0")
        with self.assertRaisesRegex(StoreError, "p/flat: not an export tariff"):
            self.store.definition("IE", "p", "plan", DAY, area="urban", export="p/flat")

    def test_a_past_day_gets_the_revision_and_end_date_of_that_day(self) -> None:
        out = self.store.definition("IE", "p", "flat", date(2026, 3, 1))
        self.assertEqual((out["revision"], out["effective_to"]), (1, "2026-06-01"))
        self.assertEqual(out["import"]["base"]["price"], "0.25")

    def test_an_export_tariff_has_no_bill_of_its_own(self) -> None:
        with self.assertRaisesRegex(StoreError, "no bill of its own"):
            self.store.definition("IE", "p", "out", DAY)


class Caching(StoreCase):
    def folder_store(self, folder: Path, read=None, **options) -> Store:
        return Store(read or self.store._read, FolderCache(folder, **options.pop("cache", {})), **options)

    def test_a_folder_cache_serves_a_second_run_with_no_store(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            first = self.folder_store(Path(folder))
            wanted = first.definition("IE", "p", "plan", DAY, area="urban")
            self.assertEqual(sorted(p.relative_to(folder).as_posix() for p in Path(folder).rglob("*.json")),
                             ["ie/index.json", "ie/p/out/1.json", "ie/p/plan/1.json", "index.json"])
            self.reads.clear()
            second = self.folder_store(Path(folder))
            self.assertEqual(second.definition("IE", "p", "plan", DAY, area="urban"), wanted)
            self.assertEqual(self.reads, [])  # the countries index is still young
            self.assertFalse(second.offline)

    def test_an_old_countries_index_is_read_again_and_nothing_else(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            self.folder_store(Path(folder)).tariff("IE", "p", "flat", DAY)
            self.reads.clear()
            later = self.folder_store(Path(folder), max_age=0)
            later.tariff("IE", "p", "flat", DAY)
            self.assertEqual(self.reads, ["index.json"])  # the checksums below it had not changed

    def test_with_no_network_the_cache_is_used_and_says_so(self) -> None:
        def down(path: str) -> bytes:
            raise OSError("no network")
        with tempfile.TemporaryDirectory() as folder:
            self.folder_store(Path(folder)).tariff("IE", "p", "flat", DAY)
            offline = self.folder_store(Path(folder), read=down, max_age=0)
            self.assertEqual(offline.tariff("IE", "p", "flat", DAY)[0], 2)
            self.assertTrue(offline.offline)
            with self.assertRaisesRegex(StoreError, "cannot be read"):
                offline.tariff("IE", "p", "plan", DAY)  # never fetched, so not held
            with self.assertRaisesRegex(StoreError, "cannot be read"):
                self.folder_store(Path(folder) / "empty", read=down).countries()

    def test_an_answer_that_is_not_the_index_falls_back_to_the_cache(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            self.folder_store(Path(folder)).providers("IE")
            portal = self.folder_store(Path(folder), read=lambda path: b"<html>sign in</html>", max_age=0)
            self.assertEqual(portal.providers("IE"), {"p": "P Energy", "q": "Q Power"})
            self.assertTrue(portal.offline)

    def test_a_changed_revision_replaces_the_cached_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            self.folder_store(Path(folder)).tariff("IE", "q", "old", date(2026, 2, 1))
            write_store(self.tariffs.parent, {**FILES, "q/old/1.json": flat(
                effective_to="2026-04-01", provider="Q Power")})
            build_store(self.tariffs)
            later = self.folder_store(Path(folder), max_age=0)
            self.assertEqual(later.tariff("IE", "q", "old", date(2026, 3, 15))[1]["effective_to"], "2026-04-01")
            self.assertIn("2026-04-01", (Path(folder) / "ie/q/old/1.json").read_text())

    def test_a_damaged_cached_file_is_fetched_again(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            self.folder_store(Path(folder)).tariff("IE", "p", "flat", DAY)
            (Path(folder) / "ie/p/flat/2.json").write_text("{half")
            self.assertEqual(self.folder_store(Path(folder)).tariff("IE", "p", "flat", DAY)[0], 2)

    def test_refresh_reads_the_countries_index_whatever_its_age(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = self.folder_store(Path(folder))
            store.providers("IE")
            self.reads.clear()
            store.refresh()
            store.providers("IE")
            self.assertEqual(self.reads, ["index.json"])

    def test_a_whole_country_can_be_fetched_for_comparisons(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = self.folder_store(Path(folder))
            self.assertEqual(store.fetch_country("IE", on=DAY), 3)  # plan, out and flat revision 2
            self.assertFalse((Path(folder) / "ie/p/flat/1.json").exists())
            self.assertEqual(store.fetch_country("ie"), 5)
            self.reads.clear()
            self.assertEqual(store.fetch_country("IE"), 5)
            self.assertEqual(self.reads, [])

    def test_a_path_that_leaves_the_store_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            cache = FolderCache(folder)
            for path in ("../outside.json", "/etc/passwd", "ie/../../x.json", "ie/index.txt"):
                with self.subTest(path), self.assertRaisesRegex(StoreError, "not a path inside"):
                    cache.put(path, b"{}")
            root = json.loads((self.tariffs / "index.json").read_text())
            root["countries"]["IE"]["path"] = "../ie/index.json"
            (self.tariffs / "index.json").write_text(json.dumps(root))
            with self.assertRaisesRegex(StoreError, "not a path inside"):
                Store(folder_reader(self.tariffs)).country("IE")

    def test_the_folder_cache_knows_the_age_of_what_it_holds(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            cache = FolderCache(folder)
            self.assertIsNone(cache.age("index.json"))
            self.assertIsNone(cache.get("index.json"))
            cache.put("index.json", b"{}")
            self.assertLess(cache.age("index.json"), 60)
            self.assertEqual(FolderCache(folder, clock=lambda: cache.age("index.json") + 1e12).get("index.json"), b"{}")

    def test_cached_builds_a_store_over_https_with_a_folder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = Store.cached("https://example.test/tariffs", folder, max_age=5)
            self.assertIsInstance(store._cache, FolderCache)
            self.assertEqual(store._max_age, 5)


class Custom(StoreCase):
    MINE = {"name": "My tariff", "effective_from": "2026-01-01",
            "bands": [{"name": "Day"}, {"name": "Night", "hours": "23:00-08:00"}],
            "areas": {"all": {"standing": "0.9", "rates": {"Day": "0.31", "Night": "0.14"}}}}
    MY_EXPORT = {"name": "My export", "effective_from": "2026-01-01", "direction": "export",
                 "bands": [{"name": "Export"}, {"name": "Peak", "hours": "16:00-19:00"}],
                 "areas": {"all": {"rates": {"Export": "0.1", "Peak": "0.2"}}}}

    def test_a_custom_tariff_takes_the_country_values_from_the_store(self) -> None:
        out = self.store.custom_definition("ie", self.MINE, DAY)
        self.assertEqual((out["id"], out["provider"], out["currency"], out["source_url"]),
                         ("custom", {"id": "custom", "name": "Custom"}, "EUR", None))
        self.assertEqual(out["import"]["zones"][0]["price"], "0.14")
        self.assertEqual(out["bill"]["total"]["percent"], "9")
        self.assertEqual(self.reads, ["index.json", "ie/index.json"])

    def test_a_custom_tariff_can_name_its_provider_and_source(self) -> None:
        mine = {**self.MINE, "provider": "Local Power",
                "source": {"id": "my-bill", "url": "https://example.test/my-bill"}}
        out = self.store.custom_definition("IE", mine, DAY)
        self.assertEqual((out["provider"]["name"], out["source_url"]),
                         ("Local Power", "https://example.test/my-bill"))

    def test_a_custom_tariff_is_paid_a_stored_or_a_custom_export(self) -> None:
        stored = self.store.custom_definition("IE", self.MINE, DAY, export="p/out")
        self.assertEqual(stored["export"]["base"]["price"], "0.12")
        custom = self.store.custom_definition("IE", self.MINE, DAY, export=self.MY_EXPORT)
        self.assertEqual(custom["export"]["zones"][0]["price"], "0.2")

    def test_a_country_the_store_does_not_hold_is_given_with_the_tariff(self) -> None:
        out = self.store.custom_definition("NZ", self.MINE, DAY, block=country(vat="15", code="NZ"))
        self.assertEqual((out["country"], out["bill"]["total"]["percent"]), ("NZ", "15"))
        self.assertEqual(self.reads, [])  # nothing was needed from the store

    def test_a_custom_tariff_is_held_to_the_same_rules(self) -> None:
        for change, message in (
                ({"areas": {"all": {"standing": "0.9", "rates": {"Day": 0.31, "Night": "0.14"}}}}, "custom tariff: areas"),
                ({"direction": "export"}, "custom tariff:"),
                ({"colour": "red"}, "custom tariff: colour")):
            with self.subTest(change), self.assertRaisesRegex(StoreError, message):
                self.store.custom_definition("IE", {**self.MINE, **change}, DAY)
        with self.assertRaisesRegex(StoreError, "pass an export tariff as `export`"):
            self.store.custom_definition("IE", self.MY_EXPORT, DAY)
        with self.assertRaisesRegex(StoreError, "custom tariff: not a JSON object"):
            self.store.custom_definition("IE", [], DAY)
        with self.assertRaisesRegex(StoreError, "is not an export tariff"):
            self.store.custom_definition("IE", self.MINE, DAY, export=self.MINE)
        with self.assertRaisesRegex(StoreError, "custom tariff: no area north"):
            self.store.custom_definition("IE", self.MINE, DAY, area="north")
        with self.assertRaisesRegex(StoreError, "custom country: currency: missing"):
            self.store.custom_definition("NZ", self.MINE, DAY, block={"country": "NZ"})
        with self.assertRaisesRegex(StoreError, "ZZ: no tariffs are held"):
            self.store.custom_definition("ZZ", self.MINE, DAY)


class Readers(unittest.TestCase):
    def test_the_url_reader_asks_for_the_path_under_the_base(self) -> None:
        seen = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b"{}"

        def opener(request, timeout):
            seen["url"], seen["agent"] = request.full_url, request.get_header("User-agent")
            return Response()
        with mock.patch.object(client.urllib.request, "urlopen", opener):
            self.assertEqual(url_reader("https://example.test/tariffs/")("ie/index.json"), b"{}")
        self.assertEqual(seen, {"url": "https://example.test/tariffs/ie/index.json",
                                "agent": client.USER_AGENT})
        with self.assertRaises(ValueError):
            url_reader("http://example.test/tariffs")

    def test_a_network_failure_is_a_store_error(self) -> None:
        def read(path: str) -> bytes:
            raise urllib.error.URLError("offline")
        with self.assertRaisesRegex(StoreError, "cannot be read"):
            Store(read).countries()


if __name__ == "__main__":
    unittest.main()
