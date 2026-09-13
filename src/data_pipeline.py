"""Out-of-core DuckDB data preparation for the 82M-row Expedia dataset."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

REQUIRED_COLUMNS = {
    "searchDate",
    "flightDate",
    "startingAirport",
    "destinationAirport",
    "totalFare",
    "isNonStop",
    "seatsRemaining",
    "totalTravelDistance",
    "isBasicEconomy",
}


def _quote(path: str | Path) -> str:
    return str(Path(path).resolve()).replace("'", "''")


def validate_schema(input_path: str | Path) -> list[str]:
    con = duckdb.connect()
    description = con.execute(
        f"DESCRIBE SELECT * FROM read_csv_auto('{_quote(input_path)}', sample_size=100000)"
    ).fetchdf()
    columns = set(description["column_name"].astype(str))
    missing = sorted(REQUIRED_COLUMNS - columns)
    if missing:
        raise ValueError(f"Raw dataset is missing required columns: {', '.join(missing)}")
    return sorted(columns)


def clean_raw_csv(
    input_path: str | Path,
    output_path: str | Path,
    *,
    profile_path: str | Path | None = None,
) -> dict[str, object]:
    """Stream the large CSV through DuckDB and write a typed, compressed Parquet table."""
    validate_schema(input_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    source = _quote(input_path)
    destination = _quote(output)
    raw_relation = f"read_csv_auto('{source}', header=true, sample_size=100000)"
    counts = con.execute(
        f"""
        SELECT
            COUNT(*) AS input_rows,
            COUNT(*) FILTER (
                WHERE totalFare IS NULL OR totalFare <= 20 OR totalFare >= 5000
            ) AS invalid_fares,
            COUNT(*) FILTER (
                WHERE searchDate IS NULL OR flightDate IS NULL OR flightDate <= searchDate
            ) AS invalid_dates,
            COUNT(*) FILTER (WHERE seatsRemaining < 0) AS invalid_seats,
            COUNT(*) FILTER (WHERE totalTravelDistance IS NULL) AS missing_distance
        FROM {raw_relation}
        """
    ).fetchone()

    con.execute(
        f"""
        COPY (
            SELECT
                CAST(searchDate AS DATE) AS searchDate,
                CAST(flightDate AS DATE) AS flightDate,
                UPPER(startingAirport) AS startingAirport,
                UPPER(destinationAirport) AS destinationAirport,
                CAST(totalFare AS DOUBLE) AS totalFare,
                CAST(isNonStop AS BOOLEAN) AS isNonStop,
                CAST(seatsRemaining AS INTEGER) AS seatsRemaining,
                COALESCE(
                    CAST(totalTravelDistance AS DOUBLE),
                    MEDIAN(CAST(totalTravelDistance AS DOUBLE)) OVER (
                        PARTITION BY startingAirport, destinationAirport
                    )
                ) AS totalTravelDistance,
                CAST(isBasicEconomy AS BOOLEAN) AS isBasicEconomy,
                date_diff('day', CAST(searchDate AS DATE), CAST(flightDate AS DATE))
                    AS days_before_departure,
                dayofweek(CAST(flightDate AS DATE)) AS departure_day_of_week,
                month(CAST(flightDate AS DATE)) AS departure_month,
                dayofweek(CAST(searchDate AS DATE)) AS search_day_of_week
            FROM {raw_relation}
            WHERE totalFare > 20 AND totalFare < 5000
              AND flightDate > searchDate
              AND (seatsRemaining IS NULL OR seatsRemaining >= 0)
        ) TO '{destination}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    accepted = con.execute(f"SELECT COUNT(*) FROM read_parquet('{destination}')").fetchone()[0]
    profile: dict[str, object] = {
        "source": str(Path(input_path).resolve()),
        "output": str(output.resolve()),
        "input_rows": int(counts[0]),
        "accepted_rows": int(accepted),
        "rejected_rows": int(counts[0] - accepted),
        "invalid_fares": int(counts[1]),
        "invalid_dates": int(counts[2]),
        "invalid_seats": int(counts[3]),
        "missing_distance_imputed": int(counts[4]),
    }
    profile_output = Path(profile_path) if profile_path else output.with_suffix(".profile.json")
    profile_output.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return profile


def build_daily_training_table(
    input_path: str | Path,
    output_path: str | Path,
) -> dict[str, object]:
    """Create one cheapest quote per route, flight date, lead day, and stop market."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    source = _quote(input_path)
    destination = _quote(output)
    con.execute(
        f"""
        COPY (
            SELECT
                startingAirport,
                destinationAirport,
                flightDate,
                days_before_departure,
                departure_day_of_week,
                departure_month,
                search_day_of_week,
                isNonStop,
                MEDIAN(totalTravelDistance) AS totalTravelDistance,
                MIN(totalFare) AS best_fare,
                COUNT(*) AS offers_observed
            FROM read_parquet('{source}')
            GROUP BY ALL
        ) TO '{destination}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    row = con.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT startingAirport || '-' || destinationAirport),
               MIN(flightDate - CAST(days_before_departure AS INTEGER)),
               MAX(flightDate - CAST(days_before_departure AS INTEGER))
        FROM read_parquet('{destination}')
        """
    ).fetchone()
    return {
        "rows": int(row[0]),
        "routes": int(row[1]),
        "search_date_min": str(row[2]),
        "search_date_max": str(row[3]),
        "output": str(output.resolve()),
    }
