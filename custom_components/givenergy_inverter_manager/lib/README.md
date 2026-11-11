# lib/

Packages written as if each were already its own distribution, so a later move into a separate
repository is a plain `git mv`. They live here because HACS ships only
`custom_components/givenergy_inverter_manager/`. Code the integration imports at run time must sit
inside that folder until it is published somewhere installable.

## Rules for every package

- It imports only the standard library, itself and the `lib/` packages named for it in the
  `ALLOWED` table in `tests/test_metadata.py`.
- It never imports the integration's `const` or `logging` modules, `core/`, `discovery/`,
  `inverter/` or `homeassistant`, not even under `TYPE_CHECKING`. The standard library `logging`
  is fine.
- Tuning constants it needs live in its own `defaults.py`. `const.py` re-imports them, so the
  dependency points from the integration into `lib/`.
- Its `__init__.py` re-exports the public names and does no work at import time.
- It has a short `README.md` with its purpose, public names and allowed dependencies.
- Its tests live in `tests/lib/<name>/`.
- The old path is a thin re-export until the shims are removed.

## Copied packages

`tariff`, `timeutil` and `tariffstore` are copies. The tariff store, `macuistin/utility-tariffs`,
is the source of truth for all tariff and billing code and calculations, and they are written
and tested there.

- Never edit a file in those three folders, or a test under `tests/lib/` that starts with the
  `Copied from the tariff store` line. Change it in the store's repository.
- The Copy tariffstore workflow copies the folders and their tests each week and opens a pull
  request. To copy by hand, run `python scripts/copy_tariffstore.py <path to a checkout>`.
- Each folder's `UPSTREAM.json` records the commit copied and a SHA-256 of each file.
  `tests/lib/test_upstream.py` fails when a file no longer matches.
- A release is refused while a copy is behind the store (`--check` in the release workflow).
- Code that reads this integration's option keys stays outside them, in `core/tariff.py` and
  `core/tariff_config.py`. A test that needs `core/` lives under `tests/core/`.

## Packages

| Package | Purpose | Allowed `lib/` dependencies |
| --- | --- | --- |
| `timeutil` | Elapsed-time maths that stays correct across a clock change. A copy | none |
| `ev` | Multi-brand EV charger model, discovery, sessions and the base-rate alert | `timeutil`, `guards` |
| `tariff` | Tariff model, energy and cost accumulation, bill maths, stored-energy value. A copy | `timeutil` |
| `heating` | Hot-water heating planner: ready-by plans, the cheapest window, the learned heating rate | `timeutil`, `tariff` |
| `guards` | Screening of inverter energy counters, and the list of settings the inverter did not take | `timeutil`, `tariff` |
| `solar` | Solar forecast shape, the settled solar day and rebuilding forecast accuracy from history | `timeutil` |
| `tariffstore` | Client for the open tariff store: find, fetch, check, cache and compile a tariff. A copy | none |
| `givtcp` | GivTCP client: discovery, reads, verified writes and write order, plus its value types and system model | `timeutil` |
