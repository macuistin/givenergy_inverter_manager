# Specifications extracted from other projects

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

**Purpose:** learn what other projects do, write it down as a specification in our own words, then build our own version from the specification. This file holds the method, the first specification (PALM's overnight target), and the backlog of specifications still to write.
**Status:** SPEC-001 below and SPEC-003 to SPEC-009 in Part C were extracted from the other projects' source and documentation in October 2026. Nothing was run. The reference models that produced the test vectors were written from the specification text, not from the other projects' code.

---

### 1. Method: read, specify, build

**Why this method.** Copyright protects the way code is written, not the idea or the method behind it. A behaviour, a formula, a threshold, a sequence of steps or an entity name is a fact that can be learned and reimplemented. Copied code, comments, names, structure and layout are not.

**Three roles, which can be three sessions.**
1. **Reader.** Reads the other project's documentation and code and writes a specification. The specification states behaviour, not code.
2. **Builder.** Implements from the specification only, with the other project's source closed. If the specification is unclear, the builder asks the reader to fix the specification, not to paste code.
3. **Checker.** Writes tests from the specification's test vectors and from our own behaviour. Compares our output with the vectors and reports differences. A difference is a question for the maintainer, not an automatic fix.

**A specification contains:**
- **Purpose and source.** What it does, which project and file it came from, the commit or version read, the date.
- **Inputs and outputs**, with units and ranges.
- **Behaviour in steps**, with every formula written in words and symbols, and every constant with its default and what it is for.
- **Failure behaviour.** What it does when data is missing or invalid.
- **Quirks and probable defects.** Things the source does that look unintended. We decide whether to copy the behaviour, and say so.
- **Test vectors.** Inputs and expected outputs, small enough to check by hand.
- **Questions for our code.** Where we may differ, phrased as questions.

**A specification must not contain:** source code or pseudo-code that follows the source line by line, comments copied from the source, the source's variable, function or class names (apart from public interface names such as entity ids and setting names, which are facts), or its file structure.

**Cloned source** lives outside the repository and is never committed.

**Provenance.** Each specification lists what was read and when. Each test vector says whether it came from the specification's reference model or from a real run.

---

The status of every specification, the backlog and the rule for new ones are in [STATUS.md](STATUS.md). The files are:

- [SPEC-001: PALM overnight charge target](SPEC-001.md)
- [SPEC-003: load history, weighting and away mode](SPEC-003.md)
- [SPEC-004: a solar diverter inside the charge plan](SPEC-004.md)
- [SPEC-005: hardware detection, caching and model gating](SPEC-005.md)
- [SPEC-006: cheapest-window selection](SPEC-006.md)
- [SPEC-007: allocating surplus solar to appliances](SPEC-007.md)
- [SPEC-008: a departure-time charging plan](SPEC-008.md)
- [SPEC-009: correcting a solar forecast by matching similar past conditions](SPEC-009.md)
- [NOTES.md](NOTES.md): approach notes from other projects
- [REFERENCE_MODELS.md](REFERENCE_MODELS.md): our own reference models that produced the test vectors
