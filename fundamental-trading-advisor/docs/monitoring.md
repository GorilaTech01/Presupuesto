# V1.1 -- Fundamental Monitoring & Trade Alerts

(Includes V1.1.1, section 2a: automatic, read-only execution-price
acquisition -- see below for what changed and what didn't.)

`weekly` produces one recommendation and stops. This layer adds the ability
to keep that recommendation under fundamental observation and re-evaluate
it as new data actually publishes, instead of treating Monday's read as
fixed all week.

```
WEEKLY ANALYSIS -> WAITING FOR CATALYST -> REEVALUATE -> READY_TO_TRADE
                                                       -> CANCELLED
```

Nothing here adds technical analysis, auto-execution, or a second decision
engine. It reuses the exact same normalization -> scoring -> catalyst ->
decision sequence `weekly` already uses (`app.fundamental.candidate.
build_decision_draft`), on freshly re-fetched official data, and just adds
a state machine on top of the result.

## 1. `fundamental_bias` vs. `trade_action` -- the core distinction

These are two different fields on `MonitoredTradeOpportunity` and must
never be conflated:

- **`fundamental_bias`** (`BULLISH` / `BEARISH` / `NEUTRAL`): the current
  directional read, from the sign of the fundamental score. This can
  change every time new data publishes.
- **`trade_action`** (`WAIT` / `READY_TO_TRADE` / `NO_TRADE` / `CANCELLED`):
  the opportunity's *operational* lifecycle state. A `BEARISH` bias can sit
  at `WAIT` for days or weeks while a required catalyst is still pending --
  `trade_action` only becomes `READY_TO_TRADE` once every criterion below
  is met.

`BUY`/`SELL` is not a `trade_action` value. The executable direction, once
`READY_TO_TRADE`, comes from the opportunity's `direction` field via its
`trade_plan` -- it is never inferred from `fundamental_bias` alone. This is
also unrelated to `weekly`'s own `ExecutionReadiness` (`ENTER_NOW` /
`WAIT_FOR_TRIGGER` / `NONE`), which is a one-shot, single-run concept;
`TradeAction` is a persisted opportunity's state over time.

**Reaching `READY_TO_TRADE` is not execution.** It means every fundamental
and operational gate has cleared; a human still has to read the alert,
re-verify price/spread/symbol in MT5, and place the order manually. See
section 7.

## 2. The READY_TO_TRADE gate

An opportunity only reaches `READY_TO_TRADE` when ALL of the following
hold (`app.monitor.opportunity_engine.evaluate_opportunity`):

1. It has not passed its `valid_until` time stop (expiration always wins,
   checked first, regardless of how strong the thesis looks).
2. No required (`HIGH`/`CRITICAL`) catalyst has published a result that
   contradicts the thesis (`FundamentalTriggerEvaluator` status `FAILED`
   cancels outright).
3. The underlying decision engine says `BUY`/`SELL`, not `NO_TRADE`.
4. **`PREFER_CONDITIONAL_POST_EVENT`**: every required catalyst is
   `CONFIRMED` -- not `PENDING`, not `PARTIALLY_CONFIRMED`. This is a
   *stricter* gate than `weekly`'s own `ExecutionReadiness` (which only
   blocks on an unresolved `CRITICAL` catalyst): here, even a `HIGH`
   catalyst still pending holds the opportunity at `WAIT`.
5. The broker symbol resolves and is verifiable.
6. A live price feed is available.
7. The resulting SL/TP/R:R risk plan is feasible (meets the minimum
   risk/reward and survives the spread check -- see `app/risk/trade_math.py`,
   no technical analysis involved).
8. Conviction has not been artificially inflated: the exact same
   `ConvictionBreakdown` the decision engine produced is carried through
   unchanged, including the permanent `EXPECTATIONS_INCOMPLETE_PENALTY`
   (no forward-policy-path data source exists in this version) and any
   contradiction penalty. A catalyst resolving in the thesis's favor never
   by itself adds conviction points.

If any gate fails, the opportunity stays at `WAIT` (or, if the underlying
score has also fallen below half the trade threshold, drops to `NO_TRADE`
and is no longer monitored -- see section 4).

`fundamental_setup_ready` (V1.1.1) is `True` once gates 1-4 and 8 have all
cleared -- i.e. the fundamental thesis itself is done -- independent of
whether gates 5-7 (symbol/price/risk-plan, all purely operational) have.
When `fundamental_setup_ready` is `True` but `trade_action` is still
`WAIT`, `readiness_blocker` names exactly which operational gate is still
open: `SYMBOL_UNVERIFIED`, `PRICE_UNAVAILABLE`, `PRICE_STALE`,
`EXECUTION_BLOCKED_SPREAD`, or `RISK_PLAN_INFEASIBLE`. This never happens
for a WAIT caused by fundamentals/catalysts still pending -- there,
`fundamental_setup_ready` stays `False` and `readiness_blocker` is `None`,
so a human glancing at a WAIT opportunity can immediately tell "still
waiting on data" from "fundamentals are done, only price/symbol is
missing" without reading the free-text reason.

## 2a. Automatic execution-price input (V1.1.1)

Once fundamentals and catalysts confirm, the system still needs a current
bid/ask to compute entry/SL/TP/R:R/position sizing (never to decide
direction -- see the guarantee below). `app.market.price_provider` defines
one typed result, `CurrentMarketQuote` (bid, ask, mid, spread, timestamp,
source, freshness, and -- when available -- tick_size/tick_value/
contract_size/volume_min/max/step/stops_level), returned identically by
every provider:

- **`MT5ReadOnlyPriceProvider`** (`app/market/mt5_provider.py`): reads
  `symbol_info`/`symbol_info_tick` from a MetaTrader 5 terminal already
  running and logged in on this machine. Strictly read-only -- it calls
  exactly `initialize`, `symbol_info`, `symbol_info_tick`, `shutdown`, and
  nothing else. It never logs in with stored credentials and never
  connects a real account automatically; it only attaches to whatever
  terminal (if any) is already open. If the `MetaTrader5` package isn't
  installed (it's Windows-only and not a project dependency) or no
  terminal is running, it fails closed to `DataSourceUnavailable` --
  exactly like every other source adapter in this project.
- **`ManualPriceFileProvider`**: the original `data/manual_prices.json`
  mechanism (section prior to V1.1.1), unchanged and never removed --
  always available as an explicit fallback.

`PRICE_PROVIDER` (`.env`) selects the priority, but the MT5 candidate is
only ever attached when `MT5_ENABLED=true` -- with the default settings
(`MT5_ENABLED=false`), `PRICE_PROVIDER=auto` behaves exactly like `manual`
and no live-terminal connection is ever attempted:

| Value | Behavior |
|---|---|
| `auto` (default) | With `MT5_ENABLED=true`: try a live read-only MT5 terminal first, fall back to the manual file. With the default `MT5_ENABLED=false`: manual file only. |
| `mt5` | MT5 only -- no manual fallback; raises `PRICE_UNAVAILABLE` immediately if `MT5_ENABLED=false`. |
| `manual` | Manual file only -- MT5 is never attempted regardless of `MT5_ENABLED`. |

`app.market.price_router.build_price_provider(settings)` is the one place
this is wired up; `weekly` and `monitor` both call it, so both always agree
on provider priority.

**Freshness.** `MAX_QUOTE_AGE_SECONDS` (default 60) bounds how old a quote
may be. A quote older than that is never used to build an executable plan:
`AutoPriceProvider.get_quote` raises `StaleDataError` (surfaced as
`PRICE_STALE`) if the best available quote is too old, or
`DataSourceUnavailable` (`PRICE_UNAVAILABLE`) if no configured source
returned anything at all -- these are deliberately distinct failure modes
so a monitored opportunity's `readiness_blocker` can say which one applies.

**Inspecting a quote directly:**

```bash
uv run python -m app quote EURUSD
```

```
Symbol: EURUSD
Broker symbol: EURUSD
Bid: 1.1000
Ask: 1.1002
Spread: 0.0002
Timestamp: 2026-09-01T12:00:00Z
Source: MT5_READ_ONLY
Fresh: YES
```

**The no-directional-price-signal guarantee.** Bid, ask, spread, and
mid-price can only ever affect: `estimated_entry`/`stop_loss`/
`take_profit`, `risk_reward`, `position_size_lots`, and whether execution
is blocked on spread/symbol/risk-plan grounds (`readiness_blocker`).
Nothing in `app.market`, `app.risk.trade_math`, or the price-provider
layer feeds into `fundamental_bias`, `direction`, `conviction`, or trigger
confirmation -- those come exclusively from
`app.fundamental.candidate.build_decision_draft` and
`app.monitor.trigger_evaluator.FundamentalTriggerEvaluator`, neither of
which takes a price as an input at all. `tests/unit/test_opportunity_engine.py`
(`test_changing_price_or_spread_never_flips_fundamental_bias`) and
`tests/integration/test_monitor_service.py`
(`test_changing_bid_ask_across_refreshes_never_changes_fundamental_bias`)
assert this directly: varying entry/stop/spread across otherwise-identical
re-evaluations never changes `fundamental_bias`, `direction`, or
`conviction` -- only the trade plan's own numbers and, potentially,
`trade_action`/`readiness_blocker`.

**Broker symbol verification.** Price acquisition reuses
`BrokerSymbolResolver` (unchanged) -- it never assumes an internal asset
name like `EURUSD` matches the broker's exact symbol. If it can't be
resolved, `readiness_blocker=SYMBOL_UNVERIFIED` and the opportunity stays
at `WAIT`, regardless of how confirmed the fundamentals are.

## 3. Fundamental triggers only

`app.monitor.trigger_evaluator.FundamentalTriggerEvaluator` looks *only* at
published-vs-consensus economic releases and central-bank decisions.

**Valid trigger conditions** (fundamental): a payrolls print beating/
missing consensus, a CPI print above/below consensus, a central bank
decision or statement tone, a GDP print. Each becomes a structured
`EconomicReleaseSurprise` (`actual`, `consensus`, `previous`,
`normalized_surprise`, `direction_for_currency_or_asset`) -- and if
`consensus` is missing, the direction is explicitly
`CONSENSUS_UNAVAILABLE`, never guessed.

**Invalid trigger conditions** (never used, anywhere in this module):
a price crossing a moving average, RSI/MACD/stochastic levels, a
support/resistance break, a candlestick pattern, a chart-derived level of
any kind. No field on `CatalystEvent` or `EconomicReleaseSurprise` carries
a price or an indicator value -- the data simply doesn't exist in this
module's inputs.

## 4. Monitoring-interest threshold

Not every `NO_TRADE` candidate is worth watching. If the fundamental score
is still at least half of the trade threshold (`MIN_BIAS_FOR_TRADE`, i.e.
`|score| >= 0.3` when the trade threshold is `0.6`), the candidate is kept
at `WAIT` as a monitored opportunity even though `weekly` itself would
have called `NO_TRADE`. Below that, it's dropped -- `create_opportunity`
returns `None` and nothing is persisted.

## 5. Incremental vs. full re-evaluation

```bash
uv run python -m app monitor                 # incremental: relies on each source's normal cache TTL
uv run python -m app monitor --full-refresh  # bypasses the cache, forces a real re-fetch
```

Incremental re-evaluation trusts each indicator's own TTL to naturally pick
up newly-published data around its release cadence, without hammering free
official APIs on every run. `--full-refresh` calls `DiskCache.clear_all()`
first, forcing every source to be hit again regardless of TTL -- useful
right after a known release if you don't want to wait out the cache.

## 6. `python -m app monitor` -- one pass, not a daemon

```bash
uv run python -m app monitor                              # re-evaluate every active opportunity
uv run python -m app monitor --opportunity-id <id>         # re-evaluate just one
uv run python -m app monitor --full-refresh                # bypass the cache
uv run python -m app monitor --json-out data/monitor/last_run.json
```

This command runs **exactly one** evaluation pass over stored opportunities
and exits. It is never a `while True` loop and never runs in the
background on its own. If you want periodic checks, schedule it yourself
-- cron, a systemd timer, a scheduled GitHub Action, or (if you're running
inside Claude Code / Cowork) a scheduled trigger that runs this same
command. Cancelled opportunities are a terminal state and are skipped on
every pass -- they are never re-evaluated again.

### Example output -- no material change

```
FUNDAMENTAL TRADE MONITOR

EURUSD
Bias: BEARISH
Action: WAIT
Conviction: 6/10

No material change.

Next catalyst:
us_nonfarm_payrolls (US)
2026-09-04 08:30 (local)

Status:
Waiting for catalyst.
```

### Example output -- fundamentals confirmed, price missing (V1.1.1)

```
FUNDAMENTAL TRADE MONITOR

EURUSD
Bias: BEARISH
Action: WAIT
Conviction: 7/10

No material change.

Next catalyst:
None flagged.

Status:
Waiting for catalyst.

Fundamental setup: READY.
Blocked only on: PRICE_UNAVAILABLE.
```

### Example output -- READY_TO_TRADE

```
════════════════════════════════════════
FUNDAMENTAL TRADE ALERT
════════════════════════════════════════

STATUS:
READY_TO_TRADE

Asset:
EURUSD

Direction:
SELL

Conviction:
7/10

Fundamental Trigger:
CONFIRMED

Why now:
  1. us_nonfarm_payrolls: confirms thesis (US_HAWKISH)

Entry:
1.1001

Stop Loss:
1.1050

Take Profit:
1.0900

R:R:
2.0

Fundamental invalidation:
Thesis invalidated if US fundamentals weaken materially relative to EUR...

Valid until:
2026-09-04T23:59:59-06:00

Next catalyst:
None flagged.

Manual execution only.

Verify exact symbol in:
MT5 > Market Watch > Show All
════════════════════════════════════════
```

### Example output -- CANCELLED

```
════════════════════════════════════════
FUNDAMENTAL TRADE ALERT
════════════════════════════════════════

STATUS:
CANCELLED

Asset:
EURUSD

Previous Bias:
BEARISH

Reason:
fundamental catalyst contradicted the thesis: us_nonfarm_payrolls: contradicts thesis (US_DOVISH)

Do not enter this trade.
════════════════════════════════════════
```

### Machine-readable JSON (one object per re-evaluated opportunity)

```json
{
  "opportunity_id": "b1e2...",
  "recommendation_id": "a9f0...",
  "symbol": "EURUSD",
  "fundamental_bias": "BEARISH",
  "trade_action": "READY_TO_TRADE",
  "direction": "SELL",
  "conviction": 68,
  "conviction_1_10": 7,
  "score": -0.87,
  "threshold": 0.6,
  "trigger_status": "CONFIRMED",
  "trigger_reasons": ["us_nonfarm_payrolls: confirms thesis (US_HAWKISH)"],
  "readiness_reason": "score crosses threshold; conviction floor met; ...",
  "cancellation_reason": null,
  "fundamental_setup_ready": true,
  "readiness_blocker": null,
  "invalidation": "Thesis invalidated if ...",
  "entry": 1.1001,
  "stop_loss": 1.1050,
  "take_profit": 1.0900,
  "risk_reward": 2.0,
  "data_cutoff": "2026-09-01T12:00:00Z",
  "last_evaluated_at": "2026-09-01T13:05:00Z",
  "valid_until": "2026-09-04T23:59:59-06:00",
  "next_catalyst": null,
  "state_changed": true
}
```

## 7. Alerts

`app.monitor.alerts.AlertPolicy` decides which domain events are worth
surfacing (a new `READY_TO_TRADE`, a `CANCELLED`/`EXPIRED`, a fundamental
bias flip, or -- optionally -- a material conviction move) and enforces
idempotency: the same opportunity, in the same state, is never alerted
twice by one running policy instance. Combined with the service only
emitting events when its own `_materially_changed` check finds a real
change against the *persisted* state, re-running `monitor` repeatedly with
no new data never re-sends an alert for a state you already saw.

Only two sinks exist in this version: `ConsoleAlertSink` (prints to
stdout, what the CLI uses by default) and `JsonAlertSink` (appends one JSON
line per alert to a file). `AlertSink` is a small `Protocol`, so a future
channel (email, Slack, a push notification) is a new class implementing
`send(message, *, event)` -- nothing else changes. **No such channel is
wired up in this version** -- there is no Telegram bot, no email sender, no
webhook call anywhere in this codebase.

## 8. Persistence

- `data/monitor/opportunities.jsonl` -- current state, one line per
  opportunity. Re-evaluating one rewrites its line in place
  (read-all/replace/write-all); it is never silently dropped, only
  transitioned.
- `data/monitor/opportunity_events.jsonl` -- append-only audit log. Every
  domain event (`TradeOpportunityCreated/Updated/Ready/Cancelled/Expired`,
  `FundamentalBiasChanged`, `ConvictionChangedMaterially`) is appended,
  never rewritten or deleted, so the full evaluation history is always
  reconstructable independent of current state.

## 9. Journal integration

`RecommendationJournal` entries gain one field, `ready_to_trade_at`, set
the moment a linked opportunity first reaches `READY_TO_TRADE`. On
cancellation, the linked journal entry's `status` is set to
`NOT_TRIGGERED` (if the cause was time-stop expiration) or `CANCELLED`
(if the cause was a contradicting catalyst or a manual skip). None of this
changes `PROPOSED` -> `ACTIVE_SIMULATION` on its own -- that only happens
through the manual acknowledgment commands below.

## 10. Manual acknowledgment -- never sends an order

```bash
uv run python -m app journal enter --opportunity-id <id> --price <price>
uv run python -m app journal skip --opportunity-id <id>
```

`journal enter` records that *you* manually placed the trade in MT5 at the
given price (sets the linked journal entry's status to
`ACTIVE_SIMULATION`); `journal skip` records that you decided not to take
it (`CANCELLED`, `exit_reason=USER_SKIPPED`). Neither command sends,
modifies, or queries any real or simulated broker order -- they only write
to the local journal file. Reaching `READY_TO_TRADE` never triggers either
of these on its own.

## 11. What this is not

- Not a daemon. `monitor` runs once and exits; schedule it yourself.
- Not a notification service. No Telegram, no email, no SMS, no webhook.
- Not a GUI or dashboard.
- Not an auto-trading system. There is no code path that places, modifies,
  or closes a real order in this version, same as `weekly` (`AUTO_EXECUTION`
  is hardcoded `false`). The MT5 price provider (section 2a) is strictly
  read-only -- it never calls `order_send`/`order_check`/`positions_get` or
  any equivalent, verified by `tests/unit/test_no_order_execution_path.py`.
- Not a second decision engine. Every re-evaluation calls the exact same
  `FundamentalDecisionEngine` and scoring pipeline `weekly` uses.
- Not dependent on the optional Claude synthesis layer. Everything in this
  document works identically with or without `ANTHROPIC_API_KEY` set --
  the LLM layer (see README section 15) is narrative-only and is never
  consulted for any state transition described here.

## 12. Known limitations

- Alert deduplication lives in the `AlertPolicy` instance's memory for the
  lifetime of one `monitor` invocation; cross-run idempotency in practice
  comes from the service only emitting an event when the *persisted*
  opportunity state actually changed, not from a separately persisted
  alert ledger.
- `refresh_all` re-evaluates every non-terminal opportunity sequentially,
  each hitting live official sources (or their cache) -- there is no
  batching or rate-limit-aware backoff beyond what each source adapter
  already does for `weekly`.
- Price acquisition is now automatic (`PRICE_PROVIDER=auto` by default,
  section 2a), but the MT5 provider only works on a machine with a real,
  already-logged-in MT5 terminal and the (Windows-only) `MetaTrader5`
  package installed -- on any other machine it fails closed and the manual
  file remains the effective source. If neither produces a fresh quote,
  `READY_TO_TRADE` cannot be reached (the opportunity correctly stays at
  `WAIT` with `readiness_blocker=PRICE_UNAVAILABLE`/`PRICE_STALE` -- gates
  5-7 in section 2) rather than falling back to a guessed price.
- The optional live-terminal broker specs (`tick_size`/`tick_value`/
  `contract_size`/`volume_*`/`stops_level` on `CurrentMarketQuote`) are
  captured for inspection (`python -m app quote`) but position-sizing math
  still uses the fixture-based `SymbolSpec` from `app.broker.mt5_specs` via
  `BrokerSymbolResolver`, not these live values -- a future version could
  prefer the live spec when available.
- No UI/aggregated view across many monitored opportunities beyond what
  `python -m app monitor --all --json-out` produces in one file.
