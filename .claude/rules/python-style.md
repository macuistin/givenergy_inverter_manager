---
description: "Clean Code limits that ruff enforces, and the habits that go with them"
paths:
  - "custom_components/**/*.py"
  - "tests/**/*.py"
  - "scripts/**/*.py"
  - "tools/**/*.py"
---

# Python style

Ruff enforces the measurable part in `pyproject.toml`: line length 100, complexity 8, 30 statements,
10 branches, 4 arguments, no boolean flag arguments. New code stays inside the limits. An existing
offender carries an inline `# noqa: <rule>`, and the change that fixes the function deletes it.

- A function does one thing at one level. Aim for 20 lines, never over 40.
- Name for meaning (`available_surplus_w`, not `calc2`).
- More than three arguments becomes a frozen dataclass. A boolean flag argument means two functions
  or an enum.
- A function either changes state or returns a value.
- Raise an exception rather than return an error code. Do not pass or return `None` where an empty
  value works.
- Do not copy a block a second time. Extract it.
- Catch specific exceptions. A `try` wraps the one call that raises. A broad `except Exception`
  is only for an integration boundary, and it logs why.
- Refactor in small steps with the tests green. For code without tests, write a characterisation
  test that pins today's behaviour first.
- Schemas and entity description tables are declarative on purpose and may stay long. Keep logic out
  of them.
- Where a validator already guarantees a key (a service schema, a form), index it directly
  (`data["key"]`) so a broken contract fails loudly. Do not add `.get` and silent defaults.
- Do not log secrets or tokens.
