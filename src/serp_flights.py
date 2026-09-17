"""Compact one-way itineraries from SerpAPI Google Flights.

We keep only the fields the picker cards need. The raw SerpAPI payload is
never written to disk; the browser may cache this compact list for 24 hours.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

SERPAPI_URL = "https://serpapi.com/search.json"
FETCH_TIMEOUT = 25
MIN_FARE = 20.0
MAX_FARE = 5000.0

_fetch_fn = None


def set_fetch(fn):
    """Tests inject a fake HTTP getter so we don't spend SerpAPI credits."""
    global _fetch_fn
    _fetch_fn = fn


def _hhmm(raw):
    if not raw:
        return None
    parts = str(raw).strip().split()
    if len(parts) >= 2:
        return parts[1][:5]
    if ":" in parts[0] and len(parts[0]) >= 4:
        return parts[0][:5]
    return None


def _airline_code(flight_number):
    raw = (flight_number or "").replace(" ", "").upper()
    if len(raw) >= 2 and raw[0].isalnum() and raw[1].isalnum():
        return raw[:2]
    return None


def _price(value):
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if MIN_FARE <= price <= MAX_FARE:
        return round(price, 2)
    return None


def compact_itinerary(item, idx):
    legs = item.get("flights") or []
    if not legs:
        return None
    price = _price(item.get("price"))
    if price is None:
        return None
    first, last = legs[0], legs[-1]
    numbers = []
    for leg in legs:
        fn = (leg.get("flight_number") or "").strip()
        if fn:
            numbers.append(fn)
    layovers = item.get("layovers") or []
    stop_airports = [row.get("id") for row in layovers if row.get("id")]
    stops = max(len(legs) - 1, len(layovers))
    duration = item.get("total_duration")
    if not duration:
        duration = sum(int(leg.get("duration") or 0) for leg in legs)
    airline = first.get("airline") or item.get("airline")
    logo = first.get("airline_logo") or item.get("airline_logo")
    return {
        "id": str(idx),
        "airline": airline,
        "airline_code": _airline_code(numbers[0]) if numbers else None,
        "airline_logo": logo,
        "flight_numbers": numbers,
        "depart_time": _hhmm((first.get("departure_airport") or {}).get("time")),
        "arrive_time": _hhmm((last.get("arrival_airport") or {}).get("time")),
        "duration_min": int(duration) if duration else None,
        "stops": int(stops),
        "stop_airports": stop_airports,
        "price": price,
    }


def compact_flights(payload):
    items = list(payload.get("best_flights") or []) + list(payload.get("other_flights") or [])
    out = []
    seen = set()
    for item in items:
        row = compact_itinerary(item, len(out))
        if not row:
            continue
        key = (tuple(row["flight_numbers"]), row["depart_time"], row["price"])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _fetch_json(url):
    if _fetch_fn is not None:
        return _fetch_fn(url)
    req = urllib.request.Request(url, headers={"User-Agent": "flightFarePredic/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"SerpAPI HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach SerpAPI: {exc.reason}") from exc


def search_one_way(origin, destination, flight_date, api_key=None):
    origin = str(origin).strip().upper()
    destination = str(destination).strip().upper()
    if isinstance(flight_date, date):
        outbound = flight_date.isoformat()
    else:
        outbound = str(flight_date)
    key = api_key or os.environ.get("SERPAPI_API_KEY")
    if not key:
        raise RuntimeError("Missing SERPAPI_API_KEY")
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": outbound,
        "type": 2,
        "currency": "USD",
        "hl": "en",
        "gl": "us",
        "show_hidden": "true",
        "api_key": key,
    }
    url = SERPAPI_URL + "?" + urllib.parse.urlencode(params)
    payload = _fetch_json(url)
    if not isinstance(payload, dict):
        raise RuntimeError("SerpAPI returned an unexpected payload")
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    return compact_flights(payload)
