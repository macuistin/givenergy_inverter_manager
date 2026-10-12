# SPEC-006: cheapest-window selection

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


**Source:** the separate Target Timeframes integration (`entities/__init__.py`), which took over the target-rate feature from the Octopus Energy integration, read October 2026. **Feeds:** C34, N13, the immersion ready-by plan. **Nothing here is code.**

#### What it does
From a list of half-hour periods with a value each (a price, a carbon figure, a solar forecast), it picks the best periods for a job needing a given number of hours.

#### Inputs
Time-ordered half-hour periods with a value; hours needed (any number, rounded up to whole half hours); a mode of exact, minimum or maximum; a flag to search for the highest instead of the lowest; a flag to prefer the latest of equal choices; an optional minimum and maximum value; an optional weighting.

#### Continuous mode (one block)
1. Slots needed is the hours times two, rounded up.
2. For each starting period that passes the value limits, extend forward one period at a time until the needed count is reached. **Stop extending at the first period outside the limits or at the end of the data.**
3. A block qualifies if its length equals the needed count (exact), or is at least the needed count and no shorter than the best so far (minimum), or is at most the needed count and no shorter than the best so far (maximum).
4. A qualifying block is scored as the sum of its values, each multiplied by its weight when a weighting is given.
5. Keep the lowest score (or the highest when searching for the highest). **On a tie keep the earlier block, or the later one when "latest" is chosen** (strict versus non-strict comparison).
6. Return the block in time order, or nothing.

#### Intermittent mode (separate periods)
1. Sort the periods by value (descending when searching for the highest), breaking ties by earliest end, or by latest end when "latest" is chosen.
2. Drop periods outside the value limits.
3. Exact: if at least the needed count remain, take the first needed count, else nothing. Maximum: take up to the needed count. Minimum: if at least the needed count remain, return all of them.
4. Return the chosen periods in time order.

#### Weighting
A comma-separated list of numbers, one per slot of the block, where a single star stands for "all remaining slots at weight 1". If there are more weights than slots, no weighting applies. An invalid string is an error.

#### Evaluation
Windows may be fixed (a start and end time) or rolling. The module has evaluation modes and a check for whether a period's selection is already complete. **That logic was not read**, so it is not specified here.

#### Test vectors
Reference model from the text, not a run. Twelve half-hour values from 00:00: 30, 28, 12, 10, 9, 9, 11, 25, 30, 31, 12, 10.
- Continuous, 2 hours (4 slots): best block is slots 3 to 6 (10, 9, 9, 11), total 39. The block 2 to 5 totals 40.
- Continuous, 1 hour, latest: slots 4 and 5 (9, 9), total 18, which is the only block of that total.
- Continuous, 2 hours, maximum value 11: unchanged, slots 3 to 6.
- Intermittent, 2 hours: slots 3, 4, 5 and 11 (10, 9, 9, 10). The two 10s tie and both are taken because four are needed.
- Intermittent, 3 hours, maximum value 10, exact: only four periods qualify and six are needed, so **nothing**.

#### Questions for our code
Our immersion ready-by plan and the charge window choose cheapest periods. Which rule do they use on a tie? Do they honour a maximum price? Do they return nothing, or a smaller set, when the target cannot be met? (evcc's planner, SPEC-008, falls back to charging at once.)


---

