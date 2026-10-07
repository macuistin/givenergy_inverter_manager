# Tariff

The tariff drives the Current Rate sensors, every cost sensor, the cheap-window charge timing and the bill estimates. Enter it at setup, or change it under **Configure**. Field ranges are in [Configuration](configuration.md#step-2-tariff).

## Rate periods

A tariff is one base rate plus up to five timed rate periods.

- The **base rate** applies whenever no timed period is active. It has a name, such as `Day`, that shows in the Current Rate Period sensor.
- Each **timed period** has a name, a rate, a window start and a window end.

Rules for windows:

- Times are `HH:MM` in Home Assistant's time zone.
- The start is included and the end is not. A window `23:00` to `08:00` is active at 23:00 and at 07:59, and not at 08:00.
- A window may cross midnight. If the end is earlier than the start, it runs overnight.
- A window whose start equals its end is never active. The forms reject it, and a stored one is skipped with a warning in the log.
- Names must differ from each other and from the base rate name, ignoring case.
- A slot with an empty name is ignored.

## Which rate applies

1. If any timed periods are active, the **cheapest of them** applies. A timed period wins over the base rate even when the base rate is lower.
2. If none is active, the base rate applies.

The cheapest timed period also sets when the overnight charge is written and which window is sent to the inverter. If the tariff has no timed period, no charge target is written.

## Change the rates from a date

When your supplier changes its prices from a set date, record the new rates with that date. You do not need to be at the screen on the day.

1. Open **Settings → Devices & Services → GivEnergy Inverter Manager → Configure**.
2. Enter the new base rate, base rate name, export rate and timed rate periods in the Tariff and Rate period sections.
3. Open **Dated rate change** and choose the date in **Rates start on**.
4. Save. The page opens with a line that lists the change, and the current rates stay in force until the date.

From the first update cycle on the chosen date, the new rates apply. Before it, the old rates apply. The date is the day in Home Assistant's time zone, so a cheap window that crosses midnight on the day before uses the old rates up to midnight and the new rates after it.

What a dated change covers and does not cover:

- **Covered:** the base rate and its name, the timed rate periods and the export rate.
- **Not dated:** the standing charge, the flat levy, VAT, the supplier discount, the bill start day and the currency. They apply as soon as you save, because the bill sensors work out one bill from one value of each. Change them on the day, or on the day you notice.
- **Nothing is recalculated.** Costs and totals already recorded keep the rates that applied when the energy was used. The date cannot be in the past. If your supplier changed prices before you updated the rates, save the new rates without a date. They apply from that moment, and the costs recorded in between stay as they are.
- **Several changes** can wait at once, one for each date. Recording a second change for the same date replaces the first. Select **Cancel scheduled rate changes** to remove every change that has not started.
- **Later edits.** Once a change has started, its rates are the ones shown in the form. Saving the form without a date sets the rates from now on. A change that has not started yet is kept.

## Stale tariff repair

The repair **Tariff rates have not been reviewed** appears when the tariff has gone 365 days without being saved changed or confirmed. A supplier price change leaves every cost figure wrong until the rates are updated, and nothing in Home Assistant tells you. The date counts from the last time you saved a different tariff in Configure or Reconfigure, recorded a dated change or confirmed the rates in the repair. The first time the integration runs with this feature, it records that day, so an upgrade never raises the repair at once. The first repair comes 365 days later at the earliest. See [Troubleshooting](troubleshooting.md#the-tariff-has-not-been-reviewed).

## Worked example

The numbers below are made up so the arithmetic is easy to follow. They are not a real tariff. Use your own values.

| Name | Rate per kWh | Window |
|---|---|---|
| Day (base rate) | 0.30 | when nothing else applies |
| Night | 0.15 | 23:00 to 08:00 |
| Boost | 0.10 | 02:00 to 04:00 |

Enter the base rate `0.30` named `Day`. Put Night in rate period 1 and Boost in rate period 2.

| Time | Active periods | Rate that applies |
|---|---|---|
| 00:00 to 01:59 | Night | Night, 0.15 |
| 02:00 to 03:59 | Night and Boost | Boost, 0.10 |
| 04:00 to 07:59 | Night | Night, 0.15 |
| 08:00 to 22:59 | none | Day, 0.30 |
| 23:00 to 23:59 | Night | Night, 0.15 |

What follows from this sample tariff:

- The cheapest timed period is Boost, so the charge target and window `02:00` to `04:00` are written to the inverter at 01:59.
- Both Night and Boost count as cheap. The Import at cheap rate sensors count energy imported in either. Import at base rate counts the base rate only.
- The Next Cheap Rate Start sensor shows the start of the next period priced below the base rate. At noon it shows `23:00`.
- On Cheapest Rate is `yes` only during Boost.

Any tariff with timed rates works the same way, whatever the supplier or country: two periods that do not overlap, three that do, or a single overnight window. A tariff with no timed rates is a flat tariff. Leave every rate period name empty.

## Bill line items

All amounts use your tariff values. The percentages are the VAT rate and the supplier discount. Set either to 0 if your tariff has none.

| Line | Formula |
|---|---|
| Import energy | kWh x rate x (1 - discount) x (1 + VAT) |
| Export earnings | kWh x export rate. No discount, no VAT |
| Standing charge and flat levy | (daily standing charge x days + levy x days / days in the bill period) x (1 + VAT). No discount. The levy is one flat amount per bill period, so a full period charges it once |

With the sample tariff above, a 5% discount, 10% VAT, a standing charge of 0.60 a day, a flat levy of 1.50 and an export rate of 0.15, the cost of 10 kWh is:

| Case | Calculation | Result |
|---|---|---|
| Import at 03:00 (Boost) | 10 x 0.10 x 0.95 x 1.10 | 1.0450 |
| Import at 12:00 (Day) | 10 x 0.30 x 0.95 x 1.10 | 3.1350 |
| Import at 23:30 (Night) | 10 x 0.15 x 0.95 x 1.10 | 1.5675 |
| Export | 10 x 0.15 | 1.5000 |
| Standing charge and levy for 10 days of a 31 day period | (0.60 x 10 + 1.50 x 10 / 31) x 1.10 | 7.1323 |

### Bill sensors

Accrued Bill This Period is the bill so far, worked out the way a supplier works it out. Each line is rounded to the smallest currency unit, such as cents.

| Line | Formula |
|---|---|
| Energy | kWh x rate for each rate period, summed over the bill period |
| Supplier saving | Discount % of the energy line. Energy only |
| Standing charge | Daily standing charge x days elapsed |
| Flat levy | One flat amount per bill period, charged in proportion to the days elapsed |
| VAT | VAT % of energy less saving, plus standing charge, plus levy |
| Export credit | Export kWh x export rate. No VAT, and taken off after VAT |

The accrued bill is energy less saving, plus standing charge, levy and VAT, minus the export credit. It reads the month totals, which reset on the bill start day.

Projected Bill This Period is the accrued bill divided by the days elapsed, times the days in the whole period.

Days elapsed is the day of the bill period: the bill start day is day 1. Days remaining is the days left after today, so elapsed plus remaining is the length of the period (28 to 31 days).

Example with the sample tariff: a 31 day period from the 16th to the 15th, bill start day 16, with 150 kWh at Boost, 40 kWh at Day and 500 kWh at Night, and 180 kWh exported.

| Line | Calculation | Amount |
|---|---|---|
| Energy | 150 x 0.10 + 40 x 0.30 + 500 x 0.15 | 102.00 |
| Supplier saving | 5% of 102.00 | -5.10 |
| Standing charge | 31 x 0.60 | 18.60 |
| Flat levy | flat, full period | 1.50 |
| VAT | 10% of 117.00 | 11.70 |
| Export credit | 180 x 0.15 | -27.00 |
| Bill | | 101.70 |

On the last day of the period the accrued and projected bill are both 101.70.

### Where costs go

Each cycle's import cost is split between the EV charger, the immersion and the rest of the house in proportion to their share of the house load. The split feeds EV Charging Cost Today, Immersion Cost Today and House Cost Today. Costs are also recorded per rate period name.

## Other fields

Take every value from your supplier bill or tariff sheet. The form is pre-filled with placeholder defaults taken from an Irish domestic tariff. They are not a recommendation, so replace all of them.

| Field | What it is and where to find it | Effect of a wrong value |
|---|---|---|
| Base rate | Price per kWh outside every timed period, before VAT. Default 0.3334 | Every import cost outside the timed windows is wrong by the same factor |
| Export rate | Amount paid per kWh sent to the grid. Called CEG in Ireland, and a feed-in or export tariff elsewhere. Default 0.195 | Export earnings, the immersion and battery export checks and the appliance advice use it |
| Standing charge | Fixed daily charge, before VAT. Default 0.8259. Enter 0 if you have none | The bill sensors are off by the difference times the days elapsed |
| Flat levy (PSO levy) | One flat amount per bill period, before VAT. Named after the Irish public service obligation levy. Enter any flat per-period charge here, or 0. Default 1.46 | The bill sensors are off by that amount, spread over the days |
| VAT rate | Percentage added to energy, the standing charge and the levy. Read it from your bill. If your rates already include tax, enter 0. Default 9.0 | Every import cost and the bill scale by the same factor. An error of a few points shifts every cost figure by that many percent |
| Supplier discount | Percentage taken off the energy rate only, before VAT, for example for paying by direct debit. Enter 0 if you have none. Default 5.5 | Import costs and the bill energy line are off by the difference |
| Bill start day | The day your bill period starts, 1 to 28. See the note on the month reset in [Configuration](configuration.md#things-to-know) | The month totals reset on the wrong day and the projected bill uses the wrong period length |
| Currency | Sets the symbol on money sensors. It does not convert any amounts | Only the symbol is wrong |

Check the values against your latest bill whenever your supplier changes its prices. Costs stay wrong until you update them, because the integration does not read your supplier's rates.
