from __future__ import annotations

import json
import os
import sys
import urllib.parse
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel, Field, model_validator  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402

from src.recommend import (  # noqa: E402
    SUPPORTED_AIRPORTS,
    normalize_stops,
    recommend_purchase_timing,
)

VALID_AIRPORT_LEN = 3

app = FastAPI(
    title="FareSignal API",
    version="0.1.0",
    description="Flight-fare curves and BUY/WAIT purchase recommendations.",
)


class PredictRequest(BaseModel):
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    flightDate: date
    currentPrice: float | None = Field(default=None, gt=0)
    stops: str = "all"

    @model_validator(mode="after")
    def validate_route(self) -> PredictRequest:
        self.origin = self.origin.strip().upper()
        self.destination = self.destination.strip().upper()
        if self.origin == self.destination:
            raise ValueError("Origin and destination must be different airports.")
        if self.origin not in SUPPORTED_AIRPORTS or self.destination not in SUPPORTED_AIRPORTS:
            raise ValueError("Pick both airports from the supported list.")
        normalize_stops(stops=self.stops)
        return self


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": "ready" if Path("models/price_model.joblib").exists() else "missing",
        "version": "0.1.0",
    }


@app.post("/api/predict")
def predict(request: PredictRequest):
    result = recommend_purchase_timing(
        request.origin,
        request.destination,
        request.flightDate,
        current_price=request.currentPrice,
        stops=request.stops,
        lookup_live=request.currentPrice is None,
    )
    if result.get("status") in {"error", "too_far"}:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@app.get("/api/backtest/results")
def backtest_results():
    path = Path("artifacts/backtest_results.json")
    if not path.exists():
        raise HTTPException(status_code=503, detail="Backtest results have not been generated.")
    return json.loads(path.read_text(encoding="utf-8"))


# Mount after API routes so one local server can host both the application and REST endpoints.
if Path("public").exists():
    app.mount("/", StaticFiles(directory="public", html=True), name="public")

_STATUS_LINES = {
    200: "200 OK",
    400: "400 Bad Request",
    405: "405 Method Not Allowed",
    500: "500 Internal Server Error",
    502: "502 Bad Gateway",
    503: "503 Service Unavailable",
}


def handler(environ, start_response):
    """WSGI entrypoint (declared in pyproject.toml) for POST /api/predict."""
    if environ.get("REQUEST_METHOD") != "POST":
        return _respond(start_response, 405, {"status": "error", "message": "Method not allowed"})

    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
        raw_body = environ["wsgi.input"].read(length) if length else b"{}"
        body = json.loads(raw_body or b"{}")
        query = urllib.parse.parse_qs(environ.get("QUERY_STRING") or "")
        lookup = str(body.get("lookup") or (query.get("lookup") or [""])[0]).strip().lower()
        if lookup == "flights":
            from api.flights import handle_request
            code, payload = handle_request(body)
            return _respond(start_response, code, payload)

        origin = str(body.get("origin", "")).strip().upper()
        destination = str(body.get("destination", "")).strip().upper()
        flight_date_str = str(body.get("flightDate", "")).strip()
        try:
            stops = normalize_stops(
                stops=body.get("stops"),
                nonstop_only=body.get("nonstopOnly"),
            )
        except ValueError:
            return _respond(start_response, 400, {
                "status": "error", "message": "Stops must be ALL, non-stop, or stop.",
            })
        current_price = body.get("currentPrice", None)
        if current_price == "" or current_price is None:
            current_price = None
        else:
            try:
                current_price = float(current_price)
            except (TypeError, ValueError):
                return _respond(start_response, 400, {
                    "status": "error", "message": "Current price must be a number.",
                })
            if current_price <= 0:
                return _respond(start_response, 400, {
                    "status": "error", "message": "Current price must be greater than 0.",
                })

        if len(origin) != VALID_AIRPORT_LEN or len(destination) != VALID_AIRPORT_LEN:
            return _respond(start_response, 400,
                             {"status": "error", "message": "Enter valid 3-letter airport codes."})
        if origin == destination:
            return _respond(start_response, 400, {
                "status": "error",
                "message": "Origin and destination must be different airports.",
            })
        if origin not in SUPPORTED_AIRPORTS or destination not in SUPPORTED_AIRPORTS:
            return _respond(start_response, 400, {
                "status": "error",
                "message": "Pick both airports from the supported list.",
            })
        try:
            flight_date = date.fromisoformat(flight_date_str)
        except ValueError:
            return _respond(start_response, 400, {"status": "error", "message": "Enter a valid flight date."})

        result = recommend_purchase_timing(
            origin, destination, flight_date,
            current_price=current_price, stops=stops,
            lookup_live=current_price is None,
        )
        return _respond(start_response, 200, result)
    except Exception as e:
        return _respond(start_response, 500, {"status": "error", "message": f"Server error: {e}"})


def _respond(start_response, code, payload):
    body = json.dumps(payload).encode()
    headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
    start_response(_STATUS_LINES[code], headers)
    return [body]
