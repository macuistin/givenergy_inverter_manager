---
description: "Writing style, generic docs, commits, pull requests, changelog and version bump"
---

# Docs, writing and workflow

## Writing

- UK English everywhere: code comments, docs, strings, commits (behaviour, colour, licence).
- Short sentences, action verbs, concrete names (files, fields, entities). A paragraph over three
  sentences is usually overwritten.
- No em dash to bolt on an afterthought. Use a comma or a full stop, or reword. Do not rewrite
  existing text just for this.
- A comment says why, never what the next line does. Delete commented-out code.
- Describe things in plain words. Roadmap ids (M3, C10) belong in `ROADMAP.md` and PR titles. In
  docs, the changelog and entity text, name the thing.

## Docs are generic

`docs/`, `README.md`, `ROADMAP.md`, `CHANGELOG.md` and every user-facing string are written for any
user with any supplier and tariff. They never mention:

- the maintainer, "the owner", one household's bill, or a one-off figure from one install
- personal device, room or people names, serial numbers, URLs or avatars (check screenshots too)

Describe a setting by its meaning, its unit and where to find it on a bill, with a labelled round
number example. Keep install-specific analysis in the PR discussion.

## Generated and checked docs

- `docs/sensors.md` is generated. After a sensor change run `python scripts/gen_sensor_docs.py`.
  `tests/test_docs_sensor_table.py` fails when it is stale.
- `tests/golden_dashboard_matrix.json` is a golden file. See `.claude/rules/dashboard.md`.
- `strings.json` and `translations/en.json` are byte identical. Edit `strings.json`, then copy it.
- Update the doc that describes the behaviour in the same change as the code.

## Commits and pull requests

- Conventional Commits for commit messages and PR titles: `fix(sensor): ...`, `feat(config): ...`.
- No `Co-Authored-By` line and no "Generated with" line in commits or PR bodies.
- PR body: `.github/PULL_REQUEST_TEMPLATE.md` (Summary, Changes, Testing, Impact, Checklist). This
  repo is personal, so there are no other sections. List what was not verified under Testing.
- Work is stacked: each PR is based on the branch below it, not on `main`. To take changes from a
  lower branch, merge it into yours. Merge commits, not squash, so a stack stays mergeable.
- Never rebase, amend or force-push a branch that has an open PR. Address review feedback with new
  commits on top, so reviewers see only what changed.
- When a lower PR merges, retarget the next one to `main` and merge `main` into it.
- CI runs on every PR whatever its base: lint, the unit and real Home Assistant suites on the
  2026.5.0 floor and on the latest release, Hassfest, HACS and CodeQL (`docs/testing.md`).

## Changelog and version

- `CHANGELOG.md` has `## Unreleased` at the top. A change a user can see or that changes stored
  data adds bullets there, in plain words: what changes, what the user sees, what to do on upgrade.
  Use the existing groups (`**Changes**`, `**Fixes**`, `**Upgrading**`).
- A removed or renamed attribute goes under `**Removed**` with what it showed, so a template that
  used it can be found.
- A change that makes a rule untrue changes the rule in the same PR.
- Changes with no user effect (tests, CI, contributor docs, these rules) get no entry.
- Releases are cut with `/release`. A version bump changes six places together: `const.py`
  (`INTEGRATION_VERSION`), `manifest.json`, `pyproject.toml`, `README.md` ("Current version:"),
  `docs/index.md` ("This documentation matches version") and `REQUIREMENTS.md` ("The current
  release is"). `python scripts/set_version.py X.Y.Z` writes all six and `--check` compares them.
  `tests/test_metadata.py` checks them too.
- `ROADMAP.md` holds planned work only. What shipped is in `CHANGELOG.md`.
