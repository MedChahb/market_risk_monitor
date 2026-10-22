"""Trading calendars: exchange_calendars sessions, or Monday to Friday for markets without one."""

from datetime import date
from functools import lru_cache

import exchange_calendars as xcals
import pandas as pd

REPORTING_CALENDARS = ("XPAR", "XNYS")  # a reporting day is a day when Paris or New York trades


@lru_cache
def exchange_calendar(code: str) -> xcals.ExchangeCalendar:
    return xcals.get_calendar(code, start="2005-01-03")  # well before the 2008 start of the data


def sessions(code: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    if code == "weekdays":
        return pd.bdate_range(start, end)
    calendar = exchange_calendar(code)
    start = max(pd.Timestamp(start), calendar.first_session)
    end = min(pd.Timestamp(end), calendar.last_session)
    return calendar.sessions_in_range(start, end)


def previous_session(code: str | None, as_of: date) -> pd.Timestamp:
    """Last session strictly before the as-of date: the most recent close a run can expect."""
    end = pd.Timestamp(as_of) - pd.Timedelta(days=1)
    return sessions(code or "weekdays", end - pd.Timedelta(days=14), end)[-1]


def reporting_days(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    days = pd.DatetimeIndex([])
    for code in REPORTING_CALENDARS:
        days = days.union(sessions(code, start, end))
    return days


def following_sessions(code: str, days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The first session strictly after each day."""
    window = sessions(code, days.min(), days.max() + pd.Timedelta(days=14))
    return window[window.searchsorted(days, side="right")]
