import unittest

import numpy as np
import pandas as pd

from src.metrics import buy_wait_agree, cheapest_day_error, curve_spearman


class MetricTests(unittest.TestCase):
    def test_cheapest_day_error_is_absolute_day_gap(self):
        days = np.array([21, 14, 7, 1])
        actual = np.array([200.0, 150.0, 180.0, 220.0])
        pred = np.array([190.0, 170.0, 140.0, 210.0])
        self.assertEqual(cheapest_day_error(days, actual, pred), 7)

    def test_buy_wait_agree_when_both_say_wait(self):
        days = np.array([21, 14, 7])
        # today=21: actual drops $20 later; pred also drops
        actual = np.array([200.0, 170.0, 190.0])
        pred = np.array([200.0, 180.0, 195.0])
        self.assertTrue(buy_wait_agree(days, actual, pred, as_of_days=21, margin=8))

    def test_buy_wait_disagree_when_pred_is_flat(self):
        days = np.array([21, 14, 7])
        actual = np.array([200.0, 170.0, 190.0])
        pred = np.array([200.0, 198.0, 199.0])
        self.assertFalse(buy_wait_agree(days, actual, pred, as_of_days=21, margin=8))

    def test_spearman_perfect_rank(self):
        y = np.array([3.0, 2.0, 1.0])
        p = np.array([30.0, 20.0, 10.0])
        self.assertAlmostEqual(curve_spearman(y, p), 1.0)


if __name__ == "__main__":
    unittest.main()
