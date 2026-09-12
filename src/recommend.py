import joblib
import numpy as np
import pandas as pd
from datetime import date, timedelta

from src.features import is_weekend_dow, near_holiday
from src.live_price import lookup_live_min_fare
from src.remaining_curve import FEATURE_COLS

MODEL_PATH = "models/price_model.joblib"
MAX_DAYS = 60
MIN_MEANINGFUL_SAVINGS = 8.0
SUPPORTED_AIRPORTS = frozenset({
    "ATL", "BOS", "CLT", "DEN", "DFW", "DTW", "EWR", "IAD",
    "JFK", "LAX", "LGA", "MIA", "OAK", "ORD", "PHL", "SFO",
})

_bundle = None


def set_bundle(bundle):
    """Tests inject a fake artifact so we don't load models/price_model.joblib."""
    global _bundle
    _bundle = bundle


def _get_bundle():
    global _bundle
    if _bundle is None:
        _bundle = joblib.load(MODEL_PATH)
    return _bundle


def _dow(d):
    # duckdb's dayofweek() is Sun=0..Sat=6; python's date.weekday() is Mon=0..Sun=6
    return (d.weekday() + 1) % 7


def _frame_for_curve(origin, destination, flight_date, current_price, today, is_nonstop, bundle):
    route = f"{origin}-{destination}"
    days_left = (flight_date - today).days
    days = list(range(MAX_DAYS, 0, -1))
    search_dates = [flight_date - timedelta(days=d) for d in days]
    distance = bundle["route_distance"].get(route, bundle["global_median_distance"])
    curve = pd.DataFrame({
        "days_before_departure": days,
        "as_of_days": days_left,
        "current_fare": current_price,
        "departure_day_of_week": _dow(flight_date),
        "departure_month": flight_date.month,
        "search_day_of_week": [_dow(d) for d in search_dates],
        "totalTravelDistance": distance,
        "is_nonstop": is_nonstop,
        "flightDate": flight_date,
        "route": route,
    })
    curve["log_current_fare"] = np.log(max(float(current_price), 1.0))
    curve["departure_is_weekend"] = is_weekend_dow(_dow(flight_date))
    curve["near_holiday"] = near_holiday(flight_date)
    curve["route_cat"] = pd.Categorical([route] * len(curve), categories=bundle["route_categories"])
    return curve


def _predict_relative(origin, destination, flight_date, current_price, today, is_nonstop, bundle):
    curve = _frame_for_curve(origin, destination, flight_date, current_price, today, is_nonstop, bundle)
    cols = bundle.get("feature_cols", FEATURE_COLS)
    rel = np.clip(bundle["model"].predict(curve[cols]), 0.3, 3.0)
    days_left = (flight_date - today).days
    today_mask = curve["days_before_departure"].to_numpy() == days_left
    today_rel = float(rel[today_mask][0]) if today_mask.any() else 1.0
    if today_rel <= 0:
        today_rel = 1.0
    # Keep the predicted shape; scale so today equals the observed/live fare.
    curve["predicted_fare"] = rel / today_rel * float(current_price)
    return curve


def _resolved_current_price(origin, destination, current_price, bundle):
    if current_price is not None:
        return float(current_price)
    route = f"{origin}-{destination}"
    medians = bundle.get("route_median_fare")
    if medians is not None:
        return float(medians.get(route, bundle.get("global_median_fare", 150.0)))
    return float(bundle.get("global_median_fare", 150.0))


STOPS_ALL = "all"
STOPS_NONSTOP = "nonstop"
STOPS_CONNECTING = "connecting"
_STOPS_ALIASES = {
    "all": STOPS_ALL,
    "": STOPS_ALL,
    "nonstop": STOPS_NONSTOP,
    "nonstoponly": STOPS_NONSTOP,
    "stop": STOPS_CONNECTING,
    "stops": STOPS_CONNECTING,
    "connecting": STOPS_CONNECTING,
}


def normalize_stops(stops=None, nonstop_only=None):
    """Map UI/API values to all | nonstop | connecting. ALL is the default."""
    if stops is not None:
        raw = str(stops).strip().lower().replace(" ", "").replace("_", "").replace("-", "")
        if raw not in _STOPS_ALIASES:
            raise ValueError("Stops must be ALL, non-stop, or stop.")
        return _STOPS_ALIASES[raw]
    if nonstop_only:
        return STOPS_NONSTOP
    return STOPS_ALL


def predict_curve(origin, destination, flight_date, current_price=None, today=None,
                  nonstop_only=None, stops=None):
    """Remaining best-fare curve, pinned to today's observed price when given.

    stops='nonstop' / 'connecting' use that pool only. stops='all' (default)
    takes the cheaper of the two for each day.
    """
    today = today or date.today()
    bundle = _get_bundle()
    price = _resolved_current_price(origin, destination, current_price, bundle)
    stops = normalize_stops(stops=stops, nonstop_only=nonstop_only)

    if bundle.get("model_kind") != "relative_remaining":
        return _predict_absolute_legacy(origin, destination, flight_date, bundle)

    if stops == STOPS_NONSTOP:
        return _predict_relative(origin, destination, flight_date, price, today, True, bundle)
    if stops == STOPS_CONNECTING:
        return _predict_relative(origin, destination, flight_date, price, today, False, bundle)

    connecting = _predict_relative(origin, destination, flight_date, price, today, False, bundle)
    nonstop = _predict_relative(origin, destination, flight_date, price, today, True, bundle)
    mixed = connecting.copy()
    mixed["predicted_fare"] = np.minimum(connecting["predicted_fare"], nonstop["predicted_fare"])
    days_left = (flight_date - today).days
    today_mask = mixed["days_before_departure"] == days_left
    today_pred = float(mixed.loc[today_mask, "predicted_fare"].iloc[0])
    if today_pred > 0:
        mixed["predicted_fare"] = mixed["predicted_fare"] * (float(price) / today_pred)
    return mixed


def _predict_absolute_legacy(origin, destination, flight_date, bundle):
    route = f"{origin}-{destination}"
    days = list(range(MAX_DAYS, 0, -1))
    search_dates = [flight_date - timedelta(days=d) for d in days]
    curve = pd.DataFrame({
        "days_before_departure": days,
        "departure_day_of_week": _dow(flight_date),
        "departure_month": flight_date.month,
        "search_day_of_week": [_dow(d) for d in search_dates],
        "totalTravelDistance": bundle["route_distance"].get(route, bundle["global_median_distance"]),
    })
    curve["route_cat"] = pd.Categorical([route] * len(curve), categories=bundle["route_categories"])
    curve["predicted_fare"] = bundle["model"].predict(curve[bundle["feature_cols"]])
    return curve


def _buy_window(remaining, best_day, best_price, margin=MIN_MEANINGFUL_SAVINGS):
    """Contiguous block of days around best_day within `margin` of the best price."""
    ordered = remaining.sort_values("days_before_departure", ascending=False).reset_index(drop=True)
    within = ordered["predicted_fare"] <= best_price + margin
    best_idx = ordered.index[ordered["days_before_departure"] == best_day][0]

    lo = hi = best_idx
    while lo > 0 and within[lo - 1]:
        lo -= 1
    while hi < len(ordered) - 1 and within[hi + 1]:
        hi += 1

    window_days = ordered.loc[lo:hi, "days_before_departure"]
    return int(window_days.max()), int(window_days.min())


def _buy_when_text(window_start, window_end):
    if window_start == window_end:
        return f"by {window_start:%b %-d}"
    return f"between {window_start:%b %-d} and {window_end:%b %-d}"


def _price_pin(origin, destination, flight_date, current_price, stops, lookup_live):
    """User fare wins; otherwise a published web fare; otherwise the route median."""
    if current_price is not None:
        return float(current_price), {
            "price_source": "user",
            "price_source_label": (
                f"Pinned to the ${float(current_price):.0f} fare you entered. "
                "The predicted trend is unchanged; only the dollar level is scaled."
            ),
            "live_matched_date": None,
        }
    if lookup_live:
        live = lookup_live_min_fare(
            origin, destination, flight_date=flight_date, stops=stops,
        )
        if live:
            return float(live["price"]), {
                "price_source": "web",
                "price_source_label": live["label"],
                "live_matched_date": live.get("matched_date"),
            }
        return None, {
            "price_source": "model",
            "price_source_label": (
                "Couldn't find a live published fare, so this uses the historical typical "
                "price for this route. The predicted trend is unchanged."
            ),
            "live_matched_date": None,
        }
    return None, {
        "price_source": "model",
        "price_source_label": (
            "Using the historical typical price for this route. Enter today's fare "
            "or leave it blank on the site to look up a published one-way."
        ),
        "live_matched_date": None,
    }


def recommend_purchase_timing(origin, destination, flight_date, today=None,
                              current_price=None, nonstop_only=None, lookup_live=False,
                              stops=None):
    today = today or date.today()
    origin = str(origin).strip().upper()
    destination = str(destination).strip().upper()
    days_left = (flight_date - today).days
    stops = normalize_stops(stops=stops, nonstop_only=nonstop_only)

    if origin == destination:
        return {
            "status": "error",
            "message": "Origin and destination must be different airports.",
        }
    if origin not in SUPPORTED_AIRPORTS or destination not in SUPPORTED_AIRPORTS:
        return {
            "status": "error",
            "message": "Pick both airports from the supported list.",
        }
    if days_left <= 0:
        return {"status": "error", "message": "Flight date must be in the future."}
    if days_left > MAX_DAYS:
        return {
            "status": "too_far",
            "message": f"Flight is {days_left} days out - the model only has reliable data up to "
                       f"{MAX_DAYS} days before departure. Check back closer to the flight.",
        }

    pin_price, pin_meta = _price_pin(
        origin, destination, flight_date, current_price, stops, lookup_live,
    )
    curve = predict_curve(
        origin, destination, flight_date,
        current_price=pin_price, today=today, stops=stops,
    )
    curve_records = curve[["days_before_departure", "predicted_fare"]].round(2).to_dict("records")
    pinned_price = float(curve.loc[curve["days_before_departure"] == days_left, "predicted_fare"].iloc[0])

    remaining = curve[curve["days_before_departure"] <= days_left]
    best_row = remaining.loc[remaining["predicted_fare"].idxmin()]
    best_day, best_price = int(best_row["days_before_departure"]), float(best_row["predicted_fare"])

    window_far_days, window_near_days = _buy_window(remaining, best_day, best_price)
    window_start = flight_date - timedelta(days=window_far_days)
    window_end = flight_date - timedelta(days=window_near_days)
    best_date = flight_date - timedelta(days=best_day)
    window_fields = {
        "best_day": best_day,
        "best_date": best_date.isoformat(),
        "buy_window_start": window_start.isoformat(),
        "buy_window_end": window_end.isoformat(),
        "buy_window_start_days": window_far_days,
        "buy_window_end_days": window_near_days,
    }

    extra = {
        "flight_date": flight_date.isoformat(),
        "stops": stops,
        "nonstop_only": stops == STOPS_NONSTOP,
        **window_fields,
        **pin_meta,
    }

    savings = pinned_price - best_price
    when = _buy_when_text(window_start, window_end)
    if best_day == days_left or savings < MIN_MEANINGFUL_SAVINGS:
        return {
            "status": "buy_now",
            "current_price": round(pinned_price, 2),
            "days_left": days_left,
            "today": today.isoformat(),
            "curve": curve_records,
            "message": f"Buy {when}. Waiting isn't expected to save $8+ before departure.",
            **extra,
        }

    wait_days = days_left - best_day
    lowest = f"Lowest predicted fare is around {best_date:%b %-d}"
    return {
        "status": "wait",
        "wait_days": wait_days,
        "current_price": round(pinned_price, 2),
        "expected_best_price": round(best_price, 2),
        "expected_savings": round(savings, 2),
        "days_left": days_left,
        "today": today.isoformat(),
        "curve": curve_records,
        "message": f"Wait, then buy {when}. {lowest}. "
                   f"You could save around ${savings:.2f} by waiting.",
        **extra,
    }


if __name__ == "__main__":
    examples = [
        ("ATL", "LAX", date.today() + timedelta(days=45), 180),
        ("ATL", "LAX", date.today() + timedelta(days=8), 220),
        ("LAX", "BOS", date.today() + timedelta(days=25), 250),
    ]
    for origin, destination, flight_date, price in examples:
        result = recommend_purchase_timing(
            origin, destination, flight_date, current_price=price,
        )
        print(f"{origin}->{destination}, flight {flight_date} @ ${price}:")
        print(f"  {result['message']}\n")
