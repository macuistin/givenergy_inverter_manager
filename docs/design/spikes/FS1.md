# FS1: what do the forecast providers give us?

## Question

Can the overnight charge simulation use the forecast's own hour-by-hour shape instead of a bell curve centred on 13:00, and which providers can give it?

## Method

- Read the attributes of a Solcast PV Forecast "Forecast Tomorrow" sensor on a running Home Assistant (12 October 2026, Solcast integration with its half-hourly detail attributes on). An anonymised copy is `tests/fixtures/forecast/solcast_tomorrow.json`.
- Read the Home Assistant documentation for the Forecast.Solar integration, and Predbat's install documentation for how it reads Solcast.
- Not tried: a running Forecast.Solar, its `forecast_solar.get_forecast` action, and Open-Meteo. None is installed on the test install, and the documentation does not give the response fields.

## Result

| Provider | Interface | Shape available | Period | Unit | Time zone |
|---|---|---|---|---|---|
| Solcast | Sensor attribute `detailedForecast` on the today and tomorrow forecast sensors | Yes | 30 minutes | `pv_estimate`, `pv_estimate10` and `pv_estimate90` in kW, the average power over the period | `period_start` carries the local offset, for example `2026-10-13T08:30:00+01:00` |
| Solcast | Sensor attribute `detailedHourly` | Yes | 1 hour | the same, in kW | the same |
| Forecast.Solar | Sensors (today, tomorrow, remaining, this hour, next hour) | No: totals and the next one or two hours only | n/a | kWh, W | n/a |
| Forecast.Solar | Action `forecast_solar.get_forecast` | Probably, not verified | unknown | unknown | unknown |
| Any provider | Home Assistant's solar forecast platform, as the Energy dashboard reads it | Yes in principle | per provider | Wh per period | per provider |

Solcast's units are power, not energy: the 48 `pv_estimate` values of the fixture add up to 67.15, and half of that, 33.58 kWh, is the sensor's state. A reader that took them as kWh would double the day. The period length is therefore taken from the gap between `period_start` values, never assumed.

Solcast lets a user switch the half-hourly detail off. The documentation of Predbat says that with it off each hourly value is treated as a half-hour one and the forecast doubles. This integration reads the hourly attribute when the half-hourly one is missing and spreads each hour over its two slots.

## Decisions

- **Solcast gives a shape and is used.** The shape is read from the tomorrow sensor's own attributes, the same sensor the total comes from. This needs no new setting and no service call, like the `estimate10` attribute the integration already reads.
- **Forecast.Solar keeps the standard curve.** Its sensors carry totals only, which the card allows. The action is not used because its response is unverified, and a call needs a config entry id and a response. A later release can add it once somebody can read a real response.
- **Home Assistant's solar forecast platform is not used.** A custom integration would have to reach into the Energy dashboard's manager and its registered platforms, which are internal and change between releases.
- **Open-Meteo is not a supported provider** here, so its `watts` and `wh_period` attributes are not read.
- **Midnight to 08:00.** The sensors move on a day at midnight: the tomorrow sensor then holds the day after. The integration already remembers the total it saw last before midnight, and now remembers the shape with it, so the period from midnight to 08:00 plans with the shape of the day being charged for. A total that arrives without a shape clears the old shape, so a shape is never paired with a different forecast.
- **Clock-change days.** Periods are mapped on the local clock. The missing hour of a spring day gets weight 0, and the repeated hour of an autumn day adds into one slot.

## What happens when `estimate10` is off

Solcast can switch its per-estimate attributes off. The integration then has no P10 value, the cautious blend is skipped, and the charge reason says so ("no low estimate available, so the forecast is used as it is"). It is not silent. Whether `estimate10` is on by default in Solcast was not verified.

## What Predbat does differently

Predbat reads the half-hourly Solcast values directly, and keeps a per-slot forecast for several days rather than a total spread with a curve. It also scales the forecast by a configured factor. This integration already scales the total by the measured accuracy of the last 14 days (`docs/concepts.md`), and the shape now rides on that scaled total. Predbat's per-slot modelling of cloud is not adopted.

## Not verified

- A running Forecast.Solar, Open-Meteo, or a Solcast with the detail switched off. The fixtures for those are synthetic.
- Solcast's own default for the detail attributes.
