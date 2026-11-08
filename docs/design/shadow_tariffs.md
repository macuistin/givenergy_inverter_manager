# Shadow tariffs

A shadow tariff is an extra tariff priced next to the active one, to show what the same measured
usage would have cost. It observes only. It never changes what the planner or any write does, and
`tests/test_shadow_cannot_write.py` and the shadow case in `tests/test_coordinator.py` enforce that.

## Decisions

- **No accumulator of its own.** Each shadow bill is worked out from the half-hourly slot history
  (kept about 400 days): slots, then bands, then the tariff engine, then the bill. Adding a shadow
  therefore shows the whole current bill period at once, and nothing extra is stored per shadow.
- **Like for like.** The active tariff is priced the same way, from its saved options, so the
  difference between active and shadow uses the same slots, engine and rounding. The existing bill
  sensors are not touched.
- **Where it is set up.** A list of tariff definitions in the options of the existing entry, edited
  in Configure, at most `MAX_SHADOW_TARIFFS` (3). The form is the one the active tariff uses, plus
  a name.
- **Rejected: a config subentry per shadow.** It gives Home Assistant's own add and remove screens,
  but it makes a device per subentry and spreads the settings across the entry.
- **What the user sees.** One "Shadow tariffs" device with, for each shadow, a bill so far, the
  difference from the active tariff (positive means the shadow costs more) and a would-be-cheaper
  flag. All start disabled. No shadow entity exists when there are no shadow tariffs.
- **Bill period.** Every shadow is priced over the active tariff's bill period, even if it would
  bill on another day.
- **Cost.** Pricing is repeated at most every `SHADOW_PRICING_INTERVAL_SECONDS` and reads only.

Not built: running the planner per shadow (#573), a simulated battery (#574), a dashboard card
(#575) and switching a shadow to the active tariff (#576).
