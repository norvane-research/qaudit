# Contributing to qaudit

*En bref : les issues sont bienvenues ; les pull requests externes ne sont pas
acceptées tant qu'un accord de contribution (CLA) n'est pas en place.*

## Issues are welcome

- **Bugs**: attach the smallest trade file that reproduces the problem (remove
  names and account numbers first), the exact command, the exit code and the
  `qaudit --version` output. A wrong verdict on a file you can share is the
  most useful report there is.
- **Unsupported export formats**: attach an anonymised sample; the E1 output
  (`qaudit mapping-skeleton file`) helps.
- **Method questions**: thresholds live in `qaudit/io/methods/method-1.0.toml`
  and are published in `docs/method-1.0.en.md`. Proposals to change a
  threshold must argue why, since any change bumps the method version and
  invalidates earlier reports.

Never post a real account statement with personal data in a public issue.

## Pull requests

qaudit is distributed under the AGPL-3.0-or-later **and** under a commercial
licence. Offering both requires the maintainer to hold the rights to every line
of code. Until a contributor licence agreement (CLA) is in place, **external
pull requests cannot be merged**; please open an issue describing the change
instead.

## Working on your own fork

The AGPL lets you modify qaudit freely. Before proposing anything, keep the
project's rules green:

```bash
pip install -e ".[dev]"
pytest
mypy --strict
ruff check .
```

Architecture rules are enforced by `tests/test_architecture.py`: the core
(`qaudit/core/`) does no I/O, receives its randomness as a
`numpy.random.Generator`, and contains no user-facing strings. If the healthy
witness fixture comes out NO-GO, the engine is broken.

If you run a modified version as a network service, the AGPL requires you to
offer its source code to its users.
