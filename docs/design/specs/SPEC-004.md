# SPEC-004: a solar diverter inside the charge plan

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


**Source:** Predbat, `prediction.py` (the per-step forward model) and `docs/customisation.md` (iBoost options), read October 2026. **Feeds:** S4, N4. **Nothing here is code.**

#### What it does
For each step of the forward simulation it decides whether a solar diverter (immersion heating) would run, how much energy it would take, and adds that energy to the house load, so the battery plan accounts for it.

#### Inputs (settings and live values)
Enable switch; a cap on energy per day; the energy already used today (resets at midnight); maximum and minimum power; a minimum battery state of charge; whether it may run during an export window; whether it should stop the battery discharging while it runs; import and export price thresholds; an optional gas price with a scale factor; an optional list of planned slots; options to run on grid charging and on solar.

#### Behaviour, for each simulation step
1. **Price test.** The step is allowed only if the import price does not exceed the import threshold and the export price does not exceed the export threshold. Optionally also only if the import price is no more than the gas price times the scale (and the same for export), so electricity heats water only when it is cheaper than gas.
2. **Planned slots.** If a plan lists slots and the step is not inside an export window (or export is allowed), the diverter takes the planned energy for the step, limited to the maximum power for the step and to what remains of the daily cap.
3. **Charging.** If it may run on grid charging, the price test passes, the daily cap is not reached and a grid charge window is active, it takes the smaller of maximum power for the step and the remaining cap.
4. **Solar.** If solar diversion is on, the price test passes, the cap is not reached, **solar in the step exceeds the minimum power for the step**, the battery's state of charge is at or above the minimum, and the step is not an export window (or export is allowed): it takes the smaller of the step's solar, the maximum power for the step minus anything already taken, and the remaining cap. That energy is removed from solar and added to load.
5. **Discharge freeze.** If the diverter is taking energy and the freeze option is on, battery discharge is blocked for the step.
6. The running total for the day is updated, and the plan reports the energy used by the diverter and whether it is running now (from planned slots or from solar).

#### Outputs
A daily energy figure that resets at midnight, an "active now" flag for automations, and a per-slot diverter column in the plan.

#### Quirks
The solar branch uses the step's solar energy, not the battery's spare capacity, so the battery still fills first only through the minimum state-of-charge setting.

#### Questions for our code
We switch the immersion on from rules with a state-of-charge threshold and temperature. Do we cap the energy per day? Do we have a minimum power test, a price test against gas or another source, or a freeze on discharge? Does our charge plan include the diverter's energy (it excludes it from the learned load already)?


---

