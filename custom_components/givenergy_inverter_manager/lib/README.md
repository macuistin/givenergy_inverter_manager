# lib/

Packages written as if each were already its own distribution, so a later move into a separate
repository is a plain `git mv`. They live here because HACS ships only
`custom_components/givenergy_inverter_manager/`. Code the integration imports at run time must sit
inside that folder until it is published somewhere installable.

## Rules for every package

- It imports only the standard library, itself and the `lib/` packages named for it in the
  `ALLOWED` table in `tests/test_metadata.py`.
- It never imports `const`, `logging`, `core/`, `discovery/`, `inverter/` or `homeassistant`, not
  even under `TYPE_CHECKING`.
- Tuning constants it needs live in its own `defaults.py`. `const.py` re-imports them, so the
  dependency points from the integration into `lib/`.
- Its `__init__.py` re-exports the public names and does no work at import time.
- It has a short `README.md` with its purpose, public names and allowed dependencies.
- Its tests live in `tests/lib/<name>/`.
- The old path is a thin re-export until the shims are removed.

## Packages

| Package | Purpose | Allowed `lib/` dependencies |
| --- | --- | --- |
| `timeutil` | Elapsed-time maths that stays correct across a clock change | none |
