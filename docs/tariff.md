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

## Worked example: Electric Ireland Night and Nightboost

These are the defaults pre-filled at setup.

| Name | Rate per kWh | Window |
|---|---|---|
| Day (base rate) | 0.3334 | when nothing else applies |
| Night | 0.1644 | 23:00 to 08:00 |
| Nightboost | 0.0965 | 02:00 to 04:00 |

Enter the base rate `0.3334` named `Day`. Put Night in rate period 1 and Nightboost in rate period 2.

| Time | Active periods | Rate that applies |
|---|---|---|
| 00:00 to 01:59 | Night | Night, 0.1644 |
| 02:00 to 03:59 | Night and Nightboost | Nightboost, 0.0965 |
| 04:00 to 07:59 | Night | Night, 0.1644 |
| 08:00 to 22:59 | none | Day, 0.3334 |
| 23:00 to 23:59 | Night | Night, 0.1644 |

What follows from this tariff:

- The cheapest timed period is Nightboost, so the charge target and window `02:00` to `04:00` are written to the inverter at 01:59.
- Both Night and Nightboost count as cheap. The Import at cheap rate sensors count energy imported in either. Import at peak rate counts the base rate only.
- The Next Cheap Rate Start sensor shows the start of the next period priced below the base rate. At noon it shows `23:00`.
- On Cheapest Rate is `yes` only during Nightboost.

## Bill line items

All amounts use your tariff values. The percentages are the VAT rate and the supplier discount.

| Line | Formula |
|---|---|
| Import energy | kWh x rate x (1 - discount) x (1 + VAT) |
| Export earnings | kWh x export rate. No discount, no VAT |
| Standing charge and PSO levy | (daily standing charge x days + PSO levy x days / days in the bill period) x (1 + VAT). No discount. The PSO levy is one flat amount per bill period, so a full period charges it once |

With the default tariff and 10 kWh:

| Case | Calculation | Result |
|---|---|---|
| Import at 03:00 (Nightboost) | 10 x 0.0965 x 0.945 x 1.09 | 0.9940 |
| Import at 12:00 (Day) | 10 x 0.3334 x 0.945 x 1.09 | 3.4342 |
| Import at 23:30 (Night) | 10 x 0.1644 x 0.945 x 1.09 | 1.6934 |
| Export | 10 x 0.195 | 1.9500 |
| Standing charge and PSO for 10 days of a 31 day period | (0.8259 x 10 + 1.46 x 10 / 31) x 1.09 | 9.5157 |

### Bill sensors

Accrued Bill This Period is the bill so far, worked out the way the supplier works it out. Each line is rounded to cents.

| Line | Formula |
|---|---|
| Energy | kWh x rate for each rate period, summed over the bill period |
| Supplier saving | Discount % of the energy line. Energy only |
| Standing charge | Daily standing charge x days elapsed |
| PSO levy | One flat amount per bill period, charged in proportion to the days elapsed |
| VAT | VAT % of energy less saving, plus standing charge, plus PSO levy |
| Export credit | Export kWh x export rate. No VAT, and taken off after VAT |

The accrued bill is energy less saving, plus standing charge, PSO levy and VAT, minus the export credit. It reads the month totals, which reset on the bill start day.

Projected Bill This Period is the accrued bill divided by the days elapsed, times the days in the whole period.

Days elapsed is the day of the bill period: the bill start day is day 1. Days remaining is the days left after today, so elapsed plus remaining is the length of the period (28 to 31 days).

Example from a real bill, 16 August to 15 September, 31 days, bill start day 16:

| Line | Calculation | Amount |
|---|---|---|
| Energy | 154 kWh x 0.1056 + 33 kWh x 0.365 + 517 kWh x 0.18 | 121.37 |
| Supplier saving | 5.5% of 121.37 | -6.68 |
| Standing charge | 31 x 0.8259 | 25.60 |
| PSO levy | flat, full period | 1.46 |
| VAT | 9% of 141.75 | 12.76 |
| Export credit | 179 kWh x 0.195 | -34.91 |
| Bill | | 119.60 |

On 15 September the accrued and projected bill are both 119.60.

### Where costs go

Each cycle's import cost is split between the EV charger, the immersion and the rest of the house in proportion to their share of the house load. The split feeds EV Charging Cost Today, Immersion Cost Today and House Cost Today. Costs are also recorded per rate period name.

## Other fields

| Field | Notes |
|---|---|
| Export / CEG rate | Paid per kWh exported. Default 0.195 |
| Standing charge | Fixed daily charge. Default 0.8259 |
| PSO levy | One flat amount per bill period. A part period is charged in proportion to its days. Default 1.46. Set 0 if you have none |
| VAT rate | Default 9.0 |
| Supplier discount | Default 5.5. Applied to import energy only |
| Bill start day | 1 to 28. See the note on the month reset in [Configuration](configuration.md#things-to-know) |
| Currency | Changes the symbol on money sensors. The rate fields always say EUR/kWh |

Take every value from your bill. The defaults are in `const.py` and match an Irish domestic tariff.
