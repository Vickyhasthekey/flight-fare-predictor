import json
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.recommend import MAX_DAYS, SUPPORTED_AIRPORTS  # noqa: E402
from src.serp_flights import search_one_way  # noqa: E402

VALID_AIRPORT_LEN = 3

_STATUS_LINES = {
    200: "200 OK",
    400: "400 Bad Request",
    405: "405 Method Not Allowed",
    500: "500 Internal Server Error",
    502: "502 Bad Gateway",
    503: "503 Service Unavailable",
}


def handle_request(body):
    origin = str(body.get("origin", "")).strip().upper()
    destination = str(body.get("destination", "")).strip().upper()
    flight_date_str = str(body.get("flightDate", "")).strip()

    if len(origin) != VALID_AIRPORT_LEN or len(destination) != VALID_AIRPORT_LEN:
        return 400, {"status": "error", "message": "Enter valid 3-letter airport codes."}
    if origin == destination:
        return 400, {
            "status": "error",
            "message": "Origin and destination must be different airports.",
        }
    if origin not in SUPPORTED_AIRPORTS or destination not in SUPPORTED_AIRPORTS:
        return 400, {
            "status": "error",
            "message": "Pick both airports from the supported list.",
        }
    try:
        flight_date = date.fromisoformat(flight_date_str)
    except ValueError:
        return 400, {"status": "error", "message": "Enter a valid flight date."}

    days_left = (flight_date - date.today()).days
    if days_left <= 0:
        return 400, {"status": "error", "message": "Flight date must be in the future."}
    if days_left > MAX_DAYS:
        return 400, {
            "status": "error",
            "message": (
                f"Flight is {days_left} days out — this tool only covers "
                f"up to {MAX_DAYS} days before departure."
            ),
        }

    if not os.environ.get("SERPAPI_API_KEY"):
        return 503, {
            "status": "error",
            "message": "Flight search is not configured. Set SERPAPI_API_KEY.",
        }

    try:
        flights = search_one_way(origin, destination, flight_date)
    except RuntimeError as exc:
        return 502, {
            "status": "error",
            "message": "Could not look up flights. Please try again.",
            "detail": str(exc)[:200],
        }

    return 200, {
        "status": "ok",
        "origin": origin,
        "destination": destination,
        "flightDate": flight_date.isoformat(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "flights": flights,
    }


def handler(environ, start_response):
    """WSGI entrypoint for POST /api/flights."""
    if environ.get("REQUEST_METHOD") != "POST":
        return _respond(start_response, 405, {"status": "error", "message": "Method not allowed"})

    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
        raw_body = environ["wsgi.input"].read(length) if length else b"{}"
        body = json.loads(raw_body or b"{}")
        code, payload = handle_request(body)
        return _respond(start_response, code, payload)
    except Exception as exc:
        return _respond(start_response, 500, {
            "status": "error", "message": f"Server error: {exc}",
        })


def _respond(start_response, code, payload):
    body = json.dumps(payload).encode()
    headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
    start_response(_STATUS_LINES.get(code, f"{code} Error"), headers)
    return [body]
