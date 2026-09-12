import json
import unittest
from io import BytesIO
from datetime import date, timedelta

import api.predict as predict_api
import src.recommend as recommend
from tests.test_recommend import _bundle


def _post(body):
    raw = json.dumps(body).encode()
    captured = {}

    def start_response(status, headers):
        captured["status"] = status

    environ = {
        "REQUEST_METHOD": "POST",
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": BytesIO(raw),
    }
    payload = b"".join(predict_api.handler(environ, start_response))
    return captured["status"], json.loads(payload)


class PredictApiTests(unittest.TestCase):
    def setUp(self):
        recommend.set_bundle(_bundle())
        self.flight = (date.today() + timedelta(days=21)).isoformat()

    def tearDown(self):
        recommend.set_bundle(None)

    def test_same_airport_is_a_bad_request(self):
        status, data = _post({
            "origin": "BOS",
            "destination": "BOS",
            "flightDate": self.flight,
            "currentPrice": 200,
            "stops": "all",
        })
        self.assertTrue(status.startswith("400"))
        self.assertEqual(data["status"], "error")
        self.assertIn("different airports", data["message"])

    def test_supported_route_is_ok(self):
        status, data = _post({
            "origin": "ATL",
            "destination": "LAX",
            "flightDate": self.flight,
            "currentPrice": 200,
            "stops": "all",
        })
        self.assertTrue(status.startswith("200"))
        self.assertIn(data["status"], {"buy_now", "wait"})


if __name__ == "__main__":
    unittest.main()
