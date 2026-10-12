# Design notes

Notes that last as long as the code they describe: the decisions behind it and the evidence for them. They move with the code, so a pull request that changes a decision updates the note.

Plans, designs for features that are not built yet, and specifications from other projects are GitHub issues, so they can be commented on and closed as they are done. They are not kept here. The planned work and its status are in [ROADMAP.md](../../ROADMAP.md), and each roadmap row links to its design issue.

- Spikes, each with question, method, result, evidence and the decision it supports:
  - [SP1: creating a persistent dashboard](spikes/SP1.md)
  - [SP2: the server-side admin check and what needs a browser](spikes/SP2.md)
  - [SP3: the wizard pattern](spikes/SP3.md)
  - [CC1: can the integration read whether SmartTarget is on?](spikes/CC1.md)
- [CONFIG_DIET.md](CONFIG_DIET.md): every option the wizards still ask for, and whether to detect it, make it an entity, make it a fixed assumption or keep it.
- [mock_givtcp.md](mock_givtcp.md): the fake GivTCP used by the write-sequence test.

The spike tests are in `tests/ha_e2e/spikes/` and run with the real Home Assistant suite (`python -m pytest tests/ha_e2e -q`, see [testing](../testing.md)).
