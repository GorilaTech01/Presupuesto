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

Safe to run every morning: if the same asset/direction/horizon thesis from
a previous run is still active (`WAIT` or `READY_TO_TRADE`), `daily`
**continues that same tracked opportunity** instead of starting a second,
parallel one -- see "How re-running `daily` avoids duplicate opportunities"
below. If you just want a lighter re-check on what's already tracked
without a fresh 3-candidate comparison, `python -m app monitor --all` alone
is cheaper (see "After an important catalyst" below).

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

Marks the journal entry as skipped **and** cancels the underlying
monitored opportunity, so `monitor --all` stops re-evaluating it and a
later `daily`/`weekly` run treats it as closed rather than continuing it.

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

## How re-running `daily` avoids duplicate opportunities

Every `daily`/`weekly` run still journals a fresh recommendation row (that
audit trail is intentional and unchanged), but before starting a new
*monitored opportunity* it checks whether one is already active for the
same thesis. "Same thesis" means: same asset, same direction (BUY/SELL),
and same horizon -- current price is never part of that check, so a moved
market never makes an unchanged thesis look new.

- **Still active** (`WAIT` or `READY_TO_TRADE`) and same asset/direction/
  horizon -> the existing opportunity is updated in place (score,
  conviction, catalysts, data cutoff, history) -- same `opportunity_id` as
  before, no duplicate.
- **Cancelled, expired, or skipped** (`journal skip` now cancels the
  underlying opportunity, not just the journal row) -> never reused; a
  fresh candidate for that asset starts a genuinely new opportunity.
- **Opposite direction, or a different horizon** -> always a new
  opportunity, even for the same asset -- that is a different thesis, not
  a continuation.

Nothing about scoring, thresholds, conviction, catalysts, trigger logic,
price policy, or the WAIT/READY_TO_TRADE/CANCELLED state machine changed to
make this work -- it's purely a lookup before persistence. See
`app/monitor/identity.py` for the exact fingerprint and
`tests/integration/test_opportunity_reuse.py` for the full set of reuse/
new-opportunity scenarios this is tested against.
