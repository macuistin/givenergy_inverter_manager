# Release 0.19: notes for the agent that builds it

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

## Part 0: Instructions

### 0.1 What is in this file

| Part | What it is | How to read it |
|---|---|---|
| Part 0 | These instructions | Read now |
| Part A | The release brief for v0.19.0: goals, decisions, guardrails, cards, order, tests, rules, configuration matrix, roadmap text | **Read all of it before writing code** |
| Part B | Design pack: flows, pseudocode, vectors and open questions for every roadmap feature. **Not built in this release.** Section 1.5 is the detailed design behind the system-type cards | Read sections 0 and 1.5 now; read a feature's section only when you work on it |
| Part C | The specification method, SPEC-001 and the specifications extracted from other projects | Read section 1 now; read a specification only when a card or section names it |
| Part D | Gap analysis with links to other projects | Reference only |

**Current as of 11 October 2026, including GivTCP 3.6, 3.6.1 and 3.6.2** (released the same day) (Part A Appendix D.7 lists what changed and which unknowns it settled).

Inside Part A, "section N" and "Appendix X" mean Part A's. Inside Part B, "section N" means Part B's. "The brief" means Part A. "The design pack" means Part B.

### 0.2 Your three jobs

1. **Build release v0.19.0** by the cards in Part A, in the order in Part A section 11, one pull request per card.
2. **Put the roadmap features on `ROADMAP.md`** with context, evidence and links (card RM1; the exact text is Part A Appendix F). Write Part B to `docs/design/FEATURE_DESIGNS.md` and Part C's specifications to `docs/design/specs/` when cards SP0 and RM1 say so.
3. **Learn from other projects by specification only** (Part C section 1): read, write a specification in our own words, build from the specification, copy nothing.

Do **not** build any Part B feature unless the maintainer names it. Do not start anything listed as out of scope in Part A section 1.

### 0.3 First run: do these in order, without asking anything in between

1. The plan is already saved in `docs/design/` (this file, `RELEASE_0.19_BRIEF.md`, `FEATURE_DESIGNS.md`, `GAP_ANALYSIS.md` and `specs/`), on the branch `r019/design-docs`.
2. Read `CLAUDE.md` (`AGENTS.md` is a symlink) and every file in `.claude/rules/`. Where this document and a rule file disagree, the rule file wins, except where Part A section 15 says this release changes the rule.
3. Read Part A in full, Part B sections 0 and 1.5, Part C section 1.
4. Read the repository code that the cards touch.
5. **Send one message, with no code**, that contains:
   - every disagreement between this document and the code or rules;
   - every assumption you cannot verify;
   - **one consolidated list of what you need from the maintainer** (Part A section 12 and Appendix C, merged, each item saying which card it unblocks and what exactly to supply, such as "an anonymised entity list from a three-phase system");
   - the cards you will start now, and the cards that are blocked and why.
6. **Do not wait for a reply. Continue** with the cards that are not blocked (section 0.4). Hold only the cards that the disagreements affect.

### 0.4 Which cards can start now

| Cards | Start now? | Waiting for |
|---|---|---|
| SP0 (the specification method), IB1 to IB5 (mechanical move, no behaviour change), IB6, IB7, RA1 | Yes | nothing |
| SP1 (compare the charge simulation with SPEC-001; no behaviour change) | Yes, after IB1 to IB5 | nothing |
| WS1, WS3 (retry a missed write; log reasons) | Yes, after IB1 to IB5 | nothing |
| SR1 to SR3 (seasonal rules) | Yes, after IB1 to IB5 | nothing |
| HK1, HK2, HK4, RM1 | Yes | nothing |
| SP2 (write more specifications) | Yes, in the background of the others | nothing |
| RA2, RA3 (rate defaults) | **Yes.** Skip GivTCP's shipped defaults 0.395, 0.155, 0.04 (U6 answered) | nothing |
| CC1 to CC3 (competing-controller warning) | **Yes.** SmartTarget is not an entity (U1 answered), so build CC2 on behaviour; CC1 is a confirmation only | nothing |
| WS2 (re-plan) | No | whether a changed target applies in an open window (U2) |
| FS1 to FS3 (forecast shape) | No for FS1 | real Solcast and Forecast.Solar data (U3) |
| SY0 to SY3 (system types) | No | fixtures (U5) |
| SY4 (survive a GivTCP upgrade): the counter guard | **Yes**, after IB5 | nothing |
| GE0 to GE3 (GivEnergy EV charger) | **Yes**, against the entity names GivTCP 3.6 documents, with fakes labelled as such | a real fixture later, for exact state strings (U4) |
| HK3 (browser checks) | No | the maintainer runs them (U7) |
| RN1, RN2 (changelog, release) | Last | everything else |

When a card is blocked, say exactly what is missing, keep going with another card, and come back when the maintainer supplies it.

### 0.5 How to work

- **One card, one pull request**, on a branch `r019/<topic>`, stacked as `.claude/rules/docs-and-style.md` describes. Push the branch and open the PR with `gh` if it is authenticated; if not, write the PR body to `docs/design/pr-notes/<branch>.md` and say so.
- **Before every push** run the three commands in `CLAUDE.md`. State in the PR which you ran, which you could not, and which golden files moved and why.
- **Keep `docs/design/PROGRESS.md` current**: one line per card (not started, in progress, PR number, merged, blocked and why). It is your memory between sessions.
- **Resuming in a new session:** read Part 0 and `docs/design/PROGRESS.md`, then continue. Do not re-read all of Part A unless a card needs it.
- **Evidence, not guesses.** Where a card says "verify", produce a fixture, a test or a note in `docs/design/spikes/` first. If you cannot, stop that card and say what is missing.
- **If the code disagrees with a card, stop that card and say so.** Do not adapt the card silently.
- **Never test against the production Home Assistant, inverter, immersion or charger.** Use the end-to-end harness or the disposable test instance only.
- **Never weaken, delete or skip a test to get green.** A golden file is a check, not a record. It moves only in a behaviour card, on purpose, through `/regenerate-goldens`.
- **Rules change with the code.** Any sentence in `CLAUDE.md`, a rule file or a skill that a card makes untrue is fixed in the same PR (Part A section 15, cards RU1 to RU4).
- **No code from other projects, ever.** If you read another project's source, write behaviour into a specification (Part C), close the source, and build from the specification.

### 0.6 What the maintainer does

Nothing except answer the consolidated list from step 5, supply the fixtures it names, run the browser checks, and review pull requests. Everything else is yours.

### 0.7 Where the facts are

| Looking for | Go to |
|---|---|
| Goal, scope, decisions already made | Part A sections 1 and 2 |
| What is verified and what is not | Part A section 3 |
| Guardrails | Part A section 4 |
| The inverter backend interface | Part A section 5 |
| A card's work and tests | Part A sections 6 to 10 |
| Order and blocks | Part A section 11 and Part 0.4 |
| Definition of done, risks, rule changes | Part A sections 13 to 15 |
| Configuration test matrix for GivTCP | Part A Appendix D |
| Roadmap text and links to add | Part A Appendix F |
| Detection and management in full | Part B section 1.5 |
| Any roadmap feature's design | Part B, by the index in Part B section 0.5 |
| How to learn from another project | Part C section 1 |
| Behaviour extracted from other projects | Part C, SPEC-001 to SPEC-009 |

### 0.8 Where each part is

The plan was one file with line numbers. It is now split by part. The table at the top of this page names each file.
