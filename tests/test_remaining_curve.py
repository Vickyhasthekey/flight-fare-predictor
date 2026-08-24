import unittest

import pandas as pd

from src.remaining_curve import make_remaining_pairs


class RemainingCurveTests(unittest.TestCase):
    def setUp(self):
        self.daily = pd.DataFrame({
            "startingAirport": ["ATL", "ATL", "ATL"],
            "destinationAirport": ["LAX", "LAX", "LAX"],
            "flightDate": pd.to_datetime(["2022-08-01"] * 3),
            "isNonStop": [False, False, False],
            "days_before_departure": [21, 14, 7],
            "best_fare": [200.0, 160.0, 180.0],
            "departure_day_of_week": [1, 1, 1],
            "departure_month": [8, 8, 8],
            "search_day_of_week": [1, 1, 1],
            "totalTravelDistance": [2000.0, 2000.0, 2000.0],
        })

    def test_pairs_only_look_forward_or_same_day(self):
        pairs = make_remaining_pairs(self.daily, as_of_stride=1)
        self.assertTrue((pairs["days_before_departure"] <= pairs["as_of_days"]).all())

    def test_same_day_pair_has_relative_fare_of_one(self):
        pairs = make_remaining_pairs(self.daily, as_of_stride=1)
        same = pairs[pairs["days_before_departure"] == pairs["as_of_days"]]
        self.assertGreater(len(same), 0)
        self.assertTrue((same["rel_fare"] == 1.0).all())

    def test_future_pair_is_future_over_current(self):
        pairs = make_remaining_pairs(self.daily, as_of_stride=1)
        row = pairs[(pairs["as_of_days"] == 21) & (pairs["days_before_departure"] == 14)].iloc[0]
        self.assertAlmostEqual(row["rel_fare"], 160.0 / 200.0)
        self.assertAlmostEqual(row["current_fare"], 200.0)


if __name__ == "__main__":
    unittest.main()
