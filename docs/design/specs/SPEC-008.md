# SPEC-008: a departure-time charging plan

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


**Source:** evcc, `core/planner/planner.go` and `planner.md`, read October 2026 from a sparse clone. **Feeds:** N13 (and the immersion ready-by plan). **Nothing here is code.**

#### What it does
Given a required charging duration, a target time and a list of priced slots, it builds the cheapest plan that finishes by the target, and says whether the plan is active now.

#### Inputs
Required duration; target time; an optional "precondition" duration to run immediately before the target; a flag for a single continuous block; the tariff's rates (start, end, price).

#### Behaviour
1. **Nothing to do** if the duration is zero or less.
2. **Latest start** is the target minus the duration. If that is already past, start now and move the target to now plus the duration.
3. **No tariff, no rates, or an error:** the plan is one block from the latest start to the target. Cost is ignored and only time is respected.
4. **Not enough time left:** if the time to the target is no more than the duration, charge continuously from now (a continuous block clamped to the available rates, with any gaps at the start or end filled by unpriced slots).
5. **Rates end before the target:** if the time after the last rate is enough for the whole duration, plan nothing now (the rest can be done later). If not, plan only the part that must use the known slots, and shorten the horizon to the last known rate.
6. **Clamp** the rates to the interval from now to the target. If the clamped rates cover less than the duration, fall back to the simple plan.
7. **Precondition.** Do not let it exceed the duration. Move the target earlier by that amount, set those last slots aside, and shorten the duration. If nothing remains, the plan is only those slots.
8. **Choose the slots.** If a continuous block is wanted, find the cheapest continuous window in the remaining time. Otherwise sort the slots by price (ties stable) and take slots until the duration is met. **If the last slot taken covers more than is needed, shorten it: the first slot (when there are several) is moved later so it starts as late as possible, any other is cut at the end.** Sort the chosen slots by time.
9. **Append the precondition slots.**
10. **Active** means the current time is inside one of the plan's slots. The plan's total cost comes from the prices.

#### Failure behaviour
Missing rates or too little coverage fall back to the simple time-only plan, so charging still finishes. An unmeetable deadline becomes immediate continuous charging.

#### Questions for our code
We plan an EV signal and a cheap window, not to a departure. Which of these edge cases do we have: not enough time, rates ending before the target, partial slot trimming, a precondition? The same design could serve the immersion's ready-by times (up to four).


---

