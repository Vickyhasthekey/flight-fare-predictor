import json
import os
import unittest
from io import BytesIO
from datetime import date, timedelta
from unittest import mock

from src.serp_flights import compact_flights, search_one_way, set_fetch
import api.flights as flights_api
from src.recommend import SUPPORTED_AIRPORTS


SERP_PAYLOAD = {
    "best_flights": [
        {
            "flights": [
                {
                    "departure_airport": {
                        "name": "Hartsfield-Jackson Atlanta International Airport",
                        "id": "ATL",
                        "time": "2026-09-15 07:15",
                    },
                    "arrival_airport": {
                        "name": "Los Angeles International Airport",
                        "id": "LAX",
                        "time": "2026-09-15 09:20",
                    },
                    "duration": 305,
                    "airline": "Delta",
                    "airline_logo": "https://example.com/dl.png",
                    "flight_number": "DL 421",
                }
            ],
            "total_duration": 305,
            "price": 312,
            "type": "One way",
            "airline_logo": "https://example.com/dl.png",
        }
    ],
    "other_flights": [
        {
            "flights": [
                {
                    "departure_airport": {
                        "id": "ATL",
                        "time": "2026-09-15 11:00",
                    },
                    "arrival_airport": {
                        "id": "DFW",
                        "time": "2026-09-15 12:30",
                    },
                    "duration": 90,
                    "airline": "American",
                    "airline_logo": "https://example.com/aa.png",
                    "flight_number": "AA 100",
                },
                {
                    "departure_airport": {
                        "id": "DFW",
                        "time": "2026-09-15 14:00",
                    },
                    "arrival_airport": {
                        "id": "LAX",
                        "time": "2026-09-15 15:20",
                    },
                    "duration": 80,
                    "airline": "American",
                    "flight_number": "AA 200",
                },
            ],
            "layovers": [{"duration": 90, "name": "Dallas", "id": "DFW"}],
            "total_duration": 260,
            "price": 198,
        },
        {
            "flights": [
                {
                    "departure_airport": {"id": "ATL", "time": "2026-09-15 06:00"},
                    "arrival_airport": {"id": "LAX", "time": "2026-09-15 08:00"},
                    "airline": "Frontier",
                    "flight_number": "F9 1",
                }
            ],
            "total_duration": 240,
            "price": None,
        },
        {
            "flights": [
                {
                    "departure_airport": {
                        "id": "ATL",
                        "time": "2026-09-15 07:15",
                    },
                    "arrival_airport": {
                        "id": "LAX",
                        "time": "2026-09-15 09:20",
                    },
                    "airline": "Delta",
                    "flight_number": "DL 421",
                }
            ],
            "total_duration": 305,
            "price": 312,
        },
    ],
}


class CompactFlightsTests(unittest.TestCase):
    def test_keeps_priced_itineraries_and_drops_unpriced(self):
        rows = compact_flights(SERP_PAYLOAD)
        prices = [r["price"] for r in rows]
        self.assertEqual(prices, [312.0, 198.0])

    def test_nonstop_uses_first_leg_airline_and_zero_stops(self):
        rows = compact_flights(SERP_PAYLOAD)
        delta = rows[0]
        self.assertEqual(delta["airline"], "Delta")
        self.assertEqual(delta["airline_code"], "DL")
        self.assertEqual(delta["flight_numbers"], ["DL 421"])
        self.assertEqual(delta["depart_time"], "07:15")
        self.assertEqual(delta["arrive_time"], "09:20")
        self.assertEqual(delta["duration_min"], 305)
        self.assertEqual(delta["stops"], 0)
        self.assertEqual(delta["stop_airports"], [])
        self.assertEqual(delta["price"], 312.0)

    def test_connecting_counts_stops_and_layover_airports(self):
        rows = compact_flights(SERP_PAYLOAD)
        aa = rows[1]
        self.assertEqual(aa["airline"], "American")
        self.assertEqual(aa["flight_numbers"], ["AA 100", "AA 200"])
        self.assertEqual(aa["stops"], 1)
        self.assertEqual(aa["stop_airports"], ["DFW"])
        self.assertEqual(aa["depart_time"], "11:00")
        self.assertEqual(aa["arrive_time"], "15:20")

    def test_dedupes_same_flight_numbers_time_and_price(self):
        rows = compact_flights(SERP_PAYLOAD)
        keys = [(tuple(r["flight_numbers"]), r["depart_time"], r["price"]) for r in rows]
        self.assertEqual(len(keys), len(set(keys)))


class SearchOneWayTests(unittest.TestCase):
    def tearDown(self):
        set_fetch(None)

    def test_calls_google_flights_once_with_show_hidden(self):
        urls = []

        def fake_fetch(url):
            urls.append(url)
            return SERP_PAYLOAD

        set_fetch(fake_fetch)
        rows = search_one_way("ATL", "LAX", date(2026, 9, 15), api_key="test-key")
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(urls), 1)
        url = urls[0]
        self.assertIn("engine=google_flights", url)
        self.assertIn("type=2", url)
        self.assertIn("show_hidden=true", url)
        self.assertIn("departure_id=ATL", url)
        self.assertIn("arrival_id=LAX", url)
        self.assertIn("outbound_date=2026-09-15", url)
        self.assertIn("api_key=test-key", url)
        self.assertNotIn("deep_search", url)

    def test_raises_when_serpapi_returns_error(self):
        set_fetch(lambda url: {"error": "Invalid API key"})
        with self.assertRaises(RuntimeError) as ctx:
            search_one_way("ATL", "LAX", date(2026, 9, 15), api_key="bad")
        self.assertIn("Invalid API key", str(ctx.exception))


def _post_flights(body):
    raw = json.dumps(body).encode()
    captured = {}

    def start_response(status, headers):
        captured["status"] = status

    environ = {
        "REQUEST_METHOD": "POST",
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": BytesIO(raw),
    }
    payload = b"".join(flights_api.handler(environ, start_response))
    return captured["status"], json.loads(payload)


class FlightsApiTests(unittest.TestCase):
    def setUp(self):
        self.flight = (date.today() + timedelta(days=21)).isoformat()
        set_fetch(lambda url: SERP_PAYLOAD)

    def tearDown(self):
        set_fetch(None)

    def test_returns_compact_flights_and_fetched_at(self):
        with mock.patch.dict(os.environ, {"SERPAPI_API_KEY": "test-key"}):
            status, data = _post_flights({
                "origin": "ATL",
                "destination": "LAX",
                "flightDate": self.flight,
            })
        self.assertTrue(status.startswith("200"))
        self.assertEqual(len(data["flights"]), 2)
        self.assertIn("fetched_at", data)
        self.assertEqual(data["flights"][0]["airline"], "Delta")
        self.assertNotIn("best_flights", data)

    def test_same_airport_is_a_bad_request(self):
        with mock.patch.dict(os.environ, {"SERPAPI_API_KEY": "test-key"}):
            status, data = _post_flights({
                "origin": "BOS",
                "destination": "BOS",
                "flightDate": self.flight,
            })
        self.assertTrue(status.startswith("400"))
        self.assertIn("different airports", data["message"])

    def test_missing_api_key_is_service_unavailable(self):
        env = {k: v for k, v in os.environ.items() if k != "SERPAPI_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True):
            status, data = _post_flights({
                "origin": "ATL",
                "destination": "LAX",
                "flightDate": self.flight,
            })
        self.assertTrue(status.startswith("503"))
        self.assertIn("SERPAPI", data["message"].upper())

    def test_predict_lookup_flights_uses_the_same_handler(self):
        with mock.patch.dict(os.environ, {"SERPAPI_API_KEY": "test-key"}):
            raw = json.dumps({
                "lookup": "flights",
                "origin": "ATL",
                "destination": "LAX",
                "flightDate": self.flight,
            }).encode()
            captured = {}

            def start_response(status, headers):
                captured["status"] = status

            import api.predict as predict_api
            environ = {
                "REQUEST_METHOD": "POST",
                "CONTENT_LENGTH": str(len(raw)),
                "wsgi.input": BytesIO(raw),
            }
            payload = b"".join(predict_api.handler(environ, start_response))
            data = json.loads(payload)
        self.assertTrue(captured["status"].startswith("200"))
        self.assertEqual(data["status"], "ok")
        self.assertEqual(len(data["flights"]), 2)

    def test_predict_query_string_lookup_flights(self):
        with mock.patch.dict(os.environ, {"SERPAPI_API_KEY": "test-key"}):
            raw = json.dumps({
                "origin": "ATL",
                "destination": "LAX",
                "flightDate": self.flight,
            }).encode()
            captured = {}

            def start_response(status, headers):
                captured["status"] = status

            import api.predict as predict_api
            environ = {
                "REQUEST_METHOD": "POST",
                "CONTENT_LENGTH": str(len(raw)),
                "QUERY_STRING": "lookup=flights",
                "wsgi.input": BytesIO(raw),
            }
            payload = b"".join(predict_api.handler(environ, start_response))
            data = json.loads(payload)
        self.assertTrue(captured["status"].startswith("200"))
        self.assertEqual(data["status"], "ok")
        self.assertEqual(len(data["flights"]), 2)

    def test_unsupported_airport_is_rejected(self):
        mystery = "XXX"
        self.assertNotIn(mystery, SUPPORTED_AIRPORTS)
        with mock.patch.dict(os.environ, {"SERPAPI_API_KEY": "test-key"}):
            status, data = _post_flights({
                "origin": "ATL",
                "destination": mystery,
                "flightDate": self.flight,
            })
        self.assertTrue(status.startswith("400"))
        self.assertIn("supported", data["message"].lower())


if __name__ == "__main__":
    unittest.main()
