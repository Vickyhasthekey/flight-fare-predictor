# Evaluation artifacts

`fare-signal backtest` writes the reproducible booking simulation here:

- `backtest_results.json` - aggregate metrics and configuration
- `backtest_decisions.csv` - one row per simulated booking decision

The checked-in model lives under `models/`. Full-data tables remain ignored because they are too
large for Git.
