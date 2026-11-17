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

## The tariff library is installed, not copied

The tariff model, bill maths, time helpers, store client and plan ranking are written and tested in
`macuistin/utility-tariffs`. Home Assistant installs them as the package `utility-tariffs-lib`,
imported as `utility_tariffs_lib.tariff`, `.timeutil`, `.tariffstore` and `.tariffranking`.

- Never patch it here. Change it in the store's repository, tag it, then move the pin.
- The pin is the one `requirements` line in `manifest.json`. `requirements-test.txt`,
  `requirements-test-e2e.txt` and `tests/ha_e2e/requirements-floor.txt` carry the same line, and
  `tests/test_library_pin.py` fails when they differ.
- A package here may import `utility_tariffs_lib` besides the standard library.
- Code that reads this integration's option keys stays outside it, in `core/tariff.py` and
  `core/tariff_config.py`. A test that needs `core/` lives under `tests/core/`.

## Packages

| Package | Purpose | Allowed `lib/` dependencies |
| --- | --- | --- |
| `ev` | Multi-brand EV charger model, discovery, sessions and the base-rate alert | `guards` |
| `heating` | Hot-water heating planner: ready-by plans, the cheapest window, the learned heating rate | none |
| `guards` | Screening of inverter energy counters, and the list of settings the inverter did not take | none |
| `solar` | Solar forecast shape, the settled solar day and rebuilding forecast accuracy from history | none |
| `givtcp` | GivTCP client: discovery, reads, verified writes and write order, plus its value types and system model | none |
