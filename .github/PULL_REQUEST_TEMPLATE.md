## Summary

<!-- What does this change and why? Link related issues or discussions. -->

## Changes

<!-- The notable changes, one bullet each. -->

-

## Testing

<!-- What you ran, what the new tests cover, and anything to check after deploying. -->

- [ ] `ruff check custom_components tests` is clean
- [ ] `python -m pytest tests -q` passes
- [ ] `python -m pytest tests/ha_e2e -q` passes (needs `requirements-test-e2e.txt`, see `docs/testing.md`)

## Impact

<!-- Compatibility with existing installs, config or stored-data changes, entity or state class changes, and how to roll back. Write "None" if there is none. -->

## Checklist

- [ ] The title follows Conventional Commits (for example `fix(sensor): ...`)
- [ ] Bug fixes have a test that fails without the fix
- [ ] Docs are updated (`docs/`, `strings.json` and `translations/en.json` stay identical)
- [ ] No new config options or constants, or they are listed above and justified
