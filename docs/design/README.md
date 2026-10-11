# Design notes for 0.18.0

Notes that record decisions and the evidence behind them. They move with the code: a pull request that changes a decision updates the note.

- [PROGRESS.md](PROGRESS.md): one line per card, and the open questions.
- Spikes, each with question, method, result, evidence and the decision it supports:
  - [SP1: creating a persistent dashboard](spikes/SP1.md)
  - [SP2: the server-side admin check and what needs a browser](spikes/SP2.md)
  - [SP3: the wizard pattern](spikes/SP3.md)
- [mock_givtcp.md](mock_givtcp.md): the fake GivTCP used by the write-sequence test.

The spike tests are in `tests/ha_e2e/spikes/` and run with the real Home Assistant suite (`python -m pytest tests/ha_e2e -q`, see [testing](../testing.md)).
