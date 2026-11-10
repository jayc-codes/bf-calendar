# BF trading calendar (iCal feed)

A subscribable iCal feed of the days the BF strategy trades, generated from the
same gate the live NinjaTrader strategy runs
(`bucko-freedom/ninjatrader/BFCalendar.cs` -> `NoTradeReason`).

## Subscribe (Google Calendar)

1. Google Calendar -> **Other calendars** -> **+** -> **From URL**
2. Paste:

   `https://jayc-codes.github.io/bf-calendar/trading-calendar.ics`

3. **Add calendar**

Use **From URL**, not **Import**: a subscription re-reads the feed, so the
refreshes below reach your calendar. An import is a one-off copy that goes stale.

Apple Calendar / Outlook: File -> New Calendar Subscription, same URL.

## What it shows

| Event | Meaning |
|---|---|
| `Trading Window` 09:30-10:30 ET | A trading day. That is the fill window. |
| `No trade - <reason>` (all day) | The gate stands down; the description says why. |

Coverage is a rolling window: from the 1st of the month 90 days back to 31 Dec two
years ahead, so there are always at least 90 days behind and two years ahead.

## The five gates, in the order the C# evaluates them

1. **no cash open** - Columbus Day, Veterans Day (BF skips these; see the caveat below)
2. **exchange holiday** - NYSE/Nasdaq closures, Good Friday included
3. **half session** - 13:15 ET early close
4. **beside a closure** - a weekday one calendar day either side of a closure
5. **quarterly expiry** - 4 or fewer calendar days to the 3rd Friday of Mar/Jun/Sep/Dec

Weekends are never sessions. Any weekday surviving all five is a trading day.

### Caveat: "no cash open" on Columbus Day and Veterans Day is the gate's rule, not a fact

`BFCalendar.cs` claims those two dates have no 09:30 cash open. The NYSE actually
trades a full session on both. What the gate really does is skip two thin-ish
sessions defensively, and `marketdata/holidays.py` never excluded them, so the
-0.231R "no cash open" figure was measured on real closures (MLK, Presidents,
Memorial, July 4, Labor, Thanksgiving, Christmas, New Year, Good Friday,
Juneteenth). This feed mirrors the gate because its job is "when does BF trade".
To publish NYSE reality instead:

    python trading_calendar.py --holidays market --out trading-calendar.ics

## Refresh

`.github/workflows/refresh.yml` regenerates the feed daily at 09:17 UTC, proves it
still matches the pinned C# answer (`--selftest`), and commits only when the
content changed. GitHub Pages serves the committed file. Google Calendar then
re-reads it on its own schedule, typically within a day.

## Source of truth

`trading_calendar.py` here is a copy of
`scripts/calendar/trading_calendar.py` in the private `jayc-codes/trading` repo.
Edit it there, then republish that file and the regenerated `.ics` together, so
the two copies cannot drift.
