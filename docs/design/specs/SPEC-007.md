# SPEC-007: allocating surplus solar to appliances

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


**Source:** PV Excess Control, `optimizer.py` (the optimise routine, standard allocation, shedding and battery discharge protection), read October 2026. **Feeds:** C18, C19, C20, S12. **Nothing here is code.**

#### What it does
Each cycle it decides which appliances to switch on, off or set to a current, from the solar surplus, in priority order, with safeguards.

#### Phases
1. **Assess.** Compute the **average** surplus over a recent window of samples, ignoring unavailable and non-finite samples. **If fewer than a minimum number of good samples exist, the surplus is untrusted.** Skip allocation and run only the safety rules and battery protection. Appliances may have their own shorter averaging window; if that window has too few good samples the main average is used.
2. **Allocate.** Sort appliances by (helpers last, priority number, id) so ties are stable. Keep **two budgets starting from different numbers**: the averaged surplus (used to decide to turn something on, a conservative gate) and the instantaneous surplus (used to decide to shed, because it is physical reality). Each allocation reduces both by the same amount.
3. **Preempt** (optional). Shed a lower-priority running appliance so a higher-priority idle one can start.
4. **Shed.** If the instantaneous budget is below an off threshold (about minus 50 W), reduce or turn off appliances from the lowest priority upwards until it recovers.
5. **Battery discharge protection**, three independent rules in order.

#### Turning a plain on/off appliance on
- It is considered only if currently off.
- Threshold is the appliance's rated power plus an on-buffer (a default exists). If an off-threshold is configured above zero, the threshold is at least rated power plus the off-threshold, so it does not start only to be shed at once.
- If the averaged budget meets the threshold plus the power of any dependency that must start first, start it. A dependency is started in the same cycle and its power is added to the amount consumed.
- An optional **solar start delay** holds the start until the surplus has persisted.
- **Plan influence** can lower the threshold: "light" uses rated power with no buffer when the plan says on; "follow the plan" uses a tenth of rated power, with a floor of 50 W.
- **Deadline must-run.** If the appliance has a deadline and runtime still owed, and the time until the deadline is no more than 1.1 times the runtime owed, start it regardless of surplus and exempt it from cooldown and shedding.
- Otherwise stay idle and say why ("insufficient surplus, X needed").

#### Shedding rules
Never shed: on-only appliances, manually overridden ones, ones running from grid supplement, deadline-forced ones, or a dependency while any dependent is running. Lower current before turning off. **Shed first the lowest priority, and among equals prefer one that has already met its minimum daily runtime.**

#### Battery discharge protection
1. **State of charge below a minimum:** shed everything that may be shed (big consumers first), and block battery discharge.
2. **Grid import mode** (cheap tariff, force charge or automatic grid charge): block discharge and do **not** shed, because loads should run on cheap grid.
3. **A large consumer is running:** limit battery discharge to the lowest limit set among running large consumers. The most restrictive rule wins.

#### Quirks
Grid-supplemented appliances are counted separately so they do not deplete the solar budget. Dependency decisions are injected afterwards by replacing idle entries.

#### Questions for our code
Our immersion and EV rules are separate. Do we use an averaged surplus for turn-on and an instantaneous one for turn-off? A minimum count of good samples? An off threshold so we do not start and stop? Priority and shedding between EV, immersion and battery (C19)? We exclude discharge limiting by rule (it writes a discharge setting).


---

