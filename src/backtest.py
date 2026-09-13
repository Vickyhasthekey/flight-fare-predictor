"""Time-aware booking simulation for FareSignal.

The model predicts a remaining fare curve at historical decision points. The simulator then pays
the *observed* fare on the predicted purchase day, which keeps predicted values out of the outcome.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.features import is_weekend_dow, near_holiday

DECISION_DAYS = (21, 14, 7)


@dataclass(frozen=True)
class PolicySummary:
    observations: int
    wait_rate: float
    mean_savings: float
    median_savings: float
    win_rate: float
    tie_rate: float
    loss_rate: float
    mean_loss_when_wrong: float
    savings_p05: float
    mean_savings_ci95_low: float
    mean_savings_ci95_high: float


def _stable_uniform(key: str) -> float:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / (2**64 - 1)


def prepare_daily_market(frame: pd.DataFrame) -> pd.DataFrame:
    """Collapse raw offers into the cheapest observed route/date/stop-market quote per day."""
    required = {
        "searchDate",
        "flightDate",
        "startingAirport",
        "destinationAirport",
        "totalFare",
        "isNonStop",
        "totalTravelDistance",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Backtest data is missing required columns: {', '.join(missing)}")

    clean = frame.copy()
    clean["searchDate"] = pd.to_datetime(clean["searchDate"], errors="coerce")
    clean["flightDate"] = pd.to_datetime(clean["flightDate"], errors="coerce")
    clean["totalFare"] = pd.to_numeric(clean["totalFare"], errors="coerce")
    clean["totalTravelDistance"] = pd.to_numeric(
        clean["totalTravelDistance"], errors="coerce"
    )
    if not pd.api.types.is_bool_dtype(clean["isNonStop"]):
        clean["isNonStop"] = (
            clean["isNonStop"].astype("string").str.lower().map({"true": True, "false": False})
        )
    clean = clean.loc[
        clean["searchDate"].notna()
        & clean["flightDate"].notna()
        & clean["totalFare"].between(20, 5000, inclusive="neither")
        & (clean["searchDate"] < clean["flightDate"])
    ].copy()
    clean["days_before_departure"] = (
        clean["flightDate"] - clean["searchDate"]
    ).dt.days

    keys = [
        "startingAirport",
        "destinationAirport",
        "flightDate",
        "searchDate",
        "days_before_departure",
        "isNonStop",
    ]
    daily = (
        clean.groupby(keys, as_index=False, observed=True)
        .agg(
            best_fare=("totalFare", "min"),
            totalTravelDistance=("totalTravelDistance", "median"),
        )
        .sort_values(keys)
    )
    daily["route"] = daily["startingAirport"] + "-" + daily["destinationAirport"]
    daily["departure_day_of_week"] = (daily["flightDate"].dt.weekday + 1) % 7
    daily["departure_month"] = daily["flightDate"].dt.month
    daily["search_day_of_week"] = (daily["searchDate"].dt.weekday + 1) % 7
    return daily.reset_index(drop=True)


def _decision_frames(
    daily: pd.DataFrame,
    route_categories: pd.Index,
    *,
    period_start_fraction: float,
    period_end_fraction: float,
    decision_days: tuple[int, ...],
    max_decisions: int | None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str | None]]:
    unique_dates = np.sort(daily["searchDate"].dropna().unique())
    if len(unique_dates) < 3:
        raise ValueError("Backtesting requires at least three distinct search dates.")
    start_index = min(len(unique_dates) - 1, int(len(unique_dates) * period_start_fraction))
    end_index = min(len(unique_dates), int(len(unique_dates) * period_end_fraction))
    cutoff = pd.Timestamp(unique_dates[start_index])
    period_end = pd.Timestamp(unique_dates[end_index]) if end_index < len(unique_dates) else None

    candidates: list[tuple[str, pd.DataFrame, int]] = []
    group_keys = ["route", "flightDate", "isNonStop"]
    for key, group in daily.groupby(group_keys, sort=False, observed=True):
        group = group.sort_values("days_before_departure", ascending=False).reset_index(drop=True)
        if len(group) < 3 or key[0] not in route_categories:
            continue
        available = group["days_before_departure"].to_numpy()
        chosen: set[int] = set()
        for target in decision_days:
            position = int(np.argmin(np.abs(available - target)))
            as_of_days = int(available[position])
            if as_of_days in chosen:
                continue
            chosen.add(as_of_days)
            row = group.loc[group["days_before_departure"].eq(as_of_days)].iloc[0]
            if row["searchDate"] < cutoff or (
                period_end is not None and row["searchDate"] >= period_end
            ):
                continue
            remaining = group.loc[group["days_before_departure"] <= as_of_days]
            if len(remaining) < 2:
                continue
            decision_id = (
                f"{key[0]}|{pd.Timestamp(key[1]).date()}|{bool(key[2])}|{as_of_days}"
            )
            candidates.append((decision_id, group, as_of_days))

    candidates.sort(key=lambda item: hashlib.sha256(item[0].encode()).hexdigest())
    if max_decisions is not None:
        candidates = candidates[:max_decisions]

    feature_frames: list[pd.DataFrame] = []
    metadata: list[dict[str, object]] = []
    for decision_id, group, as_of_days in candidates:
        current = group.loc[group["days_before_departure"].eq(as_of_days)].iloc[0]
        remaining = group.loc[group["days_before_departure"] <= as_of_days].copy()
        prior = group.loc[group["days_before_departure"] >= as_of_days, "best_fare"]
        remaining["decision_id"] = decision_id
        remaining["as_of_days"] = as_of_days
        remaining["current_fare"] = float(current["best_fare"])
        remaining["log_current_fare"] = np.log(max(float(current["best_fare"]), 1.0))
        remaining["is_nonstop"] = remaining["isNonStop"].astype(bool)
        remaining["departure_is_weekend"] = remaining["departure_day_of_week"].map(
            is_weekend_dow
        )
        remaining["near_holiday"] = near_holiday(pd.Timestamp(current["flightDate"]).date())
        remaining["route_cat"] = pd.Categorical(
            remaining["route"], categories=route_categories
        )
        feature_frames.append(remaining)
        metadata.append(
            {
                "decision_id": decision_id,
                "route": current["route"],
                "flight_date": pd.Timestamp(current["flightDate"]).date().isoformat(),
                "search_date": pd.Timestamp(current["searchDate"]).date().isoformat(),
                "is_nonstop": bool(current["isNonStop"]),
                "as_of_days": as_of_days,
                "current_fare": float(current["best_fare"]),
                "trailing_median_fare": float(prior.median()),
            }
        )
    if not feature_frames:
        raise ValueError("No eligible holdout booking decisions were found.")
    period = {
        "start": cutoff.date().isoformat(),
        "end_exclusive": period_end.date().isoformat() if period_end is not None else None,
    }
    return pd.concat(feature_frames, ignore_index=True), pd.DataFrame(metadata), period


def simulate_backtest(
    daily: pd.DataFrame,
    bundle: dict,
    *,
    minimum_savings: float = 8.0,
    period_start_fraction: float = 0.85,
    period_end_fraction: float = 1.0,
    decision_days: tuple[int, ...] = DECISION_DAYS,
    max_decisions: int | None = 10_000,
) -> tuple[pd.DataFrame, dict[str, str | None]]:
    """Return one row per historical decision and the chronological holdout cutoff."""
    frames, decisions, period = _decision_frames(
        daily,
        bundle["route_categories"],
        period_start_fraction=period_start_fraction,
        period_end_fraction=period_end_fraction,
        decision_days=decision_days,
        max_decisions=max_decisions,
    )
    feature_cols = bundle["feature_cols"]
    frames["predicted_relative"] = np.clip(
        bundle["model"].predict(frames[feature_cols]), 0.3, 3.0
    )

    records: list[dict[str, object]] = []
    decision_lookup = decisions.set_index("decision_id")
    for decision_id, curve in frames.groupby("decision_id", sort=False, observed=True):
        meta = decision_lookup.loc[decision_id]
        current_mask = curve["days_before_departure"].eq(int(meta["as_of_days"]))
        today_relative = float(curve.loc[current_mask, "predicted_relative"].iloc[0])
        curve = curve.copy()
        curve["predicted_fare"] = (
            curve["predicted_relative"] / max(today_relative, 1e-9) * float(meta["current_fare"])
        )
        predicted_choice = curve.loc[curve["predicted_fare"].idxmin()]
        oracle_choice = curve.loc[curve["best_fare"].idxmin()]
        last_choice = curve.loc[curve["days_before_departure"].idxmin()]
        predicted_savings = float(meta["current_fare"] - predicted_choice["predicted_fare"])
        model_wait = bool(
            predicted_savings >= minimum_savings
            and int(predicted_choice["days_before_departure"]) < int(meta["as_of_days"])
        )
        model_paid = (
            float(predicted_choice["best_fare"]) if model_wait else float(meta["current_fare"])
        )
        heuristic_wait = float(meta["current_fare"]) > float(meta["trailing_median_fare"])
        random_wait = _stable_uniform(decision_id) < 0.5
        actual_wait = float(meta["current_fare"] - oracle_choice["best_fare"]) >= minimum_savings
        records.append(
            {
                "decision_id": decision_id,
                **meta.to_dict(),
                "model_action": "WAIT" if model_wait else "BUY",
                "actual_best_action": "WAIT" if actual_wait else "BUY",
                "predicted_purchase_days": int(predicted_choice["days_before_departure"]),
                "predicted_savings": predicted_savings,
                "wait_paid_fare": float(predicted_choice["best_fare"]),
                "model_paid_fare": model_paid,
                "model_savings": float(meta["current_fare"] - model_paid),
                "always_buy_action": "BUY",
                "always_buy_savings": 0.0,
                "always_wait_action": "WAIT",
                "always_wait_savings": float(meta["current_fare"] - last_choice["best_fare"]),
                "heuristic_action": "WAIT" if heuristic_wait else "BUY",
                "heuristic_savings": (
                    float(meta["current_fare"] - last_choice["best_fare"])
                    if heuristic_wait
                    else 0.0
                ),
                "random_action": "WAIT" if random_wait else "BUY",
                "random_savings": (
                    float(meta["current_fare"] - last_choice["best_fare"])
                    if random_wait
                    else 0.0
                ),
                "oracle_savings": float(meta["current_fare"] - oracle_choice["best_fare"]),
            }
        )
    return pd.DataFrame(records), period


def apply_model_threshold(decisions: pd.DataFrame, threshold: float) -> pd.DataFrame:
    result = decisions.copy()
    wait = (
        result["predicted_savings"].ge(threshold)
        & result["predicted_purchase_days"].lt(result["as_of_days"])
    )
    result["model_action"] = np.where(wait, "WAIT", "BUY")
    result["model_paid_fare"] = np.where(
        wait, result["wait_paid_fare"], result["current_fare"]
    )
    result["model_savings"] = result["current_fare"] - result["model_paid_fare"]
    return result


def tune_policy_threshold(
    validation: pd.DataFrame,
    *,
    candidates: tuple[float, ...] = (8, 10, 15, 20, 25, 30, 40, 50, 75),
    minimum_wait_rate: float = 0.05,
) -> tuple[float, list[dict[str, float]]]:
    search: list[dict[str, float]] = []
    for threshold in candidates:
        scored = apply_model_threshold(validation, threshold)
        summary = summarize_policy(
            scored, "model_savings", "model_action", bootstrap_samples=100
        )
        search.append(
            {
                "threshold": float(threshold),
                "mean_savings": summary.mean_savings,
                "wait_rate": summary.wait_rate,
                "savings_p05": summary.savings_p05,
            }
        )
    eligible = [item for item in search if item["wait_rate"] >= minimum_wait_rate]
    pool = eligible or search
    best = max(pool, key=lambda item: (item["mean_savings"], item["savings_p05"]))
    return best["threshold"], search


def summarize_policy(
    decisions: pd.DataFrame,
    savings_column: str,
    action_column: str,
    *,
    seed: int = 42,
    bootstrap_samples: int = 500,
) -> PolicySummary:
    savings = decisions[savings_column].astype(float).to_numpy()
    if len(savings) == 0:
        raise ValueError("Cannot summarize an empty backtest.")
    rng = np.random.default_rng(seed)
    means = np.array(
        [rng.choice(savings, size=len(savings), replace=True).mean() for _ in range(bootstrap_samples)]
    )
    losses = savings[savings < 0]
    actions = decisions[action_column]
    return PolicySummary(
        observations=len(savings),
        wait_rate=float(actions.eq("WAIT").mean()),
        mean_savings=float(savings.mean()),
        median_savings=float(np.median(savings)),
        win_rate=float((savings > 0).mean()),
        tie_rate=float((savings == 0).mean()),
        loss_rate=float((savings < 0).mean()),
        mean_loss_when_wrong=float(losses.mean()) if len(losses) else 0.0,
        savings_p05=float(np.quantile(savings, 0.05)),
        mean_savings_ci95_low=float(np.quantile(means, 0.025)),
        mean_savings_ci95_high=float(np.quantile(means, 0.975)),
    )


def evaluate(
    data_path: str | Path,
    model_path: str | Path,
    output_path: str | Path,
    *,
    minimum_savings: float = 8.0,
    max_decisions: int | None = 10_000,
) -> dict[str, object]:
    path = Path(data_path)
    raw = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    daily = prepare_daily_market(raw)
    bundle = joblib.load(model_path)
    validation, validation_period = simulate_backtest(
        daily,
        bundle,
        minimum_savings=minimum_savings,
        period_start_fraction=0.70,
        period_end_fraction=0.85,
        max_decisions=max_decisions,
    )
    selected_threshold, threshold_search = tune_policy_threshold(validation)
    decisions, test_period = simulate_backtest(
        daily,
        bundle,
        minimum_savings=minimum_savings,
        period_start_fraction=0.85,
        period_end_fraction=1.0,
        max_decisions=max_decisions,
    )
    decisions = apply_model_threshold(decisions, selected_threshold)
    model_wait_rate = float(decisions["model_action"].eq("WAIT").mean())
    random_wait = decisions["decision_id"].map(_stable_uniform).lt(model_wait_rate)
    decisions["random_action"] = np.where(random_wait, "WAIT", "BUY")
    decisions["random_savings"] = np.where(
        random_wait, decisions["always_wait_savings"], 0.0
    )
    results: dict[str, object] = {
        "evaluation": {
            "data_path": str(path),
            "model_path": str(model_path),
            "validation_period": validation_period,
            "test_period": test_period,
            "decision_days": list(DECISION_DAYS),
            "minimum_meaningful_savings": minimum_savings,
            "selected_predicted_savings_threshold": selected_threshold,
            "validation_threshold_search": threshold_search,
            "daily_market_rows": len(daily),
            "booking_decisions": len(decisions),
        },
        "decision_accuracy": float(
            decisions["model_action"].eq(decisions["actual_best_action"]).mean()
        ),
        "policies": {
            "model": asdict(summarize_policy(decisions, "model_savings", "model_action")),
            "always_buy": asdict(
                summarize_policy(decisions, "always_buy_savings", "always_buy_action")
            ),
            "always_wait": asdict(
                summarize_policy(decisions, "always_wait_savings", "always_wait_action")
            ),
            "trailing_median_heuristic": asdict(
                summarize_policy(decisions, "heuristic_savings", "heuristic_action")
            ),
            "random": asdict(
                summarize_policy(decisions, "random_savings", "random_action")
            ),
            "oracle_reference": asdict(
                summarize_policy(decisions, "oracle_savings", "actual_best_action")
            ),
        },
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    decisions.to_csv(output.with_name("backtest_decisions.csv"), index=False)
    return results
