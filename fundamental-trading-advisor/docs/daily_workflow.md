# Daily Operating Guide (manual use)

This is the practical routine, not a design document -- see
`docs/monitoring.md` and `README.md` for how the system actually works
underneath. Everything here is manual: you read the output, you decide,
you execute in Pepperstone/MT5 yourself. Nothing in this project sends an
order.

## Each morning

```bash
uv run python -m app daily
```

This runs the full weekly fundamental comparison, refreshes every
opportunity already being tracked, and prints one consolidated review. It
is pure orchestration of `weekly` + `monitor --all` -- no new scoring or
decision logic.

**Important:** `daily` re-runs the full weekly comparison every time you
call it. Running it once at the start of your session is the intended use.
If you already have an open idea (`WAIT` or `READY_TO_TRADE`) you're
tracking and just want a fresh read on it, run `python -m app monitor --all`
instead (see "After an important catalyst" below) -- it's cheaper and
doesn't start tracking a second, separate copy of the same idea. See
"Known limitation" at the end of this guide.

## What the output means

| You see | Meaning | What you do |
|---|---|---|
| `WAIT` | Fundamentals lean a direction, but at least one required condition (a pending catalyst, price, symbol, or risk-plan check) hasn't cleared yet. | Nothing. Do not enter. Check again later or after the next catalyst. |
| `READY_TO_TRADE` | Every fundamental and operational gate has cleared. A full trade plan (entry/SL/TP/R:R) is shown. | Read the plan, re-verify price/spread/symbol live in MT5, and decide. If you take it, see "If you enter manually" below. |
| `NO_TRADE` | No candidate currently clears the minimum fundamental threshold. | Nothing to do. Check again tomorrow or after your next planned review. |
| `CANCELLED` | A previously-tracked idea was invalidated -- either a catalyst published a result that contradicts the thesis, or its time stop passed. | Nothing to do if you hadn't entered. If you had, treat it as your exit signal. |
| `NO_CHANGE` (from `monitor`) | You re-checked an existing idea and nothing material changed since last time. | Nothing to do. |

`WAIT` never means "enter soon" and `READY_TO_TRADE` is never automatic --
reaching it only means the system finished checking; you still decide and
execute by hand.

## After an important catalyst (or whenever you want to re-check)

```bash
uv run python -m app monitor --all
```

This re-evaluates every tracked opportunity against the latest available
data and reports its updated state (`NO_CHANGE` / `WAIT` / `READY_TO_TRADE`
/ `CANCELLED`). Safe to run as often as you like -- it never creates a
second copy of an existing idea and never sends a duplicate alert for a
state you've already seen.

To check on one specific idea instead of all of them:

```bash
uv run python -m app monitor --opportunity-id <id>
```

## If READY_TO_TRADE appears

Read the full block: asset, direction, conviction, why now, entry, stop
loss, take profit, R:R, fundamental invalidation, valid-until. Then, in
MT5:

1. Re-verify the exact instrument (`MT5 > Market Watch > Show All`).
2. Re-check the live bid/ask/spread yourself -- the printed entry is a
   reference, not a guarantee.
3. Decide. Nothing here executes for you.

## If you enter manually

```bash
uv run python -m app journal enter --opportunity-id <id> --price <actual_entry_price>
```

Records your entry in the journal for later performance review. **Never**
sends an order -- it only writes a log line.

## If you don't take it

```bash
uv run python -m app journal skip --opportunity-id <id>
```

Marks the journal entry as skipped. Note: this does not stop the
underlying opportunity from being tracked -- `monitor --all` will keep
re-evaluating it until it naturally expires (its time stop) or is
fundamentally invalidated (`CANCELLED`). If you don't want to see it again
after skipping, just ignore it in future `monitor`/`daily` output; it will
resolve to `CANCELLED` or expire on its own.

## If it says CANCELLED

The thesis is dead -- a catalyst contradicted it, or its time window
passed. If you never entered, there's nothing to do. If you did, this is
your signal to review/exit manually.

## At the end of the week

```bash
uv run python -m app evaluate --export-csv data/journal/benchmark.csv --export-jsonl data/journal/benchmark.jsonl
```

Prints win rate / average R / profit factor / expectancy from whatever
outcomes are already recorded, and (optionally) exports the benchmark
files for comparing against another trading system.

```bash
uv run python -m app journal
```

Lists every journaled recommendation if you just want to review the raw
log.

## Known limitation: re-running `daily`/`weekly` starts a new tracked idea

Each `daily`/`weekly` run generates a fresh recommendation and, if a
candidate is interesting enough, a **new** monitored opportunity for it --
it does not resume or merge into one you already have open for the same
asset. In practice this means: if you run `daily` every single morning
while EURUSD stays interesting for several days in a row, you can end up
tracking several separate EURUSD opportunities instead of one continuous
one, each independently reaching `WAIT`/`READY_TO_TRADE`/`CANCELLED` (and
potentially alerting) on its own schedule.

This is a known characteristic of the current design, not a scoring or
threshold bug, and it has not been changed as part of this close-out (that
would be a methodology change outside today's scope). The practical
workaround: use `daily` to check for genuinely new setups (e.g. once at the
start of your trading week, or when you suspect the picture has changed),
and use `python -m app monitor --all` for routine day-to-day re-checks of
what you're already tracking -- it only ever refreshes existing
opportunities and never creates new ones.
