# Verified development evaluation

This report verifies the upgraded repository on a deterministic trajectory-preserving sample. It is
not a substitute for the final 82M-row rerun.

## Evaluation data

```text
Raw sampled offers:         59,542
Daily market observations: 58,872
Validation period:          2022-08-15 through 2022-09-09
Test period:                2022-09-10 through 2022-10-05
Held-out booking decisions: 721
Decision points:            approximately 21, 14, and 7 days before departure
```

## Policy selection

The simulator tested predicted-savings thresholds on the validation period only. A `$15` threshold
was selected subject to a minimum 5% WAIT coverage constraint, then frozen for the test period.

## Held-out results

```text
BUY/WAIT agreement:         68.7%
Model WAIT rate:             5.5%
Model mean savings:         -$1.04 per eligible decision
Model win/tie/loss:          1.2% / 96.7% / 2.1%

Always buy mean savings:     $0.00
Always wait mean savings:  -$59.04
Trailing-median heuristic: -$24.14
Matched-rate random policy: -$4.14
Oracle reference:           $20.23
```

The model dramatically reduces the damage of indiscriminate waiting but does not yet outperform the
always-buy policy on mean savings. This is a useful engineering finding: curve-fit metrics alone do
not guarantee a profitable booking policy.

The next iteration should train directly on the economic decision target, calibrate expected savings,
and use route-aware uncertainty or abstention. Do not put a positive savings claim on the résumé until
that model passes the unchanged held-out simulator.

Machine-readable results are in `artifacts/backtest_results.json`, with individual simulated
decisions in `artifacts/backtest_decisions.csv`.
