import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.recommend import recommend_purchase_timing  # noqa: E402

VALID_AIRPORT_LEN = 3

_STATUS_LINES = {
    200: "200 OK",
    400: "400 Bad Request",
    405: "405 Method Not Allowed",
    500: "500 Internal Server Error",
}


def handler(environ, start_response):
    """WSGI entrypoint (declared in pyproject.toml) for POST /api/predict."""
    if environ.get("REQUEST_METHOD") != "POST":
        return _respond(start_response, 405, {"status": "error", "message": "Method not allowed"})

    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
        raw_body = environ["wsgi.input"].read(length) if length else b"{}"
        body = json.loads(raw_body or b"{}")

        origin = str(body.get("origin", "")).strip().upper()
        destination = str(body.get("destination", "")).strip().upper()
        flight_date_str = str(body.get("flightDate", "")).strip()

        if len(origin) != VALID_AIRPORT_LEN or len(destination) != VALID_AIRPORT_LEN:
            return _respond(start_response, 400,
                             {"status": "error", "message": "Enter valid 3-letter airport codes."})
        try:
            flight_date = date.fromisoformat(flight_date_str)
        except ValueError:
            return _respond(start_response, 400, {"status": "error", "message": "Enter a valid flight date."})

        result = recommend_purchase_timing(origin, destination, flight_date)
        return _respond(start_response, 200, result)
    except Exception as e:
        return _respond(start_response, 500, {"status": "error", "message": f"Server error: {e}"})


def _respond(start_response, code, payload):
    body = json.dumps(payload).encode()
    headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
    start_response(_STATUS_LINES[code], headers)
    return [body]
