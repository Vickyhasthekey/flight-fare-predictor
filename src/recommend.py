import joblib
import pandas as pd
from datetime import date, timedelta

MODEL_PATH = "models/price_model.joblib"
MAX_DAYS = 60  # the data (and therefore the model) only covers up to 60 days before departure
MIN_MEANINGFUL_SAVINGS = 10.0  # below this, "wait N days" isn't a convincing recommendation

# Everything needed at inference time - model, route categories, and the
# route-distance lookup - lives in this one file, so this module never needs
# data/training_table.parquet (too big to commit, won't exist when deployed).
bundle = joblib.load(MODEL_PATH)
model = bundle["model"]
route_categories = bundle["route_categories"]
feature_cols = bundle["feature_cols"]
_route_distance = bundle["route_distance"]
_global_median_distance = bundle["global_median_distance"]


def _dow(d):
    # duckdb's dayofweek() is Sun=0..Sat=6; python's date.weekday() is Mon=0..Sun=6
    return (d.weekday() + 1) % 7


def predict_curve(origin, destination, flight_date):
    """Predicted best fare for every days_before_departure from MAX_DAYS down to 1."""
    route = f"{origin}-{destination}"
    days = list(range(MAX_DAYS, 0, -1))
    search_dates = [flight_date - timedelta(days=d) for d in days]

    curve = pd.DataFrame({
        "days_before_departure": days,
        "departure_day_of_week": _dow(flight_date),
        "departure_month": flight_date.month,
        "search_day_of_week": [_dow(d) for d in search_dates],
        "totalTravelDistance": _route_distance.get(route, _global_median_distance),
    })
    curve["route_cat"] = pd.Categorical([route] * len(curve), categories=route_categories)
    curve["predicted_fare"] = model.predict(curve[feature_cols])
    return curve


def recommend_purchase_timing(origin, destination, flight_date, today=None):
    today = today or date.today()
    days_left = (flight_date - today).days

    if days_left <= 0:
        return {"status": "error", "message": "Flight date must be in the future."}
    if days_left > MAX_DAYS:
        return {
            "status": "too_far",
            "message": f"Flight is {days_left} days out - the model only has reliable data up to "
                       f"{MAX_DAYS} days before departure. Check back closer to the flight.",
        }

    curve = predict_curve(origin, destination, flight_date)
    curve_records = curve[["days_before_departure", "predicted_fare"]].round(2).to_dict("records")
    current_price = float(curve.loc[curve["days_before_departure"] == days_left, "predicted_fare"].iloc[0])

    # only look at the window that's actually still ahead of us (today through departure) -
    # a day that's already passed can't be recommended
    remaining = curve[curve["days_before_departure"] <= days_left]
    best_row = remaining.loc[remaining["predicted_fare"].idxmin()]
    best_day, best_price = int(best_row["days_before_departure"]), float(best_row["predicted_fare"])

    savings = current_price - best_price
    if best_day == days_left or savings < MIN_MEANINGFUL_SAVINGS:
        return {
            "status": "buy_now",
            "current_price": round(current_price, 2),
            "days_left": days_left,
            "curve": curve_records,
            "message": f"Buy now - predicted price ${current_price:.2f}. "
                       f"Price is expected to stay about the same or rise before departure.",
        }

    wait_days = days_left - best_day
    return {
        "status": "wait",
        "wait_days": wait_days,
        "current_price": round(current_price, 2),
        "expected_best_price": round(best_price, 2),
        "expected_savings": round(savings, 2),
        "days_left": days_left,
        "curve": curve_records,
        "message": f"Wait about {wait_days} more day(s). Price is predicted to drop from "
                   f"${current_price:.2f} to ${best_price:.2f} (~${savings:.2f} savings).",
    }


if __name__ == "__main__":
    examples = [
        ("ATL", "LAX", date.today() + timedelta(days=45)),
        ("ATL", "LAX", date.today() + timedelta(days=8)),
        ("LAX", "BOS", date.today() + timedelta(days=25)),
        ("ATL", "LAX", date.today() + timedelta(days=60)),
        ("LAX", "BOS", date.today() + timedelta(days=60)),
    ]
    for origin, destination, flight_date in examples:
        result = recommend_purchase_timing(origin, destination, flight_date)
        print(f"{origin}->{destination}, flight {flight_date} (in {(flight_date - date.today()).days} days):")
        print(f"  {result['message']}\n")
