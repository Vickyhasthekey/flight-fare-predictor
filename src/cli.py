from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date

from src.backtest import evaluate
from src.data_pipeline import build_daily_training_table, clean_raw_csv
from src.recommend import recommend_purchase_timing


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fare-signal",
        description="FareSignal data, model, backtest, and recommendation workflows.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="Stream the raw 82M-row CSV to Parquet.")
    ingest.add_argument("--input", required=True)
    ingest.add_argument("--output", default="data/flight_prices_clean.parquet")

    table = commands.add_parser("build-table", help="Build daily route-market training curves.")
    table.add_argument("--input", default="data/flight_prices_clean.parquet")
    table.add_argument("--output", default="data/training_table.parquet")

    commands.add_parser("train", help="Train and save the remaining-fare-curve model.")

    backtest = commands.add_parser("backtest", help="Run the chronological booking simulator.")
    backtest.add_argument("--input", default="data/sample_flight_trajectories.csv")
    backtest.add_argument("--model", default="models/price_model.joblib")
    backtest.add_argument("--output", default="artifacts/backtest_results.json")
    backtest.add_argument("--minimum-savings", type=float, default=8.0)
    backtest.add_argument("--max-decisions", type=int, default=10_000)

    recommend = commands.add_parser("recommend", help="Generate one local recommendation.")
    recommend.add_argument("origin")
    recommend.add_argument("destination")
    recommend.add_argument("flight_date", type=date.fromisoformat)
    recommend.add_argument("--price", type=float)
    recommend.add_argument(
        "--stops", choices=["all", "nonstop", "connecting"], default="all"
    )

    args = parser.parse_args()
    if args.command == "ingest":
        _print(clean_raw_csv(args.input, args.output))
    elif args.command == "build-table":
        _print(build_daily_training_table(args.input, args.output))
    elif args.command == "train":
        subprocess.run([sys.executable, "src/train_model.py"], check=True)
    elif args.command == "backtest":
        _print(
            evaluate(
                args.input,
                args.model,
                args.output,
                minimum_savings=args.minimum_savings,
                max_decisions=args.max_decisions,
            )
        )
    elif args.command == "recommend":
        _print(
            recommend_purchase_timing(
                args.origin,
                args.destination,
                args.flight_date,
                current_price=args.price,
                stops=args.stops,
            )
        )


if __name__ == "__main__":
    main()
