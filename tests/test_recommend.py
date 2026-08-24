import unittest
from datetime import date, timedelta

import numpy as np
import pandas as pd

import src.recommend as recommend


class FakeRelativeModel:
    def predict(self, X):
        days = X["days_before_departure"].to_numpy(dtype=float)
        as_of = np.maximum(X["as_of_days"].to_numpy(dtype=float), 1.0)
        is_ns = X["is_nonstop"].to_numpy()
        connecting = 0.70 + 0.30 * (days / as_of)
        nonstop = np.full(len(X), 1.05)
        return np.where(is_ns, nonstop, connecting)


def _bundle():
    routes = pd.Index(["ATL-LAX"])
    return {
        "model": FakeRelativeModel(),
        "model_kind": "relative_remaining",
        "route_categories": routes,
        "feature_cols": [
            "route_cat", "is_nonstop", "days_before_departure", "as_of_days",
            "log_current_fare", "departure_day_of_week", "departure_month",
            "search_day_of_week", "totalTravelDistance", "departure_is_weekend",
            "near_holiday",
        ],
        "route_distance": pd.Series({"ATL-LAX": 1940.0}),
        "global_median_distance": 1500.0,
        "route_median_fare": pd.Series({"ATL-LAX": 180.0}),
        "global_median_fare": 160.0,
    }


class RecommendTests(unittest.TestCase):
    def setUp(self):
        recommend.set_bundle(_bundle())
        self.today = date(2026, 3, 1)
        self.flight = self.today + timedelta(days=21)

    def tearDown(self):
        recommend.set_bundle(None)

    def test_pins_today_to_the_observed_fare(self):
        curve = recommend.predict_curve(
            "ATL", "LAX", self.flight, current_price=210.0, today=self.today, nonstop_only=False,
        )
        today_row = curve.loc[curve["days_before_departure"] == 21].iloc[0]
        self.assertAlmostEqual(float(today_row["predicted_fare"]), 210.0)

    def test_remaining_curve_scales_from_current_price(self):
        curve = recommend.predict_curve(
            "ATL", "LAX", self.flight, current_price=200.0, today=self.today, nonstop_only=False,
        )
        day14 = float(curve.loc[curve["days_before_departure"] == 14, "predicted_fare"].iloc[0])
        self.assertAlmostEqual(day14, 200.0 * (0.70 + 0.30 * 14 / 21), places=2)

    def test_nonstop_only_uses_the_nonstop_curve(self):
        curve = recommend.predict_curve(
            "ATL", "LAX", self.flight, current_price=200.0, today=self.today, nonstop_only=True,
        )
        day7 = float(curve.loc[curve["days_before_departure"] == 7, "predicted_fare"].iloc[0])
        self.assertAlmostEqual(day7, 200.0 * 1.05, places=2)

    def test_any_itinerary_picks_the_cheaper_of_nonstop_and_connecting(self):
        any_curve = recommend.predict_curve(
            "ATL", "LAX", self.flight, current_price=200.0, today=self.today, nonstop_only=False,
        )
        ns_curve = recommend.predict_curve(
            "ATL", "LAX", self.flight, current_price=200.0, today=self.today, nonstop_only=True,
        )
        day7_any = float(any_curve.loc[any_curve["days_before_departure"] == 7, "predicted_fare"].iloc[0])
        day7_ns = float(ns_curve.loc[ns_curve["days_before_departure"] == 7, "predicted_fare"].iloc[0])
        self.assertLess(day7_any, day7_ns)

    def test_wait_recommendation_uses_pinned_today(self):
        result = recommend.recommend_purchase_timing(
            "ATL", "LAX", self.flight, today=self.today, current_price=200.0,
        )
        self.assertEqual(result["status"], "wait")
        self.assertEqual(result["current_price"], 200.0)
        self.assertGreater(result["expected_savings"], 8)


if __name__ == "__main__":
    unittest.main()
