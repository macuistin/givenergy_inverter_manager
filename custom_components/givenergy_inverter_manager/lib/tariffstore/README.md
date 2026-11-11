# tariffstore

The client for the open tariff store: find a country, a provider and a tariff, fetch the revision
in force on a day, check it against its checksum, keep it in a local cache and build the
definition that `lib/tariff` prices. It also validates a custom tariff a user types in.

This folder is a copy. It is written and tested in `macuistin/utility-tariffs`, folder
`lib/tariffstore`. `UPSTREAM.json` records the commit it was copied from and a SHA-256 of each
file, and `tests/lib/tariffstore/test_upstream.py` fails when a file here no longer matches.

- Never edit a file here. Change it in the store's repository. The Copy tariffstore workflow
  copies the folder and its tests each week and opens a pull request. To copy by hand, run
  `python scripts/copy_tariffstore.py <path to a checkout>`, which also rewrites `UPSTREAM.json`.
- The store's lint holds the code to this repository's limits, so the copy passes here unchanged.

## Public names

`Store`, `StoreError`, `FolderCache`, `MemoryCache`, `folder_reader`, `url_reader`,
`compile_area`, `CompileError`, `validate_tariff`, `validate_country`, `checksum`.

`Store.definition(...)` and `Store.custom_definition(...)` return the document that
`lib.tariff.load_definition` reads. The two packages do not import each other. The caller hands
the document from one to the other.

## Blocking calls

`url_reader` and `FolderCache` read the network and the disk. Inside Home Assistant, call a
`Store` from an executor job, never from the event loop.

## Allowed dependencies

The standard library only.
