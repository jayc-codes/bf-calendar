"""Generate the BF trading-calendar .ics, the feed you subscribe to in Google Calendar.

The day classification is a line-for-line mirror of the live gate,
``bucko-freedom/ninjatrader/BFCalendar.cs`` -> ``NoTradeReason``, in the SAME
order the C# evaluates it:

    1. no cash open      Columbus Day, Veterans Day
    2. exchange holiday  NYSE/Nasdaq closures (Good Friday included)
    3. half session      13:15 ET early close
    4. beside a closure  weekday one calendar day either side of a closure
    5. quarterly expiry  <= 4 calendar days to the 3rd Friday of Mar/Jun/Sep/Dec

Any weekday that survives all five is a trading day. Weekends are never sessions.

WHY THIS REPLACED THE FIRST GENERATOR (2026-11-10). The first one derived days
from ``marketdata/holidays.py``, which has no Columbus Day / Veterans Day class
at all -- so it printed ``Trading Window`` on 2026-11-11, while the live gate says
NO TRADE. The incident is why ``BFCalendar.noCashOpen`` exists (the chart traded
Columbus Day live while the backtest excluded it). ``tests/test_trading_calendar.py``
pins the feed to the C# answer so the two cannot drift again.

WHY VETERANS DAY IS HERE AT ALL, and where the C# premise is wrong. ``BFCalendar``
says these two dates have "no 09:30 cash open". That is false for the NYSE, which
trades a full session on both Columbus Day and Veterans Day. What ``BFCalendar``
really encodes is a defensive skip of two thin-ish sessions; ``holidays.py`` never
excluded them, so the -0.231R "no cash open" figure was measured on real closures
(MLK, Presidents, Memorial, July 4, Labor, Thanksgiving, Christmas, New Year,
Good Friday, Juneteenth), not on these two days. The feed mirrors the gate because
its job is "when does BF trade", not "when is the market open". Flip that decision
in one place: ``NO_CASH_OPEN_LABELS`` plus ``--holidays market``.

    python scripts/calendar/trading_calendar.py --out scripts/calendar/trading-calendar.ics
    python scripts/calendar/trading_calendar.py --selftest
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

TZID = "America/New_York"
WIN_START = (9, 30)
WIN_END = (10, 30)
CAL_NAME = "BF Trading"
CAL_DESC = ("When the BF strategy trades. Trading days carry the 09:30-10:30 ET fill "
            "window. Skipped days are all-day markers with the reason in the "
            "description.")
HORIZON_BACK_DAYS = 90
FIRST_YEAR, LAST_YEAR = 2015, 2060


# ---------------------------------------------------------------- calendar math
def nth_weekday(y: int, mo: int, dow: int, n: int) -> date:
    d = date(y, mo, 1)
    return d + timedelta(days=(dow - d.weekday()) % 7 + 7 * (n - 1))


def last_weekday(y: int, mo: int, dow: int) -> date:
    nxt = date(y + (mo == 12), (mo % 12) + 1, 1)
    d = nxt - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - dow) % 7)


def observed(d: date) -> date:
    """Saturday holidays observe the Friday, Sunday holidays the Monday."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def good_friday(year: int) -> date:
    """Anonymous Gregorian computus, then back up two days from Easter Sunday."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    lterm = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lterm) // 451
    month = (h + lterm - 7 * m + 114) // 31
    day = ((h + lterm - 7 * m + 114) % 31) + 1
    return date(year, month, day) - timedelta(days=2)


def closures(y: int) -> dict[date, str]:
    """Named NYSE/Nasdaq closures -- the C# BuildClosed set, with names for display."""
    out = {
        observed(date(y, 1, 1)): "New Year's Day",
        nth_weekday(y, 1, 0, 3): "Martin Luther King Jr Day",
        nth_weekday(y, 2, 0, 3): "Washington's Birthday",
        good_friday(y): "Good Friday",
        last_weekday(y, 5, 0): "Memorial Day",
        observed(date(y, 7, 4)): "Independence Day",
        nth_weekday(y, 9, 0, 1): "Labor Day",
        nth_weekday(y, 11, 3, 4): "Thanksgiving",
        observed(date(y, 12, 25)): "Christmas",
    }
    if y >= 2022:
        out[observed(date(y, 6, 19))] = "Juneteenth"
    return out


def no_cash_open(y: int) -> dict[date, str]:
    """The C# BuildNoCashOpen set: futures trade, the gate stands down anyway."""
    return {
        nth_weekday(y, 10, 0, 2): "Columbus Day",
        observed(date(y, 11, 11)): "Veterans Day",
    }


def half_sessions(y: int) -> dict[date, str]:
    """13:15 ET early closes -- the C# BuildHalf set."""
    out: dict[date, str] = {}
    july4 = observed(date(y, 7, 4))
    if july4.weekday() < 5:
        prior = july4 - timedelta(days=1)
        if prior.weekday() < 5:
            out[prior] = "day before Independence Day"
    out[nth_weekday(y, 11, 3, 4) + timedelta(days=1)] = "day after Thanksgiving"
    xmas_eve = date(y, 12, 24)
    if xmas_eve.weekday() < 5:
        out[xmas_eve] = "Christmas Eve"
    return out


def days_to_quarterly_expiry(day: date) -> int:
    """Calendar days to the next 3rd Friday of Mar / Jun / Sep / Dec."""
    for add in range(200):
        d = day + timedelta(days=add)
        if d.month in (3, 6, 9, 12) and d.weekday() == 4 and 15 <= d.day <= 21:
            return add
    return 999


def quarterly_month(day: date) -> str:
    d = day + timedelta(days=days_to_quarterly_expiry(day))
    return d.strftime("%b %Y")


class Calendar:
    """The five gates, in the C# order. ``None`` from ``no_trade`` means tradeable."""

    def __init__(self, years: range, include_expiry: bool = True, holidays: str = "bf"):
        self.include_expiry = include_expiry
        self.closed: dict[date, str] = {}
        self.nocash: dict[date, str] = {}
        self.half: dict[date, str] = {}
        for y in years:
            self.closed.update(closures(y))
            if holidays == "bf":
                self.nocash.update(no_cash_open(y))
            self.half.update(half_sessions(y))

    def no_trade(self, d: date) -> tuple[str, str] | None:
        """(short title, long reason) or None. Mirrors BFCalendar.NoTradeReason."""
        if d in self.nocash:
            name = self.nocash[d]
            return (f"No trade - {name}",
                    f"{name}: BFCalendar treats this as a no-cash-open day and stands "
                    f"down. Note the NYSE is actually open; this is a defensive skip, "
                    f"not a closure.")
        if d in self.closed:
            name = self.closed[d]
            return (f"No trade - {name}",
                    f"{name}: exchange holiday. The 09:30 ET cash open this model is "
                    f"built on does not happen; measured -0.231R against +0.599R.")
        if d in self.half:
            name = self.half[d]
            return (f"No trade - half session ({name})",
                    f"{name}: half session, 13:15 ET close. Thin, excluded from the "
                    f"backtest.")
        for cand, direction in ((d - timedelta(days=1), "day after"),
                                (d + timedelta(days=1), "day before")):
            if cand in self.closed:
                return (f"No trade - beside {self.closed[cand]}",
                        f"Beside a closure ({direction} {self.closed[cand]}). Thin, "
                        f"excluded from the backtest.")
        if self.include_expiry:
            dte = days_to_quarterly_expiry(d)
            if dte <= 4:
                when = "today" if dte == 0 else f"{dte} day{'s' if dte != 1 else ''} out"
                return (f"No trade - quarterly expiry in {dte}d"
                        if dte else "No trade - quarterly expiry day",
                        f"Front-month volume runs 22-28% of normal at 2-4 days out and "
                        f"1-2% on expiry day ({quarterly_month(d)} expiry is {when}). "
                        f"Roll to the next contract and resume.")
        return None


# ------------------------------------------------------------------- ics writing
def esc(text: str) -> str:
    """RFC 5545 TEXT escaping: backslash, semicolon, comma, newline."""
    out = (text.replace("\\", "\\\\").replace(";", "\\;")
               .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n"))
    return out.replace("\r", "\\n")


def fold(line: str) -> str:
    """RFC 5545 folding: continuation lines, 75 octets max, never split a UTF-8 char."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > 74:
            parts.append(cur)
            cur = b          # keep the character that started this new line
        else:
            cur += b
    parts.append(cur)
    return "\r\n ".join(p.decode("utf-8") for p in parts)


VTIMEZONE = """BEGIN:VTIMEZONE
TZID:America/New_York
X-LIC-LOCATION:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE""".split("\n")


def build(start: date, end: date, include_expiry: bool = True,
          holidays: str = "bf", stamp: datetime | None = None) -> tuple[str, int, int]:
    years = range(start.year - 1, end.year + 2)
    cal = Calendar(years, include_expiry=include_expiry, holidays=holidays)
    # DTSTAMP is derived from the window, not from the clock: a daily refresh then
    # produces byte-identical output, so the feed only commits when its CONTENT
    # changes. Google refetches on its own schedule regardless of DTSTAMP.
    if stamp is None:
        stamp = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    stamp = stamp.strftime("%Y%m%dT%H%M%SZ")

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//trading//bf-calendar//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{CAL_NAME}",
             f"X-WR-CALDESC:{esc(CAL_DESC)}", f"X-WR-TIMEZONE:{TZID}",
             "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H",
             "SOURCE;VALUE=URI:https://jayc-codes.github.io/bf-calendar/trading-calendar.ics"
             ] + VTIMEZONE

    trade = no = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            reason = cal.no_trade(d)
            if reason is None:
                trade += 1
                ds = f"{d:%Y%m%d}T{WIN_START[0]:02d}{WIN_START[1]:02d}00"
                de = f"{d:%Y%m%d}T{WIN_END[0]:02d}{WIN_END[1]:02d}00"
                lines += ["BEGIN:VEVENT", f"UID:bf-trade-{d:%Y%m%d}@bf-calendar",
                          f"DTSTAMP:{stamp}", f"DTSTART;TZID={TZID}:{ds}",
                          f"DTEND;TZID={TZID}:{de}", "SUMMARY:Trading Window",
                          "DESCRIPTION:BF fill window 09:30-10:30 ET. One trade per pair "
                          "per session, win lose or scratch.",
                          "TRANSP:TRANSPARENT", "SEQUENCE:0", "END:VEVENT"]
            else:
                no += 1
                short, long_reason = reason
                nxt = d + timedelta(days=1)
                lines += ["BEGIN:VEVENT", f"UID:bf-notrade-{d:%Y%m%d}@bf-calendar",
                          f"DTSTAMP:{stamp}", f"DTSTART;VALUE=DATE:{d:%Y%m%d}",
                          f"DTEND;VALUE=DATE:{nxt:%Y%m%d}", f"SUMMARY:{esc(short)}",
                          f"DESCRIPTION:{esc(long_reason)}",
                          "TRANSP:TRANSPARENT", "SEQUENCE:0", "END:VEVENT"]
        d += timedelta(days=1)

    lines.append("END:VCALENDAR")
    # ONE fold pass, at the end: folding a line that is already folded corrupts it.
    return "\r\n".join(fold(line) for line in lines) + "\r\n", trade, no


def default_window(today: date | None = None) -> tuple[date, date]:
    """A window that only moves once a month, so a daily refresh commits only then.

    Start is the 1st of the month 90 days back; end is 31 Dec two years out. The
    horizon is therefore always >= 90 days behind and >= 2 years ahead, and the
    generated bytes are identical for every day inside the same month.
    """
    today = today or date.today()
    back = today - timedelta(days=HORIZON_BACK_DAYS)
    return date(back.year, back.month, 1), date(today.year + 2, 12, 31)


# --------------------------------------------------------------------- selftest
GOLDEN_TRADE = """
2026-11-06 2026-11-09 2026-11-10 2026-11-12 2026-11-13 2026-11-16 2026-11-17
2026-11-18 2026-11-19 2026-11-20 2026-11-23 2026-11-24 2026-11-30 2026-12-01
2026-12-02 2026-12-03 2026-12-04 2026-12-07 2026-12-08 2026-12-09 2026-12-10
2026-12-11 2026-12-21 2026-12-22 2026-12-23 2026-12-28 2026-12-29 2026-12-30
2027-01-04 2027-01-05 2027-01-06 2027-01-07 2027-01-08 2027-01-11 2027-01-12
2027-01-13 2027-01-14 2027-01-15 2027-01-20 2027-01-21 2027-01-22 2027-01-25
2027-01-26 2027-01-27 2027-01-28 2027-01-29 2027-02-01 2027-02-02 2027-02-03
2027-02-04
"""
GOLDEN_SKIP = """
2026-11-11 2026-11-25 2026-11-26 2026-11-27 2026-12-14 2026-12-15 2026-12-16
2026-12-17 2026-12-18 2026-12-24 2026-12-25 2026-12-31 2027-01-01 2027-01-18
2027-01-19
"""


def selftest() -> int:
    """Pin the gate to the answer the compiled BFCalendar.cs gives (see README)."""
    start, end = date(2026, 11, 6), date(2027, 2, 4)
    cal = Calendar(range(start.year - 1, end.year + 2))
    got_trade, got_skip = [], []
    d = start
    while d <= end:
        if d.weekday() < 5:
            (got_skip if cal.no_trade(d) else got_trade).append(d.isoformat())
        d += timedelta(days=1)
    want_trade = GOLDEN_TRADE.split()
    want_skip = GOLDEN_SKIP.split()
    fails = []
    if got_trade != want_trade:
        fails.append(f"trading days differ\n  got  {got_trade}\n  want {want_trade}")
    if got_skip != want_skip:
        fails.append(f"skipped days differ\n  got  {got_skip}\n  want {want_skip}")

    # The 2026-11-10 regression: the first feed called Veterans Day tradeable.
    if (date(2026, 11, 11) in {date.fromisoformat(x) for x in got_trade}):
        fails.append("2026-11-11 (Veterans Day) came back tradeable")
    # Columbus Day and the expiry week, the other two classes the old feed missed.
    for pin in (date(2026, 10, 12), date(2026, 12, 18), date(2026, 11, 27)):
        if cal.no_trade(pin) is None:
            fails.append(f"{pin} came back tradeable")
    # A plain week must stay contiguous: Mon-Fri tradeable, weekend absent.
    for pin in (date(2027, 1, 4), date(2027, 1, 8)):
        if cal.no_trade(pin) is not None:
            fails.append(f"{pin} came back skipped")

    for f in fails:
        print("FAIL", f)
    print(f"selftest: {len(got_trade)} trading days, {len(got_skip)} skipped, "
          f"{len(fails)} failure(s)")
    return 1 if fails else 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="start", default=None)
    p.add_argument("--to", dest="end", default=None)
    p.add_argument("--out", default="scripts/calendar/trading-calendar.ics")
    p.add_argument("--no-expiry", action="store_true",
                   help="skip the quarterly-expiry blackout")
    p.add_argument("--holidays", choices=("bf", "market"), default="bf",
                   help="bf: mirror the BFCalendar gate (default). market: NYSE-only "
                        "closures, dropping the Columbus/Veterans defensive skip.")
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args()

    if a.selftest:
        return selftest()

    start, end = default_window()
    if a.start:
        start = datetime.strptime(a.start, "%Y-%m-%d").date()
    if a.end:
        end = datetime.strptime(a.end, "%Y-%m-%d").date()

    ics, trade, no = build(start, end, not a.no_expiry, a.holidays)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(ics, encoding="utf-8", newline="")
    print(f"{out}: {trade + no} weekdays ({trade} Trading Window, {no} No trade)")
    print(f"  {start} .. {end}, {WIN_START[0]:02d}:{WIN_START[1]:02d}-"
          f"{WIN_END[0]:02d}:{WIN_END[1]:02d} {TZID}, holidays={a.holidays}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
