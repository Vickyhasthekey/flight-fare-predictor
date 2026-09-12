import unittest
from datetime import date

from src.features import is_weekend_dow, near_holiday, us_federal_holidays


class FeatureTests(unittest.TestCase):
    def test_2022_thanksgiving_is_a_federal_holiday(self):
        self.assertIn(date(2022, 11, 24), us_federal_holidays(2022))

    def test_july_4_week_is_near_holiday(self):
        self.assertTrue(near_holiday(date(2022, 7, 4)))
        self.assertTrue(near_holiday(date(2022, 7, 2)))
        self.assertFalse(near_holiday(date(2022, 7, 20)))

    def test_duckdb_dow_weekend(self):
        # duckdb dayofweek: Sun=0 .. Sat=6
        self.assertTrue(is_weekend_dow(0))
        self.assertTrue(is_weekend_dow(6))
        self.assertFalse(is_weekend_dow(3))


if __name__ == "__main__":
    unittest.main()
