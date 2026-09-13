from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.backtest import prepare_daily_market, simulate_backtest, summarize_policy
from src.remaining_curve import FEATURE_COLS


class FallingCurveModel:
    def predict(self, frame):
        days = frame["days_before_departure"].to_numpy(dtype=float)
        as_of = frame["as_of_days"].to_numpy(dtype=float)
        return 0.70 + 0.30 * days / np.maximum(as_of, 1)


def _daily_market():
    rows = []
    for flight_index in range(10):
        flight = pd.Timestamp("2022-10-01") + pd.Timedelta(days=flight_index)
        for days, fare in [(21, 200), (14, 180), (7, 150), (1, 170)]:
            rows.append(
                {
                    "searchDate": flight - pd.Timedelta(days=days),
                    "flightDate": flight,
                    "startingAirport": "ATL",
                    "destinationAirport": "LAX",
                    "totalFare": fare,
                    "isNonStop": False,
                    "totalTravelDistance": 1940,
                }
            )
    return prepare_daily_market(pd.DataFrame(rows))


def _bundle():
    return {
        "model": FallingCurveModel(),
        "feature_cols": FEATURE_COLS,
        "route_categories": pd.Index(["ATL-LAX"]),
    }


class BacktestTests(unittest.TestCase):
    def test_daily_market_keeps_cheapest_offer(self):
        raw = pd.DataFrame(
            [
                {
                    "searchDate": "2022-09-01",
                    "flightDate": "2022-09-20",
                    "startingAirport": "ATL",
                    "destinationAirport": "LAX",
                    "totalFare": 220,
                    "isNonStop": False,
                    "totalTravelDistance": 1940,
                },
                {
                    "searchDate": "2022-09-01",
                    "flightDate": "2022-09-20",
                    "startingAirport": "ATL",
                    "destinationAirport": "LAX",
                    "totalFare": 190,
                    "isNonStop": False,
                    "totalTravelDistance": 1940,
                },
            ]
        )
        daily = prepare_daily_market(raw)
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily.iloc[0]["best_fare"], 190)

    def test_simulator_pays_observed_fare_on_predicted_day(self):
        decisions, _ = simulate_backtest(
            _daily_market(),
            _bundle(),
            minimum_savings=8,
            period_start_fraction=0.1,
            max_decisions=None,
        )
        waited = decisions.loc[decisions["model_action"].eq("WAIT")]
        self.assertFalse(waited.empty)
        self.assertTrue((waited["model_paid_fare"] > 0).all())
        # The policy pays the observed $170 quote on its predicted day-1 purchase,
        # not the model's synthetic dollar estimate and not the $150 oracle minimum.
        self.assertTrue((waited["model_savings"] == 30).any())

    def test_summary_contains_bootstrap_interval(self):
        decisions = pd.DataFrame(
            {"savings": [10.0, 0.0, -5.0], "action": ["WAIT", "BUY", "WAIT"]}
        )
        summary = summarize_policy(decisions, "savings", "action", bootstrap_samples=30)
        self.assertEqual(summary.observations, 3)
        self.assertLessEqual(summary.mean_savings_ci95_low, summary.mean_savings)
        self.assertGreaterEqual(summary.mean_savings_ci95_high, summary.mean_savings)


if __name__ == "__main__":
    unittest.main()
