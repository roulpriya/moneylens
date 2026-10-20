"""Separate recent-account discovery from the calendar-month report window."""
import datetime as dt
from zoneinfo import ZoneInfo


def windows(timezone='UTC', current=None):
    current = current or dt.datetime.now(dt.timezone.utc)
    today = current.astimezone(ZoneInfo(timezone)).date()
    first = today.replace(day=1)
    previous = (first - dt.timedelta(days=1)).replace(day=1)
    return {'timezone': timezone, 'discovery_from': (today - dt.timedelta(days=30)).isoformat(),
            'discovery_before': (today + dt.timedelta(days=1)).isoformat(),
            'report_from': previous.isoformat(), 'report_to': today.isoformat()}
