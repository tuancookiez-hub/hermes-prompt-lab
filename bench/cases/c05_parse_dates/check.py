import datetime as dt, sys
sys.path.insert(0, ".")
from utils.dates import format_date, parse_date
assert parse_date("03/04/2026") == dt.date(2026, 4, 3)
assert parse_date(format_date(dt.date(2025, 12, 31))) == dt.date(2025, 12, 31)
