# SPEC-001: PALM overnight charge target

> **Where the parts of the 0.19 plan are.** This plan was written as one file in four parts. References such as "Part A" or "Part B section 1.5" mean:
> 
> | Part | File |
> |---|---|
> | Part 0 (instructions for the agent) | [RELEASE_0.19_AGENT_NOTES.md](RELEASE_0.19_AGENT_NOTES.md) |
> | Part A (the release brief) | [RELEASE_0.19_BRIEF.md](RELEASE_0.19_BRIEF.md) |
> | Part B (design pack for the roadmap features) | [FEATURE_DESIGNS.md](FEATURE_DESIGNS.md) |
> | Part C (specifications extracted from other projects) | [specs/](specs/README.md) |
> | Part D (gap analysis) | [GAP_ANALYSIS.md](GAP_ANALYSIS.md) |
> 


**Source:** `palm_utils.py` and `palm_soc.py` in [salewis38/palm](https://github.com/salewis38/palm), version 1.1.4 of the utilities, read October 2026, plus the project README and GivTCP's settings table for the SmartTarget variant. **Roadmap:** supports S5, C24, C25, C28 and the v0.19 re-plan and seasonal rules.

#### 2.1 What it does

Once a night it chooses how full to charge the battery from the grid. It simulates the next two days half hour by half hour, starting from an empty-to-reserve battery, using a blended solar forecast and the household's usual load. It then picks the target that lets tomorrow's solar fill the battery without wasting it, while keeping a floor for the evening and for the dip before the sun comes up.

#### 2.2 Inputs

| Input | Meaning |
|---|---|
| Forecast, three estimates | Low (10%), middle (50%) and high (90%) energy for each half hour of tomorrow and the day after, in kWh, summed across arrays (up to two), aligned to local time |
| Conservatism weight | A number from 10 to 90. Default 35. Out-of-range values are clamped |
| Load profile | Expected house energy for each of 48 half-hours, in kWh |
| Usable capacity | Battery energy that can be used, in kWh |
| Reserve percent | Battery reserve held for power cuts. Minimum 4 |
| Charge rate | Inverter charge and discharge limit, in kW |
| Charge window end | The half-hour index when the grid charge ends |
| Month | Used to pick winter, shoulder or summer behaviour |
| Floors | Minimum target in summer (default 25 percent) and in shoulder months (default 45 percent) |

#### 2.3 Preparing the inputs

**Forecast blend.** The weight selects a point between the percentiles. Compute three factors: the low-estimate factor is `50 - weight` and not below zero; the high-estimate factor is `weight - 50` and not below zero; the middle factor is `weight - 10` when the weight is 50 or less, and `90 - weight` above 50. The blended generation for a half hour is the three estimates multiplied by their factors, divided by the sum of the factors. Effects: weight 10 is the low estimate only, 50 is the middle only, 90 is the high only, and values between mix the two nearest percentiles in proportion. **At the default weight of 35 the blend is 37.5 percent low and 62.5 percent middle.**

**Load profile.** The expected load for each half hour is a weighted average over the previous days. A list of per-day weights is configured. A day with weight zero or less is skipped. The result is divided by the total weight. If the total weight is zero it logs an error and treats it as one (so the profile is wrong, not absent). Each day's half-hour energy is the difference between successive cumulative "consumption today" readings sampled every half hour. If the job runs after 21:00 local, "yesterday" means today, so the most recent day is not missed.

**Forecast alignment.** The forecast arrives in 30-minute periods tagged with an end time. It is shifted to local time, summed across arrays using the shorter of the two lengths, and converted to kWh per half hour. If it is already past midday when the forecast is read, the first day is dropped and the next day becomes "tomorrow".

#### 2.4 The simulation

Run it twice, once for tomorrow and once for the day after. For each day:

1. Start the battery at the reserve energy. Record the starting value as both the highest and lowest charge seen.
2. For each of the 48 half hours:
   - **During the grid charge window** (up to and including the window-end index): the house is treated as supplied by the grid. The load is zero and the battery stays where it started.
   - **After the window**: the battery changes by the blended generation minus the load for that half hour, limited to plus or minus the charge rate. The charge is **not capped at capacity**, so it can go above 100 percent or below zero. That is deliberate. The excess above 100 percent is the solar that the battery cannot absorb.
3. **Forward tracking.** While the charge is falling and the highest value so far has not risen above the reserve, track the lowest value. Once past the window, track the highest value.
4. **Backward pass.** Find the last half hour whose charge equals the day's highest value, and take the lowest charge at or before it. That is the true low point before the peak (the first low seen going forward may not be the lowest).
5. Convert the highest and lowest to whole percentages of capacity.

#### 2.5 The target

1. **Day-after correction.** If tomorrow's peak is below 100 percent and the day after's peak is above 100 percent, add half of the day after's excess over 100 (whole percent) to tomorrow's peak. This lowers tonight's target to leave room for a sunnier day after.
2. **Floor.** Use the shoulder-month floor (default 45) in shoulder months, otherwise the summer floor (default 25).
3. **Target** is the largest of three numbers, limited to 100:
   - `100 - peak` (room so that tomorrow's solar just fills the battery),
   - `floor - lowest` (lift so that after the dip before the sun, the battery still holds the floor above its start; the lowest is usually negative, which raises the target),
   - the floor itself.

#### 2.6 Seasonal and failure behaviour

- **Winter months** (default January to March and October to December): target 100 and no calculation. The charge window end is set to a separate, normally longer, winter end time.
- **Shoulder months** (default April, May and September): use the higher floor, because load varies (heating).
- **Missing forecast** (the middle estimate for tomorrow is zero or absent): target 100.
- **Forecast download fails**: use the previous values if there are any, otherwise treat as missing.
- **A second calculation** runs about an hour before the cheap window ends, to catch a changed forecast (README).
- **Writing:** one target write, and optionally the window start and end. The cloud variant reads the setting back after about three seconds and logs a failure if it differs. The local variant queues a charge-target write and falls back to the cloud on error.

#### 2.7 How the inverter treats the target (from the same sources)

A forum answer describing GivTCP's SmartTarget says: the target is applied only if "enable charge target" is on, which overrides the slot targets; the charge slot is then set to the cheap window with target 100, and the percentage in the slot is ignored in favour of the target. The app's "charge now" sequence sets a window of 00:01 to 23:59, enables charging and the target, sets the target to 100 and the rate to full. "Pause" sets the charge and discharge rates to zero. These match the questions U2 and U8.

#### 2.8 Quirks and probable defects

1. **The rate limit is applied per half hour without halving.** A 2.5 kW limit caps each half hour at 2.5 kWh, twice what the inverter can deliver. It rarely binds, but our model should use rate times half an hour.
2. **The backward pass uses a list that begins with a label.** Its indexes are shifted by one slot, so it covers the first 47 half hours, not all 48. Edge cases around the last half hour can differ by one value.
3. **The first comparison at the start of a day** looks at the previous element of a list, which wraps to the end. Harmless in practice.
4. **Charge is uncapped** (see 2.4). A reader may take it for a bug. It is the mechanism.
5. **The winter month check is skipped in test mode**, so a dry run in winter shows a calculated target that the live run would not write.
6. **The target ignores export.** It assumes extra solar is lost or exported for little. Its author has since written that with higher export payments a full overnight charge makes more sense, and removed the forecast from the newer local version for that reason ([PALM 2 issue](https://github.com/salewis38/palm2/issues/1)).

#### 2.9 Test vectors

Computed with a reference model written from sections 2.3 to 2.5. **Not a run of PALM.** Setup: capacity 10 kWh, reserve 4 percent, charge window ends at half-hour index 9, rate limit not binding, load 0.3 kWh in every half hour after the window, floors 25 (summer) and 45 (shoulder), summer month. Solar for the day is the shape below over half hours 14 to 33 (07:00 to 17:00) multiplied by a scale; the low estimate is 0.5 times the middle and the high estimate 1.25 times the middle.

Shape (kWh at scale 1): 0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 1.00, 1.05, 1.05, 1.00, 0.90, 0.80, 0.65, 0.50, 0.35, 0.20, 0.10, 0.05, 0.00. A scale of 1 gives 11.15 kWh a day.

| Scenario | Day 1 scale | Day 2 scale | Weight 10 | Weight 35 | Weight 50 | Weight 70 |
|---|---|---|---|---|---|---|
| A. Normal | 1.0 | 1.0 | 96 | 69 | 49 | 35 |
| B. Dull, then very sunny | 0.5 | 2.2 | 100 | 89 | 79 | 39 |
| C. Very sunny | 1.8 | 1.8 | 59 | 34 | 34 | 33 |
| D. No sun | 0.0 | 0.0 | 100 | 100 | 100 | 100 |

Hand checks. **D:** with no solar the day-one peak equals the start, so `100 - peak` is 96, but the dip is deep (about minus 110 percent), so `25 - (-110)` is above 100 and the target is limited to 100. **A at weight 10:** the low estimate never lifts the battery above its start, so the target is `100 - 4 = 96`. **C at weight 35:** the day's peak is 101 percent, so the first term is not positive. The dip is about minus 9 percent, so the second term is 34, which becomes the target. **B at weight 35:** day one peaks at 4 percent and day two at 137, so the correction adds 18 to day one's peak (22), the first term is 78, the dip term is 89, and the target is 89.

#### 2.10 Questions for our code (card SP1)

Our `core/rules.py` finds the smallest overnight charge that keeps the battery above the minimum all day, then lowers it for the day-after correction and raises it for a plugged-in car. PALM instead sizes the target so that tomorrow's solar fills the battery, with a floor and a dip term. They aim at the same outcome by different routes. **Do not change behaviour on this evidence.** Run the vectors and report:
1. Where do the two targets differ on scenarios A to D, and by how much?
2. Does our simulation also leave room for solar that would otherwise overflow, or does it stop at "never below the minimum"?
3. Is our day-after correction the same size (half the excess over 100) and under the same conditions (tomorrow below 100 and the day after above)?
4. How does our forecast blend compare? Ours blends the middle estimate toward the low one by a fraction; PALM's weight 35 is 37.5 percent toward the low estimate.
5. Do we cap the rate per half hour as rate times 0.5?
6. Does our fail-safe for a missing forecast give 100?
7. What happens in a dry run in winter?

---

