# Design notes

Notes that record decisions and the evidence behind them. They move with the code: a pull request that changes a decision updates the note.

## Release 0.19 (planned)

The work is tracked in GitHub issues, starting at #304. Each pull request group is a child, and each card is a grandchild with its full text. The specifications from other projects are under #366.

- [RELEASE_0.19_PLAN.md](RELEASE_0.19_PLAN.md): the plan as it stands against the code, what is blocked, and what the maintainer has to supply.
- [FEATURE_DESIGNS.md](FEATURE_DESIGNS.md): a design for each roadmap feature (flows, pseudocode, vectors, open questions). None is built in 0.19 unless named.
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
