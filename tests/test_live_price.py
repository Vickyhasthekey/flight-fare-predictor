import unittest
from datetime import date

from src.live_price import (
    fare_from_google_html,
    fare_from_kayak_html,
    lookup_live_min_fare,
    parse_cheapest_one_way_headline,
    parse_kayak_one_way_deals,
    set_fetch,
)


KAYAK_SNIPPET = '''
<div>Cheapest one-way</div></div><div class="c_nzd-price">$115</div>
<div class="c_nzd-price-range">Typical prices: $131-$295</div>
{"title":"Cheapest flight","dataText":"$115","type":"cheapestResult"}
"cheapestPopularOneWayFlight":{"deals":[
{"providerName":"Frontier","price":{"price":115,"currency":"USD","localizedPrice":"$115"},
 "pickupDateIso":"2026-10-03","leg1Stops":2},
{"providerName":"JetBlue","price":{"price":117,"currency":"USD","localizedPrice":"$117"},
 "pickupDateIso":"2026-09-12","leg1Stops":1},
{"providerName":"Frontier","price":{"price":116,"currency":"USD","localizedPrice":"$116"},
 "pickupDateIso":"2026-09-19","leg1Stops":2}
]},"cheapestPopularDirectFlight":{"deals":[
{"providerName":"Frontier","price":{"price":215,"currency":"USD"},
 "pickupDateIso":"2026-09-23","leg1Stops":0}
]}
'''

GOOGLE_SNIPPET = '''
<table><tr><th>Cheapest one-way flight</th>
<td class="D5ftLd QORQHb">$99</td></tr></table>
'''


class LivePriceParseTests(unittest.TestCase):
    def test_parses_kayak_one_way_deals_and_skips_round_trip_block(self):
        deals = parse_kayak_one_way_deals(KAYAK_SNIPPET)
        self.assertEqual(len(deals), 3)
        self.assertEqual(deals[0]["price"], 115.0)
        self.assertEqual(deals[0]["date"], "2026-10-03")
        self.assertNotIn(215.0, [d["price"] for d in deals])

    def test_headline_cheapest_one_way(self):
        self.assertEqual(parse_cheapest_one_way_headline(KAYAK_SNIPPET), 115.0)
        self.assertEqual(parse_cheapest_one_way_headline(GOOGLE_SNIPPET), 99.0)

    def test_exact_flight_date_wins(self):
        hit = fare_from_kayak_html(KAYAK_SNIPPET, flight_date=date(2026, 9, 12))
        self.assertEqual(hit["price"], 117.0)
        self.assertEqual(hit["match"], "exact")
        self.assertEqual(hit["matched_date"], "2026-09-12")

    def test_nearby_date_when_exact_is_missing(self):
        hit = fare_from_kayak_html(KAYAK_SNIPPET, flight_date=date(2026, 9, 16))
        self.assertEqual(hit["match"], "nearby")
        self.assertEqual(hit["matched_date"], "2026-09-19")
        self.assertEqual(hit["price"], 116.0)

    def test_route_lowest_when_date_is_far_from_listed_deals(self):
        hit = fare_from_kayak_html(KAYAK_SNIPPET, flight_date=date(2026, 11, 20))
        self.assertEqual(hit["match"], "route_lowest")
        self.assertEqual(hit["price"], 115.0)

    def test_google_city_pair_cheapest_one_way(self):
        hit = fare_from_google_html(GOOGLE_SNIPPET)
        self.assertEqual(hit["price"], 99.0)
        self.assertEqual(hit["source"], "google")


class LivePriceLookupTests(unittest.TestCase):
    def tearDown(self):
        set_fetch(None)

    def test_lookup_uses_kayak_html_and_does_not_hit_google(self):
        urls = []

        def fake_fetch(url):
            urls.append(url)
            if "kayak.com" in url:
                return KAYAK_SNIPPET
            raise AssertionError(f"unexpected fetch {url}")

        set_fetch(fake_fetch)
        hit = lookup_live_min_fare("ATL", "BOS", flight_date=date(2026, 9, 12))
        self.assertEqual(hit["price"], 117.0)
        self.assertEqual(hit["source"], "kayak")
        self.assertIn("Kayak", hit["label"])
        self.assertTrue(all("kayak.com" in u for u in urls))

    def test_lookup_falls_back_to_google_when_kayak_has_no_fare(self):
        def fake_fetch(url):
            if "kayak.com" in url:
                return "<html>no prices here</html>"
            if "google.com" in url:
                return GOOGLE_SNIPPET
            raise AssertionError(url)

        set_fetch(fake_fetch)
        hit = lookup_live_min_fare("ATL", "BOS", flight_date=date(2026, 9, 30))
        self.assertEqual(hit["price"], 99.0)
        self.assertEqual(hit["source"], "google")

    def test_lookup_returns_none_when_both_sources_fail(self):
        set_fetch(lambda url: "<html></html>")
        self.assertIsNone(lookup_live_min_fare("ATL", "BOS"))


if __name__ == "__main__":
    unittest.main()
