# BF trading calendar (iCal feed)

A subscribable iCal feed of the days the BF strategy trades, generated from the decision
the live box actually runs.

## Subscribe (Google Calendar)

1. Google Calendar -> **Other calendars** -> **+** -> **From URL**
2. Paste:

   `https://jayc-codes.github.io/bf-calendar/trading-calendar.ics`

3. **Add calendar**

Use **From URL**, not **Import**: a subscription re-reads the feed, so refreshes reach your
calendar. Apple Calendar / Outlook: File -> New Calendar Subscription, same URL.

## What it shows

| Event | Meaning |
|---|---|
| `Trading Window` 09:30-10:30 ET | A trading day. That is the fill window. |
| `No trade - <reason>` (all day) | The strategy stands down; the description says why. |

Coverage is rolling: from the 1st of the month 90 days back to 31 Dec two years ahead.

## The rule

The deployed v2 strategy (`BFEngine.Holiday.cs` -> `HolidayDrop.Decide`) drops exactly
three classes, with `dropNoCashOpen=false` and `dropPreExpiry=false` as reported in its own
startup config line:

1. **cash closure** - NYSE/Nasdaq holidays, Good Friday included
2. **half session** - 13:15 ET early close
3. **beside a closure** - a weekday one calendar day either side of a closure

Everything else is a trading day, including Columbus Day, Veterans Day and the quarterly
expiry week. Those last two classes are only in `BFCalendar.NoTradeReason`, the old C# live
rule, which the box has switched off and the frozen backtest never applied.

### Why those two are not skipped (measured)

`bucko-freedom/scripts/holiday_extras.py` on the 1,245 adopted oracle trades, baseline
13.5 trades/mo and 7.29 R/mo:

| Class | Sessions | Trades | E(R) | 95% CI | Dropping costs |
|---|---|---|---|---|---|
| Columbus + Veterans | 11 | 13 | +0.002R | [-0.613, +0.749] | 0.00 R/mo |
| Pre-expiry week | 52 | 70 | +0.622R | [+0.315, +0.948] | 0.47 R/mo |

Neither class is measurably bad, and the expiry week is measurably good. A feed that
dropped them (the 2026-10-13 version did) disagreed with the strategy on 61 sessions a year.

## Refresh

`.github/workflows/refresh.yml` regenerates the feed daily at 09:17 UTC, proves it still
matches the pinned compiled-C# answer (`--selftest`), validates the iCalendar structure, and
commits only when the content changed. GitHub Pages serves the committed file; Google
re-reads it on its own schedule, typically within a day.

## Source of truth

`trading_calendar.py` here is a copy of `scripts/calendar/trading_calendar.py` in the
private `jayc-codes/trading` repo. Edit it there, then republish that file and the
regenerated `.ics` together, so the two copies cannot drift.
