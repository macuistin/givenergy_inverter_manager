# lib/solar

Solar forecast handling for a home battery, with no Home Assistant objects.

- `shape`: turns a forecast's per-period power list (Solcast `detailedForecast` style, half-hourly
  or hourly) into 48 half-hour weights on the local clock, checks a stored shape, finds the minute
  solar ends, and lists the producing hours. A clock-change day still lands each period in the slot
  of its local time. Anything that does not look like a day of forecast gives `None`, and the
  caller keeps `DEFAULT_SOLAR_SHAPE` (a bell curve centred on 13:00).
- `day`: `settled_solar_w` and `HeldSolarDay` debounce "has the solar day started" so a reading that
  wanders across the noise floor at dawn and dusk does not flip the decision every cycle.
- `seeding`: `seed_forecast_records` pairs recorded forecast readings with the recorded daily solar
  counter and returns the nightly forecast-versus-actual records a new install would otherwise
  wait several nights for. The host reads its own history and passes `RecordedReadings` in.
- `defaults`: `SOLAR_NOISE_FLOOR_W`, `SOLAR_DAY_DEBOUNCE_MINUTES`, `SOLAR_STALE_AFTER_S`.

Pass the time and the time zone in. Nothing here reads the clock.

## Allowed dependencies

The standard library and `lib/timeutil`.

## Not here

Finding a forecast sensor among the entities (`discovery/forecast.py`, which also finds immersion
switches for the wizard), reading the recorder (`forecast_seeding.py`), and the charge decisions that
use the shape (`core/rules.py`) stay in the integration.
