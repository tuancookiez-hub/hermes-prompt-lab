"""Date helpers."""
import datetime as dt


def format_date(d: dt.date) -> str:
    return d.strftime("%d/%m/%Y")
