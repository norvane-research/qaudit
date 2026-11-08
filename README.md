# qaudit — audit and validation of trading systems

*Version française : [README.fr.md](README.fr.md).*

`qaudit` reads a history of closed trades and returns a reasoned verdict —
**GO**, **CONDITIONAL GO** or **NO-GO** — with the numbers behind it and the
conditions for going live.

It asks the questions a backtest screenshot never answers: how many variants
were tried before this one? What is left once the best trades are removed?
Would a system with no edge at all have done as well?

**Deterministic core, smart shell.** The engine runs alone, offline, with no
language model: same inputs + same version + same seed = same JSON, byte for
byte. The verdict follows mechanically from explicit barriers (never from a
composite score); every point can be challenged on its own.

> qaudit states facts about a trade history. It is **not investment advice**,
> it predicts no performance and it recommends no settings.

**Selling an EA or signals?** The engine is free. When buyers need a result
they can check, Norvane Research re-runs the audit on your file and, on GO,
records a numbered attestation in a public registry:
[transferable attestation, 390 €](https://whop.com/lafabrique/qaudit-attestation),
due whatever the verdict · [check an attestation](https://norvane-research.pages.dev/en/verification.html)
· the pre-check of your file is free.

---

## What a report looks like

The bundled demo (`qaudit demo`) audits a synthetic martingale system. On the
surface it looks fine: +20.5 % over 15 months, 77.5 % winning trades, profit
factor 1.26, annualised Sharpe 1.52, maximum drawdown 9 %. Condensed from its
report:

```text
NO-GO                    method 1.0 · engine 1.0.0 · seed 0 · 600 trades, USD
data SHA-256             ae4badd1047e2753…83394ca19ef5

Blocking   martingale: after a loss, volume is multiplied by ≥ 1.5 in 96 % of
           cases (after a win: 1 %), over 135 post-loss trades
Major      no stop: 100 % of trades have no stop-loss

Barrier                               value   NO-GO if   indecision band
deflated Sharpe (10 variants)         0.54    < 0.50     0.45 – 0.55   borderline
profit factor, bootstrap 5th pct      1.03    < 1.00     0.95 – 1.05   borderline
drawdown percentile (permutations)    88.0    < 5        3 – 8
p-value against the no-edge null      0.048   ≥ 0.05     0.03 – 0.08   borderline
walk-forward efficiency               —       < 0.40     not evaluated (no walk-forward data)

This system stops being significant beyond 12 tested variants.
```

On statistics alone it would get a conditional GO at best; the position sizing
is what makes it a NO-GO. Full reports, HTML and PDF:
[martingale → NO-GO](https://norvane-research.pages.dev/en/exemples/martingale.html)
· [healthy witness → GO](https://norvane-research.pages.dev/en/exemples/temoin-sain.html).

---

## Quick start

```bash
python -m venv .venv
.venv/Scripts/activate          # Linux/macOS: source .venv/bin/activate
pip install -e .
qaudit demo --out demo-out      # two offline audits: healthy witness → GO, martingale → NO-GO
```

Runtime dependencies: `numpy`, `scipy`, `pandas` — nothing else. Once
installed, the package touches neither the network nor any API key.

## Audit a file

```bash
qaudit audit history.csv --initial-balance 10000 --out report/ --lang en
```

Formats read (detected automatically, can be forced with `--kind`):

- generic CSV, one row per trade;
- MetaTrader 5 CSV export and HTML account history;
- MetaTrader 5 **Strategy Tester** report, HTML or Open XML (closed trades are
  rebuilt from the deals);
- MetaTrader 4 detailed report;
- Deriv profit table.

MetaTrader headers are recognised in English, French, Spanish, German,
Portuguese and Italian. The engine validates the file — naming any faulty row
and column — computes everything the data allows and writes:

- `report/archive/<name>.json` — the full, versioned document, always archived
  (published schema: `qaudit/io/writers/schema/report-1.0.json`);
- `report/<name>.html`, `report/<name>.pdf` (and `<name>.json` depending on the
  profile) — the deliverables of the chosen report profile.

The exit code **is** the verdict: `0` GO · `1` conditional GO · `2` NO-GO.

> Command-line options and a few identifiers are French (`--offre` = report
> profile, `--holder` = attestation holder). Reports, the desktop app and the
> published method are available in English with `--lang en`.

Useful options:

| Option | Effect |
|---|---|
| `--prices ohlc.csv --symbol EURUSD` | price series: enables the look-ahead, execution-realism and stop-sensitivity detectors; ATR regimes |
| `--walkforward folder/` | one trade file per parameter set: evaluates the walk-forward barrier (without it the verdict is at best conditional) |
| `--ruleset two_step_static` or `--ruleset my_rules.toml` | prop-firm replay (`qaudit rulesets` lists the built-in rulebooks) |
| `--n-trials 50` | declared number of variants tried (the deflated Sharpe is always published on the 1…1000 grid) |
| `--seed 7` | simulation seed (printed in the report) |
| `--lang en` | report in English |
| `--offre verdict_propfirm` | report profile (`qaudit profils` lists them) |

### When the engine stops: three escalation gates

| Code | Situation | How to resume |
|---|---|---|
| **10** (E1) | a header is not recognised and cannot be inferred from the content; a JSON lists the columns seen and the missing fields | `qaudit mapping-skeleton file.csv > mapping.toml`, fill it in, rerun with `--mapping mapping.toml`. The validated mapping is remembered by header fingerprint: the next file in the same format goes through alone. |
| **11** (E2) | prop-firm rulebook in prose, missing or incomplete; the TOML skeleton is printed | fill in **every** key (a missing rule is written `0`, never guessed), `as_of` is mandatory, rerun with `--ruleset file.toml` |
| **E3** | a barrier quantity falls inside its indecision band | the verdict is returned normally, with `revue_humaine: true` and the borderline quantity printed |

Other codes: `20` invalid data (row and column named), `30` internal error
(traceback printed).

### Re-render without recomputing, batch mode

```bash
qaudit render --from report/archive/<name>.json --offre audit_prix --out other/
qaudit batch folder_of_csv/ --jobs 8 --initial-balance 10000 --offre portefeuille --out batch/
```

Rendering from the archive is byte-identical to a direct audit (tested). Batch
mode audits N systems in parallel with a Benjamini–Hochberg correction on the
portfolio p-values. Measured: 80 systems, full audit at 10,000 iterations, in
22 s on 8 cores.

## What the report contains

- **Header**: engine version, method version, seed, SHA-256 fingerprint of the
  data (the four reproducibility fields).
- **In plain words**: the explanation for the end client, with no auditor in
  the loop — what the verdict means and does not mean, the five tests
  rephrased as questions with the file's figure and the threshold, each serious
  finding explained, then what remains to be done. Every section also carries a
  "How to read this section" box. These texts are catalogue templates filled
  with the numbers of the archived document: nothing is computed or interpreted
  at render time.
- **Verdict and barriers**: deflated Sharpe, profit factor at the 5th
  percentile of a block bootstrap, drawdown percentile among order
  permutations, p-value against the no-edge null, walk-forward efficiency —
  each with its threshold and indecision band.
- **Findings**: validation (ruin, gaps…), structural detectors (martingale,
  grid, missing stops, profit concentration, equity linearity, win-rate/payoff
  asymmetry, single-period dependence, holding time) and, with prices,
  look-ahead, execution realism and stop sensitivity (±10/20/30 %). A detector
  that could not run says so.
- **Statistics**: PSR, DSR and its sensitivity to the number of trials, with
  the tipping point ("this system stops being significant beyond N variants").
- **Resampling**: stationary block bootstrap (Politis–Romano, automatic block
  length), order permutation, no-edge null that keeps the empirical
  distributions (it is not an efficient-market null, and the report says so).
- **Regimes**, quarters, walk-forward (named protocol), **prop-firm replay**
  (probability per phase, failure causes, ruin of the funded account, median
  payout, net expectancy).

One visual charter for HTML, PDF and the desktop window. The HTML report is
self-contained (inline CSS, no downloaded font or resource, printable); the PDF
is generated by hand with no dependency.

## Ingestion conventions

- Mandatory fields: open time, close time, profit. The others (volume,
  direction, symbol, prices, stop, ticket, commission, swap, currency) are
  optional; when missing, the analyses that need them are cleanly disabled.
- If `commission` and/or `swap` are given, `profit` is taken as gross and the
  net is `profit + commission + swap` (MetaTrader convention); otherwise
  `profit` is taken as net.
- Naive timestamps are read as they are (server time); an explicit offset is
  converted to UTC.
- Canonical order: ascending close time. Duplicates, closes before opens and
  mixed currencies are errors (code 20).
- Ruin: as soon as `initial balance + cumulative P&L` ≤ 0, a blocking finding;
  no ratio is computed on a negative base. Without `--initial-balance` (or a
  deposit read from an MT5 report), ruin and relative metrics cannot be
  evaluated and the report says so.
- Every decision quantity is computed on per-trade P&L in account currency:
  the verdict is exactly invariant to a rescaling of profits.

## Versioned method

Thresholds live in `qaudit/io/methods/method-1.0.toml`, never in the code.
Changing a threshold requires bumping `version`: the method version is printed
in every report and invalidates earlier reports. The published method
([docs/method-1.0.en.md](docs/method-1.0.en.md)) is generated from that file
by `qaudit methode`, and a test fails if they diverge.

| Barrier | NO-GO | Indecision band |
|---|---|---|
| blocking structural finding | ≥ 1 | — |
| deflated Sharpe | < 0.50 | 0.45 – 0.55 |
| profit factor, 5th percentile of the block bootstrap | < 1.00 | 0.95 – 1.05 |
| drawdown percentile among permutations | < 5 | 3 – 8 |
| p-value against the no-edge null | ≥ 0.05 | 0.03 – 0.08 |
| out-of-sample walk-forward efficiency | < 0.40 | 0.35 – 0.50 |
| cumulative major findings | — | ≥ 3 → conditional |

A barrier that cannot be evaluated (no walk-forward, null not computable) is
never deemed passed: it becomes a named condition.

## Report profiles

`qaudit profils` lists the seven built-in profiles (`qaudit/io/profils/*.toml`).
A profile chooses the sections and formats delivered; it never touches the
computation or the verdict, cannot remove the header, the verdict, critical
findings, scope and limits or the footer, and the full JSON is always archived.
No notion of profile exists under `qaudit/core/` (tested).

| Profile | Content |
|---|---|
| `pre_verification` | is the file usable? (`qaudit validate`, no verdict) |
| `verdict_propfirm` | verdict, key figures, prop-firm replay |
| `audit_complet` | the full report; attestation on GO |
| `audit_prix` | full report + price detectors + walk-forward |
| `attestation_cessible` | full report + attestation the holder may show to buyers of the system |
| `portefeuille` | several systems with the multiple-selection correction |
| `due_diligence` | everything, plus an investment-committee note |

## Attestations and the public registry

An **attestation** is issued only on a **GO** verdict. It states one thing: a
file identified by its SHA-256 fingerprint passed method version x.y on a given
date. It is recorded in a registry (`~/.qaudit/registre.jsonl`, or
`--registry`) under a reference `AUD-<year>-<NNN>`; the same fingerprint audited
with the same versions always gets the same reference, and a re-issue produces
the same bytes.

```bash
qaudit audit file.html --offre attestation_cessible --holder "Studio X" --issuer "Name"
qaudit attest --from qaudit-out/archive/file.json --offre audit_complet   # re-issue
qaudit verify AUD-2026-001                    # registry entry, code 20 if unknown
qaudit badge AUD-2026-001 --site https://example.org/en   # SVG badge + HTML/Markdown snippet kit
qaudit registre --html site/verification.html # public page: never the holder
```

Anyone can run the engine, reproduce any report and issue attestations into
their own registry, under their own name. The attestations listed on the
**maintainer's public registry** are issued only after the maintainer has
re-run the audit on the client's file: that is the paid service described
below.

## Desktop app

`qaudit gui` (or `qaudit-gui`) opens a tkinter window — no extra dependency.
First try: **Load example**, then **Run audit** → GO within seconds, **Open
HTML** shows the report. Same core, same reports as the command line (tested
byte for byte). The escalation gates are handled inside the window: E1 opens
the column-mapping editor, E2 offers to save the rulebook skeleton, E3 shows
"human review required".

Windows executables: `.\packaging\build.ps1` builds a self-contained
`dist\qaudit\` folder (≈ 140 MB). The binaries are **not signed**; Windows
Smart App Control may block them. Running from Python
(`pythonw -m qaudit gui`) is never blocked.

## Library

```python
import pandas as pd
from qaudit.core.audit import AuditOptions, run_audit
from qaudit.core.validate import validate
from qaudit.io.method import load_method
from qaudit.io.readers.common import infer_mapping
from qaudit.io.readers.dataframe import from_dataframe

table = from_dataframe(df, initial_balance=10_000.0, currency="USD")
config = load_method()
validation = validate(table, infer_mapping(table.columns), max_gap_days=config.max_gap_days)
result = run_audit(validation, config, AuditOptions(seed=0))
print(result.verdict.decision, [b.name for b in result.verdict.barriers if b.triggered])
```

An external regime classifier can be injected with `run_audit(..., classifier=…)`
(protocol `qaudit.core.regimes.RegimeClassifier`).

## Development

```bash
pip install -e ".[dev]"
pytest              # unit, property-based (hypothesis), golden and regression tests
mypy --strict       # 0 errors, local stubs for scipy/pandas in stubs/
ruff check .        # cyclomatic complexity ≤ 10, global randomness forbidden (NPY002)
pytest --cov        # coverage of core/ ≥ 90 %
```

Architecture rules (checked by `tests/test_architecture.py`): `core/` imports
neither `io/`, `cli/` nor `i18n/`; no disk or network access in the core (a test
cuts the sockets); randomness only through a `numpy.random.Generator` passed as
a parameter; no user-facing string in the code (i18n keys, `fr.toml` /
`en.toml` catalogues with identical keys).

Golden fixtures (`tests/fixtures/`, regenerated byte for byte by
`tests/fixtures/generate.py`) are synthetic: healthy witness, martingale, grid,
no stop + asymmetry, no-edge noise, ruin, look-ahead. **The healthy witness is
the safeguard: if it comes out NO-GO, the engine is broken.**

Measured budgets: full audit of 1,000 trades × 10,000 iterations in ≈ 2.8 s;
80 systems in parallel in ≈ 22 s.

Contributions: see [CONTRIBUTING.md](CONTRIBUTING.md).

## Services

The engine is free. What the maintainer sells is what a copy of the code cannot
give: an audit re-run by a third party and recorded in a public registry.

| Service | Price | |
|---|---|---|
| Open-source engine | free | the whole engine, every report, AGPL-3.0-or-later |
| Pre-check | free | is your file usable? Answer before any payment |
| Transferable attestation | 390 € | we re-run the audit on your file; on GO, a numbered attestation in the public registry that your buyers verify themselves; due whatever the verdict |
| Portfolio of systems | on quote | several systems with the multiple-selection correction |
| Due diligence | on quote | everything, plus an investment-committee note |
| Commercial licence | on quote | embed the engine in a closed-source product or service without the AGPL obligations |

The static site of the service is generated by `packaging/build_site.py` from
`site.toml` (contact, order and payment links, prices).

## Licence

Copyright © 2026 — see [NOTICE](NOTICE).

qaudit is free software under the **GNU Affero General Public License v3.0 or
later** ([LICENSE](LICENSE)). If you run a modified version as a network
service, the AGPL requires you to offer its source to its users. A **commercial
licence** is available for closed-source use.

## What qaudit does not do

It never executes strategy code (it observes, it does not replay); it never
recommends a setting; it never guesses a prop-firm rule; it calls no language
model, neither in the computation nor in the verdict. It is not investment
advice.
