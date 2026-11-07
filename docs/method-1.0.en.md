# qaudit method — version 1.0

This document fully describes the method qaudit applies to a trade history: the tests, their thresholds, the decision rules, the flaw detectors and their parameters. It is generated automatically from the method configuration file: what is written here is exactly what is computed.

Three principles. (1) The engine computes everything the data provided allows; the service ordered only changes what is shown, never the verdict. (2) No overall score: every test has a threshold fixed in advance, a single failed test is enough for a NO-GO. (3) Determinism: same data, same method version, same seed → the same report byte for byte, verifiable by anyone holding the file.

## The five barriers

Five eliminatory barriers. A barrier is “triggered” (failed) when its value crosses the threshold in the stated direction; a value inside the indecision band yields the verdict but requires a human review (gate E3); a barrier that cannot be computed for lack of data becomes a condition (never a pass).

| Barrier | Question asked | NO-GO threshold | Indecision band |
|---|---|---|---|
| Deflated Sharpe ratio (DSR) | Is chance ruled out? | < 50.0 % | [45.0 % ; 55.0 %] |
| Profit factor, 5th percentile of the block bootstrap | And with bad luck? | < 1.00 | [0.95 ; 1.05] |
| Percentile of the observed drawdown among order permutations | Do the losses come clustered? | < 5.00 | [3.00 ; 8.00] |
| p-value against the no-edge null | Would a system with no edge do as well? | ≥ 5.0 % | [3.0 % ; 8.0 %] |
| Out-of-sample walk-forward efficiency | Does it hold outside the periods it was tuned on? | < 40.0 % | [35.0 % ; 50.0 %] |

### Is chance ruled out?

Deflated Sharpe ratio (Bailey & López de Prado). The Sharpe ratio measures the steadiness of gains. The PSR is the probability that the true Sharpe is positive given the number of trades, the skewness and the tails of the distribution. The DSR evaluates that probability against the best Sharpe expected by chance after N attempts (N declared by the requester, else the method default); the variance of Sharpe across variants, if not provided, is approximated conservatively (Lo approximation, flagged). The report prints the DSR curve for N = 1 to 1,000 and the tipping point.

### And with bad luck?

Profit factor at the 5th percentile of the stationary block bootstrap (Politis–Romano, automatic block length). Trades are resampled in blocks to preserve their serial dependence; the profit factor is recomputed on each resample. The barrier looks at the 5th percentile: what the same strategy would yield in unfavourable scenarios. Below 1.00 it loses money in those scenarios.

### Do the losses come clustered?

Percentile of the observed drawdown among order permutations. The same trades are randomly reordered; total profit is invariant, only the drawdown changes. The percentile is the share of permutations whose drawdown is less than or equal to the observed one. A very low percentile signals a curve too smooth to be credible (arranged order, selection); a very high one is not eliminatory but signals clustered losses, printed as such.

### Would a system with no edge do as well?

p-value against the “no-edge” null. Systems with no edge at all are simulated by keeping the empirical distributions of gains and losses and neutralising only the hit frequency (break-even rate p₀ = |mean loss| / (mean gain + |mean loss|)). The p-value is the share of those systems reaching at least the observed net profit. This is not an efficient-market null: the question asked is “is the observed hit rate explainable by chance, given the profile of gains and losses?”.

### Does it hold outside the periods it was tuned on?

Walk-forward efficiency. The requester supplies one set of results per parameter set tested; the method splits the period into folds (anchored or rolling protocol), selects on each fold the parameter set by the fixed criterion, and measures the performance of the selected set on the following, unseen fold. Efficiency is the ratio of out-of-sample to in-sample performance. The auditor runs no strategy: it compares supplied results.

## Decision rules

- 1 blocking finding(s) or more → NO-GO.
- One triggered barrier → NO-GO.
- 3 major findings or more → GO CONDITIONAL at best.
- One barrier not evaluated (missing data) → condition; the verdict cannot be GO.
- A value inside the indecision band → verdict rendered, human review required (gate E3).
- Fewer than 30 usable trades → blocking finding “insufficient sample”.

There is neither weighting nor composite score: barriers do not offset one another.

## Structural detectors

Eleven structural detectors examine the way the trading is done. Eight work without a price series; three (stop geometry, look-ahead, execution realism) require the instrument's OHLC quotes and are reported as “not run” otherwise. Each detector raises a finding of severity info, minor, major or blocking according to the parameters below; a detector that cannot run says so.

| Detector | What it detects | Parameters |
|---|---|---|
| Stake increased after losses (`martingale`) | Volume increased after a loss (volume ratio ≥ ratio_min) on a share of post-loss trades; contrast with post-gain behaviour required. | ratio_min = 1.5, min_events = 10, major_share = 0.3, blocking_share = 0.6, contrast_min = 0.15 |
| Positions stacked against the market (`grid`) | Positions added to a losing position of the same direction at a worse price and closed together (basket); share of trades concerned. | min_depth = 1, major_share = 0.15, blocking_share = 0.35, min_trades = 20, basket_close_seconds = 120 |
| Trades without a protective stop (`no_stop`) | Share of trades without a stop-loss. | minor_share = 0.1, major_share = 0.5 |
| Profit carried by a few trades (`profit_concentration`) | Share of gross gain brought by the best trades (top_fraction); net profit once the best are removed (remove_fraction). | top_fraction = 0.05, share_major = 0.7, remove_fraction = 0.01, min_trades = 30 |
| Equity curve too smooth (`equity_linearity`) | Abnormally linear equity curve: R² against the trade index above r2_major. | r2_major = 0.995, min_trades = 50 |
| Many small wins, a few large losses (`payoff_asymmetry`) | Very high hit rate combined with a very low average win / average loss ratio. | win_rate_major = 0.85, payoff_major = 0.2, win_rate_blocking = 0.95, payoff_blocking = 0.1, min_trades = 30 |
| Result owed to a single period (`period_dependence`) | Share of net profit brought by a single quarter, over at least min_periods quarters. | min_periods = 4, share_major = 0.8 |
| Unrealistic holding times (`holding_time`) | Unrealistic holding times: share of trades under min_seconds, or over max_days. | min_seconds = 1, short_share_major = 0.1, short_share_blocking = 0.5, max_days = 365, long_share_minor = 0.1 |
| Stop too sensitive (`stop_geometry`) | With prices: share of gross gain that vanishes if the stop is tightened by 10 %, 20 %, 30 %. | collapse_major = 0.5, min_trades = 30, min_aligned_share = 0.5 |
| Entries too perfect (`lookahead`) | With prices: share of entries exactly at the low / high of their bar, tested against chance (p-value). | tick_bps = 1, min_share = 0.05, p_major = 0.01, p_blocking = 0.001, min_aligned_share = 0.5, min_trades = 30 |
| Impossible execution prices (`execution_realism`) | With prices: share of entry or exit prices outside the high–low range of their bar (tolerance in basis points). | tolerance_bps = 3, minor_share = 0.01, major_share = 0.05, blocking_share = 0.2, min_aligned_share = 0.5 |

Parameters are named as in the method file; shares are fractions (0.30 = 30 %).

## Simulations and parameters

- 10 000 iterations for the bootstrap, the permutation and the null, each on an independent random stream derived from the seed (fixed ranks).
- Bootstrap: stationary blocks (Politis-Romano), automatic length.
- Order permutation: the input table is never modified; total profit is invariant.
- No-edge null: empirical distributions of gains and losses kept, frequency neutralised.
- Default number of trials: 10; sensitivity grid: 1, 10, 50, 100, 300, 1000.
- Walk-forward: 5 folds, anchored protocol, selection by net profit.
- Regimes: volatility terciles over 20 trades (without prices) or ATR over 14 bars (with prices).
- Propfirm replay: paths of trading days resampled in blocks; horizon of unlimited phases: 250 days.
- Validation: a gap of more than 30 days between two closes is flagged.
- Default seed 0, printed in every report; no global source of randomness.

## Inputs

Mandatory input: closed trades (open time, close time, net profit; useful: volume, direction, symbol, prices, stop, ticket, commission, swap). Optional inputs: OHLC price series (enables the three price detectors and ATR regimes), one set of results per parameter set tested (enables the walk-forward barrier), a structured propfirm rulebook (enables the replay), the number of variants tried (N; method default otherwise).

## What the method does not test

- Only closed trades are analysed: floating P&L and open positions are unknown.
- Without a price series, stop sensitivity, look-ahead and execution realism are not tested — the report says so.
- Without results per parameter set, out-of-sample robustness is not established: the verdict cannot be GO.
- The method cannot prove that a history was not truncated beyond its consistency checks (gaps, ruin, duplicates).
- No future performance is predicted; a real edge can vanish.
- No settings are recommended; the auditor states facts.

## Versioning

Current version: 1.0. Any change to a threshold, a band or a detector parameter creates a new method version; the version is printed in every report and every attestation, which are valid for it only.

## Reproducing a report

To reproduce a report: the same trade file (its SHA-256 fingerprint is printed), the same qaudit and method versions, the same seed (printed). The command “qaudit render --from archive.json” regenerates the deliverables from the archive without any recomputation and yields the same bytes as the original audit.
