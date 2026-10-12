# SPEC-005: hardware detection, caching and model gating

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


**Source:** `givenergy-modbus` (`model/plant.py`, `model/inverter.py`, `docs/hardware-firmware-quirks.md`, `docs/register-identification.md`) and the givenergy-hass README, read October 2026. **Feeds:** SY1, SY2, C29. **Nothing here is code.** Those projects read the inverter's registers; we read GivTCP's entities. The method carries over, the addresses do not.

#### What it does
It decides what kind of plant it is talking to and which parts exist, once, then caches the answer.

#### Behaviour
1. **Identity read.** The plant's main device holds a device type code. Without it detection fails loudly.
2. **Family from the first digit:** 2 single-phase hybrid, 3 AC-coupled, 4 three-phase hybrid, 5 EMS controller, 6 three-phase AC-coupled, 7 Gateway, 8 All-In-One. Two-digit prefixes name variants: 21 Polar, 41 commercial All-In-One, 51 commercial EMS, 81 high-voltage Gen 3 hybrid, 82 All-In-One hybrid, 83 Gen 4 hybrid.
3. **Generation within family 2** comes from the main firmware version (Gen 1, 2 and 3 are told apart this way). **Firmware numbers are not comparable across families.** A larger number is not "newer".
4. **Nominal battery voltage** follows the family: All-In-One 307 V, three-phase hybrids 76.8 V, others 51.2 V.
5. **Peripherals are probed, then validated.** Meters, low-voltage batteries and their controller, high-voltage control units and modules are each looked for at fixed addresses. **A peripheral that responds but is all zeros is a ghost slot and is dropped.** Low-voltage battery probing is skipped for high-voltage and EMS plants.
6. **High-voltage topology.** The count of control units comes from one register, each unit reports its module count, and module addresses follow from that.
7. **Caching and re-detection.** The result is cached. A later pass can be "hinted": only previously seen addresses are rechecked. A manual action forces a full sweep (used after adding or removing a battery).
8. **Gating.** Entities are created per model. Examples: a house-consumption-today figure is suppressed on All-In-One and EMS plants; on a Gateway the inverter-shaped sensors are suppressed (they read zero) and the whole-house figures sit on the Gateway device; solar-derived figures are absent on AC-coupled and All-In-One models.
9. **Support statement.** The project publishes a table of what is validated against captures from real hardware and what is only modelled.

#### Quirks the project documents (use as test ideas)
- The same register addresses mean different things on different firmware lineages. Routing must be keyed to the resolved model, never inferred from live values.
- Registers added in a later protocol revision read zero on older firmware. **Zero does not mean absent, and absent does not mean zero.**
- A writable baseline register looks like a live counter.
- A documented unit can contradict its own description, and units were corrected between revisions. Treat a unit as a strong hint, not proof.
- GivEnergy is no longer trading, so the protocol document is the last word and will not be reissued.

#### Questions for our code
We classify nothing today. Which GivTCP value plays the part of the device type code (`Invertor_Type`, U10)? Do we treat an all-zero module or a zero energy counter as present? Do we create or hide entities by system type? Do we offer a way to re-detect?


---

