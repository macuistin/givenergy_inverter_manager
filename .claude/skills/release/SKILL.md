---
name: release
description: "Prepare a GivEnergy Inverter Manager release: rename the changelog section, bump the six version places, check, and open the release PR. Use when asked to cut or prepare a release."
disable-model-invocation: true
---

# Release

A release is a `chore/release-<version>` branch and PR whose only changes are the changelog heading
and the six version strings. Commit title: `chore(release): bump version to X.Y.Z`. Past examples:
`git show 98d2e24`, `git show 921d400`.

1. Decide the version. A user-visible feature or a stored data change is a minor bump (0.18.2 to
   0.19.0). A fix only is a patch bump.
2. Start from the tip of the branch that holds the changes. Merge `main` in if it moved. Do not
   rebase.
3. In `CHANGELOG.md`, rename `## Unreleased` to `## vX.Y.Z`. Under the heading add one or two plain
   sentences that say what the release does and what to do on upgrade (for example check a setting
   that now has a new default). Keep the existing groups (`**Removed**`, `**Added**`, `**Changed**`, `**Fixes**`, `**Upgrading**`).
4. Run `python scripts/set_version.py X.Y.Z`, which writes the six places below. Check its diff:
   - `custom_components/givenergy_inverter_manager/const.py`, `INTEGRATION_VERSION`
   - `custom_components/givenergy_inverter_manager/manifest.json`, `version`
   - `pyproject.toml`, `version`
   - `README.md`, the `Current version:` line
   - `docs/index.md`, the `This documentation matches version` line
   - `REQUIREMENTS.md`, the `The current release is` line
   Then `grep -rn "<old version>" .` and confirm only history (changelog, design notes) is left.
5. Run `python scripts/set_version.py --check vX.Y.Z` and `python -m pytest tests/test_metadata.py -q`.
   Both fail if one of the six places disagrees.
6. Run `ruff check custom_components tests scripts packages`, the unit suite and the end-to-end suite.
7. Commit, then open the PR with `.github/PULL_REQUEST_TEMPLATE.md`. The PR body says what the
   release contains, taken from the changelog.
8. After the PR merges, the maintainer runs Actions > Release > Run workflow on `main` with
   `X.Y.Z`, or pushes the tag `vX.Y.Z`. `.github/workflows/release.yml` checks the six places,
   tags the commit and publishes the GitHub release with the changelog section as notes. HACS lists
   GitHub releases as versions. A beta (`X.Y.ZbN`) needs no changelog section of its own: it
   uses `## Unreleased`, and the workflow can run from any branch for it. Do not run the workflow,
   create the tag or the release unless asked.
9. Do not touch a live Home Assistant to install the release unless the maintainer asks.
