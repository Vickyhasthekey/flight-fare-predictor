import numpy as np
import pandas as pd

DEFAULT_MARGIN = 8.0


def cheapest_day_error(days, actual, pred):
    days = np.asarray(days)
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    return abs(int(days[np.argmin(actual)]) - int(days[np.argmin(pred)]))


def buy_wait_agree(days, actual, pred, as_of_days, margin=DEFAULT_MARGIN):
    days = np.asarray(days)
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    remaining = days <= as_of_days
    days, actual, pred = days[remaining], actual[remaining], pred[remaining]
    today = days == as_of_days
    if not today.any():
        return False
    actual_wait = (actual[today][0] - actual.min()) >= margin
    pred_wait = (pred[today][0] - pred.min()) >= margin
    return bool(actual_wait == pred_wait)


def curve_spearman(y, p):
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    if len(y) < 3 or np.std(y) < 1e-6 or np.std(p) < 1e-6:
        return float("nan")
    return float(pd.Series(y).corr(pd.Series(p), method="spearman"))
