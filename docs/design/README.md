# Design notes

Notes that record decisions and the evidence behind them. They move with the code: a pull request that changes a decision updates the note.

## Release 0.19 (planned)

- [RELEASE_0.19_PLAN.md](RELEASE_0.19_PLAN.md): the plan as it stands against the code, what is blocked, and what the maintainer has to supply.
- [RELEASE_0.19_BRIEF.md](RELEASE_0.19_BRIEF.md): the release brief. Goal, decisions, guardrails, the inverter backend, every card with its tests, the order of work and the configuration test matrix.
- [RELEASE_0.19_AGENT_NOTES.md](RELEASE_0.19_AGENT_NOTES.md): how the work is run, one card to one pull request.
- [FEATURE_DESIGNS.md](FEATURE_DESIGNS.md): a design for each roadmap feature (flows, pseudocode, vectors, open questions). None of these is built in 0.19 unless named.
- [specs/](specs/README.md): the specification method and the specifications extracted from other projects. Other projects are studied and never copied.
- [GAP_ANALYSIS.md](GAP_ANALYSIS.md): what other GivEnergy systems do that this integration does not.

## Release 0.18

- [PROGRESS.md](PROGRESS.md): one line per card, and the open questions.
- Spikes, each with question, method, result, evidence and the decision it supports:
  - [SP1: creating a persistent dashboard](spikes/SP1.md)
  - [SP2: the server-side admin check and what needs a browser](spikes/SP2.md)
  - [SP3: the wizard pattern](spikes/SP3.md)
- [CONFIG_DIET.md](CONFIG_DIET.md): every option the wizards still ask for, and whether to detect it, make it an entity, make it a fixed assumption or keep it.
- [mock_givtcp.md](mock_givtcp.md): the fake GivTCP used by the write-sequence test.

The spike tests are in `tests/ha_e2e/spikes/` and run with the real Home Assistant suite (`python -m pytest tests/ha_e2e -q`, see [testing](../testing.md)).
