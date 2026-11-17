"""The stored format of dynamic prices: one file per feed, area and day, and a small index per feed.

Dynamic prices change every half hour, so they are written by a machine and cannot be reviewed one
by one. This module is the only definition of what a file may hold, and the update script writes
nothing it refuses. Standard library only. docs/format.md describes the format in words.

A day file lists the prices of one local day from local midnight, one per interval. A published
day is never changed. A day with a daylight saving change has 23 or 25 hours of prices.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAY_KEYS = {"schema", "feed", "area", "date", "timezone", "interval_minutes", "prices"}
INTERVALS = (15, 30, 60)
DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A price per kWh in the major currency unit. Wider than any real market, narrow enough to refuse
# a feed that switched to pence or to MWh.
LOW, HIGH = Decimal("-1"), Decimal("5")


def day_path(country: str, feed: str, area: str, day: date | str) -> str:
    """`gb/octopus-agile/a/2026/11/17.json`, under the prices folder."""
    year, month, dom = str(day).split("-")
    return f"{country.lower()}/{feed}/{area}/{year}/{month}/{dom}.json"


def index_path(country: str, feed: str, area: str) -> str:
    return f"{country.lower()}/{feed}/{area}/index.json"


def slots_in_day(day: date, timezone: str, interval_minutes: int) -> int:
    """How many intervals the local day has, which is fewer or more on a clock change."""
    zone = ZoneInfo(timezone)
    start = datetime.combine(day, time(0), zone).astimezone(ZoneInfo("UTC"))
    end = datetime.combine(day + timedelta(days=1), time(0), zone).astimezone(ZoneInfo("UTC"))
    return int((end - start).total_seconds() // (interval_minutes * 60))


def validate_day(doc: Any) -> list[str]:
    """What is wrong with a day file, in plain words. An empty list means it may be stored."""
    if not isinstance(doc, dict):
        return ["the file must be an object"]
    errors = [f"unknown field {k}" for k in sorted(set(doc) - DAY_KEYS)]
    errors += [f"missing field {k}" for k in sorted(DAY_KEYS - set(doc))]
    if errors:
        return errors
    errors = _labels(doc)
    day = _day(doc["date"])
    if day is None:
        errors.append("date must be a calendar date, YYYY-MM-DD")
    try:
        ZoneInfo(str(doc["timezone"]))
    except (ZoneInfoNotFoundError, ValueError):
        errors.append("timezone must be an IANA zone")
    return errors if errors else _prices(doc, day)


def _labels(doc: dict[str, Any]) -> list[str]:
    errors = []
    if doc["schema"] != 1:
        errors.append("schema must be 1")
    errors += [f"{k} must be a lower case slug" for k in ("feed", "area")
               if not isinstance(doc[k], str) or not SLUG.match(doc[k])]
    if doc["interval_minutes"] not in INTERVALS:
        errors.append(f"interval_minutes must be one of {INTERVALS}")
    return errors


def _day(text: object) -> date | None:
    if not isinstance(text, str) or not DAY.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _prices(doc: dict[str, Any], day: date | None) -> list[str]:
    prices = doc["prices"]
    if not isinstance(prices, list) or not all(
            isinstance(p, str) and DECIMAL.match(p) for p in prices):
        return ["prices must be a list of decimal strings"]
    errors = []
    expected = slots_in_day(day, doc["timezone"], doc["interval_minutes"]) if day else 0
    if len(prices) != expected:
        errors.append(f"a {doc['interval_minutes']} minute day on {doc['date']} has {expected} "
                      f"prices, not {len(prices)}")
    outside = [p for p in prices if not LOW <= Decimal(p) <= HIGH]
    if outside:
        errors.append(f"{len(outside)} prices are outside {LOW} to {HIGH} per kWh, "
                      f"for example {outside[0]}")
    return errors


def dumps_day(doc: dict[str, Any]) -> str:
    """The one way a day file is written: keys sorted, prices one per line, so a diff reads."""
    head = {k: doc[k] for k in sorted(doc) if k != "prices"}
    text = json.dumps(head, indent=2, ensure_ascii=False)[:-2]
    body = ",\n".join(f"    {json.dumps(p)}" for p in doc["prices"])
    return f'{text},\n  "prices": [\n{body}\n  ]\n}}\n'


def day_checksum(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def month_checksum(days: dict[str, str]) -> str:
    """One checksum for a month, from its day checksums in date order."""
    return day_checksum("\n".join(f"{day} {days[day]}" for day in sorted(days)))


def feed_index(feed: str, area: str, days: dict[str, str]) -> dict[str, Any]:
    """The index of one feed and area: the latest day and a checksum for each month held."""
    months: dict[str, dict[str, str]] = {}
    for day, checksum in days.items():
        months.setdefault(day[:7], {})[day] = checksum
    return {"schema": 1, "feed": feed, "area": area, "latest": max(days) if days else None,
            "months": {m: month_checksum(d) for m, d in sorted(months.items())}}
