"""Look up a published one-way fare and use it as today's pin for the curve.

Kayak's public route pages list recent one-way deals (price + date). Google's
city-pair pages list a cheapest one-way. Neither is a live GDS quote for every
date; we never invent a fare with an LLM.
"""
from __future__ import annotations

import re
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
from datetime import date, datetime

MIN_FARE = 35.0
MAX_FARE = 1500.0
NEARBY_DAYS = 10
FETCH_TIMEOUT = 8

KAYAK_ROUTE_URL = "https://www.kayak.com/flight-routes/{origin}/{destination}"
GOOGLE_PAIR_URL = (
    "https://www.google.com/travel/flights/flights-from-{origin}-to-{destination}.html"
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Google SEO pages are city-to-city, not airport-to-airport.
CITY_SLUG = {
    "ATL": "atlanta",
    "BOS": "boston",
    "CLT": "charlotte",
    "DEN": "denver",
    "DFW": "dallas",
    "DTW": "detroit",
    "EWR": "newark",
    "IAD": "washington",
    "JFK": "new-york",
    "LGA": "new-york",
    "LAX": "los-angeles",
    "MIA": "miami",
    "OAK": "oakland",
    "ORD": "chicago",
    "PHL": "philadelphia",
    "SFO": "san-francisco",
}

_fetch_fn = None


def set_fetch(fn):
    """Tests inject a fake HTTP getter so we don't hit the network."""
    global _fetch_fn
    _fetch_fn = fn


def _in_range(price):
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if MIN_FARE <= value <= MAX_FARE:
        return value
    return None


def _parse_money(text):
    if text is None:
        return None
    cleaned = str(text).replace(",", "").replace("$", "").strip()
    return _in_range(cleaned)


def parse_kayak_one_way_deals(html):
    """Recent one-way deals from Kayak's route SEO payload."""
    match = re.search(r'"cheapestPopularOneWayFlight"\s*:\s*\{', html)
    if not match:
        return []
    blob = html[match.start(): match.start() + 80_000]
    next_block = re.search(r'"cheapestPopular(?:Direct|RoundTrip|LastMinute)', blob[80:])
    if next_block:
        blob = blob[: next_block.start() + 80]

    deals = []
    for part in blob.split('"providerName":')[1:]:
        price_m = re.search(r'"price"\s*:\s*\{\s*"price"\s*:\s*(\d+)', part)
        date_m = re.search(r'"pickupDateIso"\s*:\s*"(\d{4}-\d{2}-\d{2})"', part)
        stops_m = re.search(r'"leg1Stops"\s*:\s*(\d+)', part)
        carrier_m = re.match(r'"([^"]+)"', part)
        if not price_m or not date_m:
            continue
        price = _parse_money(price_m.group(1))
        if price is None:
            continue
        deals.append({
            "price": price,
            "date": date_m.group(1),
            "stops": int(stops_m.group(1)) if stops_m else None,
            "carrier": carrier_m.group(1) if carrier_m else None,
        })
        if len(deals) >= 20:
            break
    return deals


def parse_cheapest_one_way_headline(html):
    patterns = [
        r"Cheapest one-way.{0,200}?\$([0-9][0-9,]{1,4})",
        r'"title"\s*:\s*"Cheapest flight"\s*,\s*"dataText"\s*:\s*"\$([0-9,]+)"',
        r"Cheapest one-way flight.{0,160}?\$([0-9][0-9,]{1,4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.I | re.S)
        if match:
            price = _parse_money(match.group(1))
            if price is not None:
                return price
    return None


def _fmt_date(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%b %-d")
    except ValueError:
        return iso


def _pick_deal(deals, flight_date, stops="all"):
    if not deals:
        return None, None
    pool = deals
    if stops == "nonstop":
        filtered = [d for d in deals if d.get("stops") == 0]
        if filtered:
            pool = filtered
    elif stops == "connecting":
        filtered = [d for d in deals if d.get("stops") not in (None, 0)]
        if filtered:
            pool = filtered
    if flight_date is None:
        return min(pool, key=lambda d: d["price"]), "route_lowest"

    target = flight_date.isoformat()
    exact = [d for d in pool if d["date"] == target]
    if exact:
        return min(exact, key=lambda d: d["price"]), "exact"

    nearby = []
    for deal in pool:
        try:
            deal_date = date.fromisoformat(deal["date"])
        except ValueError:
            continue
        delta = abs((deal_date - flight_date).days)
        if delta <= NEARBY_DAYS:
            nearby.append((delta, deal))
    if nearby:
        nearby.sort(key=lambda item: (item[0], item[1]["price"]))
        return nearby[0][1], "nearby"
    return min(pool, key=lambda d: d["price"]), "route_lowest"


def fare_from_kayak_html(html, flight_date=None, nonstop_only=False, stops=None):
    deals = parse_kayak_one_way_deals(html)
    if stops is None:
        stops = "nonstop" if nonstop_only else "all"
    deal, match = _pick_deal(deals, flight_date, stops=stops)
    headline = parse_cheapest_one_way_headline(html)

    if deal is None and headline is None:
        return None

    if deal is None:
        return {
            "price": headline,
            "matched_date": None,
            "match": "route_lowest",
            "source": "kayak",
        }

    price = deal["price"]
    if match == "route_lowest" and headline is not None:
        price = min(price, headline)
    return {
        "price": price,
        "matched_date": deal["date"],
        "match": match,
        "source": "kayak",
        "stops": deal.get("stops"),
        "carrier": deal.get("carrier"),
    }


def fare_from_google_html(html):
    price = parse_cheapest_one_way_headline(html)
    if price is None:
        return None
    return {
        "price": price,
        "matched_date": None,
        "match": "route_lowest",
        "source": "google",
    }


def _label(hit, origin, destination, flight_date):
    price = int(round(hit["price"]))
    source = "Kayak" if hit["source"] == "kayak" else "Google Flights"
    match = hit.get("match")
    matched = hit.get("matched_date")
    if match == "exact" and matched:
        return (
            f"Today's lowest published one-way for {_fmt_date(matched)} is ${price} "
            f"({source}). The predicted trend is unchanged; the dollars are scaled to that fare."
        )
    if match == "nearby" and matched and flight_date is not None:
        return (
            f"{source} didn't list {flight_date:%b %-d}; nearest published one-way is "
            f"${price} on {_fmt_date(matched)}. Curve scaled to that fare."
        )
    if matched:
        return (
            f"Today's lowest published one-way {origin}–{destination} is ${price} "
            f"({source}, {_fmt_date(matched)}). Your exact date wasn't listed; "
            f"the predicted trend is scaled to that fare."
        )
    return (
        f"Today's lowest published one-way {origin}–{destination} is ${price} ({source}). "
        f"The predicted trend is scaled to that fare."
    )


def _http_get(url, timeout=FETCH_TIMEOUT):
    if _fetch_fn is not None:
        return _fetch_fn(url)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        request = urllib.request.Request(url, headers=headers)
        context = ssl.create_default_context()
        with urllib.request.urlopen(request, timeout=timeout, context=context) as resp:
            return resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError):
        return _curl_get(url, timeout)


def _curl_get(url, timeout):
    curl = shutil.which("curl")
    if not curl:
        return None
    try:
        result = subprocess.run(
            [
                curl, "-sS", "-L",
                "-A", USER_AGENT,
                "--max-time", str(int(timeout)),
                url,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 0 and result.stdout:
        return result.stdout
    return None


def lookup_live_min_fare(origin, destination, flight_date=None, nonstop_only=False, stops=None):
    """Return a published one-way fare dict, or None if nothing usable was found."""
    origin = origin.upper()
    destination = destination.upper()
    if stops is None:
        stops = "nonstop" if nonstop_only else "all"
    kayak_url = KAYAK_ROUTE_URL.format(origin=origin, destination=destination)
    html = _http_get(kayak_url)
    hit = fare_from_kayak_html(html, flight_date=flight_date, stops=stops) if html else None
    if hit:
        hit["url"] = kayak_url
        hit["label"] = _label(hit, origin, destination, flight_date)
        return hit

    origin_slug = CITY_SLUG.get(origin)
    dest_slug = CITY_SLUG.get(destination)
    if not origin_slug or not dest_slug:
        return None
    google_url = GOOGLE_PAIR_URL.format(origin=origin_slug, destination=dest_slug)
    html = _http_get(google_url)
    hit = fare_from_google_html(html) if html else None
    if hit:
        hit["url"] = google_url
        hit["label"] = _label(hit, origin, destination, flight_date)
        return hit
    return None
