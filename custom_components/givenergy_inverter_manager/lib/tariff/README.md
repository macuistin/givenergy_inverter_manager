# lib/tariff

The tariff model and the money maths: timed rate periods (including ones that run past midnight),
the cheapest rate in force, running energy and cost totals for a billing period, a bill line by
line and the value of energy held in a battery. It needs no Home Assistant objects and does not
read option keys.

## Public names

- `RatePeriod`, `TariffConfig`: the tariff, built from typed fields
- `EnergyAccumulator`, `CounterMemory`: running totals for a billing period
- `BillBreakdown`, `money`: a bill rounded to cents, halves upward (`Decimal`, `ROUND_HALF_UP`)
- `reprice`, `import_by_band`, `BillPeriod`, `Rounding`, `Repriced`: price slots under a tariff (see below)
- `price_period`, `PeriodRules`, `PeriodBill`, `bill_period_bounds`, `start_day_of`: the bill so far for the current bill period, priced from the slot history (see below)
- `SlotDay`, `SlotEnergy`, `SlotHistory`, `FLOWS`, `DEFAULT_LOADS`: energy in half-hour slots, a local day at a time, kept for
  about 400 days (see below)
- `StoredEnergy`, `stored_energy_change`, `value_per_stored_kwh`: the value of stored energy

## Half-hourly slots

`SlotDay` holds one local day. Supply flows (`FLOWS`: import, export, solar, battery charge,
battery discharge, grid-to-battery) are kept apart from loads by name (house, EV and immersion
are always there, and another can be added by name). Every figure is a reading and none is
derived from the others, so drift in one source shows rather than being absorbed. Each slot
also holds the seconds actually observed, which tells a slot with no data from one that used
nothing, and the battery state of charge at its end. Slots are counted in real elapsed time from
local midnight, so a day has 46, 48 or 50 of them across a clock change.

Stored form (`StoredSlotDay`, a `TypedDict` in `slots.py` that defines it and says what each field means;
written by `SlotDay.to_storage`): `version`, `date`, `start` (midnight with its UTC offset),
`slots`, `flows_wh` and `loads_wh` (whole watt-hours per slot), `soc_pct`, `seconds`. A day saved
under another time zone or version is skipped, not converted.

`SlotHistory.record` spreads an interval over the slots it touches by time, splits it at
midnight, ignores an interval over 30 minutes (a gap) and drops days past the retention.
`to_storage` writes whole watt-hours and seconds, and `restore` skips and counts unreadable days.
The data does not depend on any tariff, so it can be priced under any of them later.

## Repricing

`reprice(days, tariff, BillPeriod(days, period_days), rounding)` prices the slots of a bill period
under a `TariffConfig` and returns the kWh in each rate band, the energy cost, the export credit
and the bill line by line. The slots hold no price, so the same days can be priced under any
tariff. Import is priced at the rate in force when each slot starts, so a rate window that starts
inside a half hour is priced as if it began at the slot start.

`Rounding.PER_BAND` rounds each band's cost to the cent before the rest of the bill, as a supplier
bill does, and reproduces a real bill exactly. `Rounding.TOTAL` adds the bands and rounds once,
which is what the cost sensors add up, and can be a cent out. `tests/lib/tariff/test_reprice.py`
has a worked bill as a test case.

## Bill so far from the history

`price_period(history, definition, through)` prices the bill period holding the day `through` under
a `TariffDefinition`: slots go through `bands.import_by_band`, then `engine.price_bill`. The bill
covers the period start to `through`, that day included, and the share of the monthly levy follows
the length of the whole period. `PeriodRules(start_day=...)` takes the bill dates from another
tariff, so two definitions are priced over the same days. `PeriodRules(is_holiday=...)` says which
dates are public holidays. `PeriodBill.data_from` is the first day the history holds inside the
period and `coverage` is the observed share of the days priced. A definition from
`definition_from_config` agrees with the bill the options give, to the cent on the worked October
bill (`tests/lib/tariff/test_period_bill.py`).

## Definitions

A tariff and its bill can be written as one JSON document, which is data and not code.
`load_definition(text)` or `parse_definition(mapping)` returns a frozen `TariffDefinition`, or
raises `DefinitionError` with the path of the field that is wrong, such as
`bill.total.of.charges.mode`. The types are in `definition.py` and the reader in
`definition_parse.py`. The document holds the provider, country and optional region, the dates it
applies (`effective_from` included, `effective_to` excluded), the prices, the customer's own
inputs, the bill as a tree and worked bills it must reproduce (`checks`).

- Money is a decimal string. A JSON number with a decimal point, `NaN` and `Infinity` are refused.
- The bill is a tree of a closed set of node kinds: `energy_by_band`, `export_credit`, `per_day`,
  `per_period`, `adjust`, `tax` and `sum`. Nesting sets the order and the tax base. A `sum` holds
  its children by name, so no list position matters. An unknown kind or field is refused.
- A zone has a unique priority, and the applicable zone of highest priority wins.
- `export` has a `base` price and may have `zones`, written like the import zones, for an export
  price that changes with the time of day. With no zones the export price is flat.
- A check gives `export_kwh` as one figure, paid at the base export price, or as an object of
  kWh by export band.
- `complete` is allowed only with at least one entry in `checks`.
- There is no checksum in the document. It belongs to the index entry for the file.

`price_bill(definition, BillInputs(days, period_days, import_kwh_by_band, export_kwh))` prices a
bill in `Decimal` and returns the tree with an amount on every node (`Line`), so each tax base can
be checked. A credit is a negative amount. Each node rounds to the currency's smallest unit, halves
upward, unless it says `round: none`. `verify_checks(definition)` prices each worked bill in the
document and raises `CheckFailed` if one gives another total. The engine reads band totals, not
slots. `bands.import_by_band(days, definition, is_holiday)` turns stored slots into those totals:
each slot takes the band in force at its start on the definition's clock, the zone of highest
priority winning (`band_at` gives one moment's band). `bands.export_by_band` and `export_band_at`
do the same for exported energy, and `price_period` uses them when the export has zones. In
`BillInputs`, `export_kwh` is one figure or the kWh in each export band, and a banded credit lists
its bands as child lines. A zone past midnight belongs to the day it
began. Whether a date is a public holiday is passed in, because the package has no calendar. `tests/lib/tariff/test_engine.py` reproduces a worked October bill (187.35).

`definition_from_config(config, Locale(currency, country, timezone_name, effective_from))` writes
a `TariffConfig`, the tariff as the options hold it, as a definition and reads it back through
`parse_definition`. The cheapest-wins rule becomes priorities, the dearest timed rate lowest. It
prices the same bill as `TariffConfig.calculate_bill`, which `tests/lib/tariff/test_compile.py`
checks across bill lengths and tariff shapes. A bill start day after the 28th is refused, because
a monthly period can name days 1 to 28 only. The options hold no ISO currency code, country or
time zone, so the caller supplies them.

## Index and sources

`build_index(files, generated)` makes the tariff index from definition files (path to text). The
index is grouped by country, then provider, then tariff, and each revision has its dates, path and
a checksum over the file's canonical form (keys sorted, no spaces). The build refuses a file that
is not at `country/provider/tariff/revision.json`, revisions of one tariff whose dates overlap, and
a `supersedes` naming a revision that is not there. `latest` is the revision in force on the day the
index was generated, and is null while all revisions are still to come.

`parse_index(text)` reads an index back. `find_tariff` and `revision_in_force(tariff, day)` choose
the revision that prices a day (the end date is excluded). A `TariffSource` hands over the index and
the files. `load_revision(source, entry)` checks a file against its entry's checksum
(`ChecksumMismatch`), parses it, and refuses one whose revision or dates disagree with the entry.
An entry with no checksum, as a local definition has, is parsed but not checksummed. The library
reads no disk or network; the source does.

## Allowed dependencies

The standard library and `lib/timeutil`.

## Not here

Reading the saved options by `CONF_` key (`core/tariff.py`: `build_tariff`, the dated rate
changes and the option saves) and the tariff snapshot (`core/tariff_snapshot.py`) stay in the
integration, because they name the integration's own keys. The stored bill rows themselves
(`bill_days`: `day_row`, `with_day`, `tariff_in_effect`, `tariff_changes`) are here.
