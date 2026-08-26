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
        # Nonstop rel is a flat 1.05; scaling to today's $200 keeps that flat shape at $200.
        self.assertAlmostEqual(day7, 200.0, places=2)

    def test_connecting_only_uses_the_connecting_curve(self):
        curve = recommend.predict_curve(
            "ATL", "LAX", self.flight, current_price=200.0, today=self.today, stops="connecting",
        )
        day7 = float(curve.loc[curve["days_before_departure"] == 7, "predicted_fare"].iloc[0])
        self.assertAlmostEqual(day7, 200.0 * (0.70 + 0.30 * 7 / 21), places=2)

    def test_stop_alias_is_connecting(self):
        via_stop = recommend.predict_curve(
            "ATL", "LAX", self.flight, current_price=200.0, today=self.today, stops="stop",
        )
        via_connecting = recommend.predict_curve(
            "ATL", "LAX", self.flight, current_price=200.0, today=self.today, stops="connecting",
        )
        day7_stop = float(via_stop.loc[via_stop["days_before_departure"] == 7, "predicted_fare"].iloc[0])
        day7_conn = float(via_connecting.loc[via_connecting["days_before_departure"] == 7, "predicted_fare"].iloc[0])
        self.assertAlmostEqual(day7_stop, day7_conn)

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
        self.assertIn("between", result["message"])
        self.assertIn("Mar", result["message"])
        self.assertIn("Lowest predicted fare", result["message"])

    def test_buy_now_message_names_calendar_dates(self):
        result = recommend.recommend_purchase_timing(
            "ATL", "LAX", self.flight, today=self.today, current_price=200.0,
            nonstop_only=True,
        )
        self.assertEqual(result["status"], "buy_now")
        self.assertTrue(
            result["message"].startswith("Buy by ")
            or result["message"].startswith("Buy between "),
            result["message"],
        )
        self.assertIn("Mar", result["message"])

    def test_user_fare_is_not_replaced_by_a_live_lookup(self):
        result = recommend.recommend_purchase_timing(
            "ATL", "LAX", self.flight, today=self.today, current_price=200.0,
            lookup_live=True,
        )
        self.assertEqual(result["current_price"], 200.0)
        self.assertEqual(result["price_source"], "user")
        self.assertIn("200", result["price_source_label"])

    def test_live_lookup_scales_the_curve_and_keeps_the_trend(self):
        import src.live_price as live_price

        def fake_fetch(url):
            return '''
            <div>Cheapest one-way</div><div class="c_nzd-price">$100</div>
            "cheapestPopularOneWayFlight":{"deals":[
            {"providerName":"JetBlue","price":{"price":100,"currency":"USD"},
             "pickupDateIso":"2026-03-22","leg1Stops":1}
            ]},"cheapestPopularDirectFlight":{}
            '''

        live_price.set_fetch(fake_fetch)
        try:
            result = recommend.recommend_purchase_timing(
                "ATL", "LAX", self.flight, today=self.today, lookup_live=True,
            )
        finally:
            live_price.set_fetch(None)
        self.assertEqual(result["current_price"], 100.0)
        self.assertEqual(result["price_source"], "web")
        self.assertEqual(result["live_matched_date"], "2026-03-22")
        day14 = next(p["predicted_fare"] for p in result["curve"] if p["days_before_departure"] == 14)
        self.assertAlmostEqual(day14, 100.0 * (0.70 + 0.30 * 14 / 21), places=2)

    def test_scales_whole_curve_when_today_relative_is_not_one(self):
        class DriftModel:
            def predict(self, X):
                days = X["days_before_departure"].to_numpy(dtype=float)
                return 0.50 + 0.01 * days

        bundle = _bundle()
        bundle["model"] = DriftModel()
        recommend.set_bundle(bundle)
        curve = recommend.predict_curve(
            "ATL", "LAX", self.flight, current_price=200.0, today=self.today, nonstop_only=True,
        )
        today_row = curve.loc[curve["days_before_departure"] == 21].iloc[0]
        day14 = float(curve.loc[curve["days_before_departure"] == 14, "predicted_fare"].iloc[0])
        self.assertAlmostEqual(float(today_row["predicted_fare"]), 200.0)
        today_rel = 0.50 + 0.01 * 21
        day14_rel = 0.50 + 0.01 * 14
        self.assertAlmostEqual(day14, 200.0 * day14_rel / today_rel, places=2)


if __name__ == "__main__":
    unittest.main()
