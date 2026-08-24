from datetime import date, timedelta

_HOLIDAY_CACHE = {}


def _nth_weekday(year, month, weekday, n):
    """nth occurrence of weekday in month. weekday: Mon=0 .. Sun=6."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year, month, weekday):
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def us_federal_holidays(year):
    if year not in _HOLIDAY_CACHE:
        _HOLIDAY_CACHE[year] = frozenset({
            date(year, 1, 1),
            _nth_weekday(year, 1, 0, 3),   # MLK
            _nth_weekday(year, 2, 0, 3),   # Presidents
            _last_weekday(year, 5, 0),     # Memorial
            date(year, 6, 19),             # Juneteenth
            date(year, 7, 4),
            _nth_weekday(year, 9, 0, 1),   # Labor
            _nth_weekday(year, 10, 0, 2),  # Columbus / Indigenous Peoples
            date(year, 11, 11),            # Veterans
            _nth_weekday(year, 11, 3, 4),  # Thanksgiving
            date(year, 12, 25),
        })
    return _HOLIDAY_CACHE[year]


def near_holiday(d, window=3):
    if not isinstance(d, date):
        d = d.date() if hasattr(d, "date") else date.fromisoformat(str(d)[:10])
    hols = us_federal_holidays(d.year) | us_federal_holidays(d.year - 1) | us_federal_holidays(d.year + 1)
    return any(abs((d - h).days) <= window for h in hols)


def is_weekend_dow(dow):
    """True for Sat/Sun. duckdb dayofweek is Sun=0 .. Sat=6."""
    return int(dow) in (0, 6)
