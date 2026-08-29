# Fundamental Trading Advisor

A **fundamental-only** trading advisor. It researches macro data, compares
exactly 3 candidate assets, and produces one recommendation: **BUY**,
**SELL**, or **NO_TRADE**. It never uses technical analysis, never sees
price history as a directional signal, and never places real orders.

```
ANALYSIS -> RECOMMENDATION -> YOU DECIDE -> MANUAL EXECUTION IN MT5
```

This is a standalone project. It does not import from, depend on, or modify
any other trading system in this repository.

## 1. Objective

Given the current macro backdrop (monetary policy, inflation, employment,
growth, geopolitics), pick the single best fundamental opportunity among 3
finalist candidates for the coming ~1 week, or say **NO_TRADE** if none is
defensible. Every recommendation is logged so it can later be benchmarked
against another trading system.

## 2. Absolute rule: fundamental only

No RSI, MACD, moving averages, Bollinger Bands, ATR, Fibonacci, support/
resistance, candlestick patterns, order blocks, market structure, or any
other price-history-derived signal is used to decide direction or pick an
asset. The current price is used **only** to: compute entry/SL/TP,
distance to SL/TP, risk sizing, and check spread/broker restrictions. It is
never used to infer that an asset "should" go up or down.

## 3. Architecture

```
DATA SOURCES (FRED, ECB, Eurostat, BLS, EIA, CFTC, ...)
        v
NORMALIZED FACTS  (app.domain.models.FactObservation)
        v
DETERMINISTIC SCORING  (app.fundamental.scoring / analysis)
        v
CATALYST CALENDAR  (app.catalysts.service)
        v
DECISION ENGINE  (app.fundamental.decision.FundamentalDecisionEngine)
        v
[optional] CLAUDE SYNTHESIS -- narrative only, validated, never a data source
        v
RISK / TRADE MATH  (app.risk.trade_math) -- no technical levels
        v
STRUCTURED DECISION + TRADE PLAN  (app.domain.models.FundamentalDecision)
        v
HUMAN REPORT + JSON + JOURNAL  (app.reporting / app.journal)
```

Directory layout:

```
app/
  common/        logging, time/timezone utils, disk cache, exceptions
  config/        pydantic-settings configuration (.env)
  domain/        typed models & enums shared across the whole pipeline
  sources/       one adapter per official data source (see section 5)
  fundamental/   scoring primitives, per-asset analysis, decision engine
  catalysts/     7-day forward event calendar + severity classification
  market/        tradable universe metadata, price provider
  broker/        MT5 symbol/spec fixtures, execution-blocking gateway
  risk/          SL/TP construction (no technical analysis) + position sizing
  journal/       RecommendationJournal, benchmark export, performance metrics
  reporting/     human-readable report + machine-readable JSON
  llm/           optional Claude synthesis layer + strict output validator
  services/      WeeklyPipeline -- the only module allowed to orchestrate all of the above
  cli/           `analyze` / `weekly` / `report` / `journal` / `evaluate`
tests/
  unit/          one file per module, no real network calls (respx/fixtures)
  integration/   full pipeline + CLI, still no real network calls
  fixtures/      sample API payloads used by source-client tests
config/
  central_bank_calendar_2026.yaml   publicly pre-announced FOMC/ECB meeting dates
```

## 4. Installation

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
cd fundamental-trading-advisor
uv sync
cp .env.example .env   # then fill in what you have (all optional)
```

## 5. Configuration (`.env`)

| Variable | Purpose | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Optional narrative synthesis layer (never a data source) | unset (disabled) |
| `FRED_API_KEY` | Free key for FRED (US rates, CPI, PCE, NFP, JOLTS, yields, DXY) | unset |
| `EIA_API_KEY` | Free key for EIA (oil/energy context) | unset |
| `MT5_ENABLED` | Enables a future read-only MT5 connection (not implemented yet) | `false` |
| `AUTO_EXECUTION` | **Hard-blocked.** Setting `true` raises a config error at startup. | `false` |
| `PAPER_TRADING` | Marks the journal as paper-trading mode | `true` |
| `ACCOUNT_EQUITY` | Used for position sizing; omit to skip sizing | unset |
| `RISK_PERCENT` | Fraction of equity risked per trade; capped at 1% (`AGGRESSIVE_MAX`) | `0.005` (0.5%, MODERATE) |
| `TIMEZONE` | Local timezone for display | `America/Costa_Rica` |

Risk profiles (`app.config.settings.RiskProfile`): `CONSERVATIVE=0.25%`,
`MODERATE=0.50%`, `AGGRESSIVE_MAX=1.00%`. The settings validator refuses to
start above 1%, and refuses `AUTO_EXECUTION=true` outright.

## 6. Fundamental sources -- implemented

Free-first, official sources only:

| Source | Used for | Auth |
|---|---|---|
| **FRED** (`app/sources/fred`) | Fed funds target, CPI/core CPI/PCE/core PCE (YoY, derived), unemployment, NFP, JOLTS, initial claims, 10Y/2Y yields, real 10Y yield, broad USD index, plus US official release-date calendar | free API key |
| **ECB Data Portal / SDW** (`app/sources/ecb`) | Deposit facility & MRO rates, HICP headline/core YoY | none |
| **Eurostat** (`app/sources/eurostat`) | Eurozone unemployment, GDP growth, retail sales | none |
| **BLS public API v1** (`app/sources/bls`) | Cross-check for CPI/unemployment/NFP (25 queries/day limit, not primary) | none (unregistered tier) |
| **EIA** (`app/sources/eia`) | WTI spot price, crude stocks (commodity/oil context) | free API key |
| **CFTC** (`app/sources/cftc`) | Net non-commercial futures positioning (EUR, gold) via Socrata | none |
| Central bank meeting calendar (`config/central_bank_calendar_2026.yaml`) | FOMC & ECB Governing Council decision dates | static config, official published schedule |
| ISM release dates | Computed via the well-known "1st/3rd business day of month" convention | n/a (see limitations -- no free ISM *data* API) |

Every adapter fails closed: on any HTTP error, missing key, or unexpected
response shape it raises `DataSourceUnavailable` and is recorded per
indicator. Nothing is ever synthesized to fill a gap.

## 7. Fundamental sources -- pending

- **ISM Manufacturing/Services PMI values**: ISM has no free, keyless
  machine-readable API for the actual index values (only the release
  *dates* can be computed deterministically). `app/sources/ism` is a typed
  stub that always raises `DataSourceUnavailable`; wiring a licensed feed
  or a manual-entry workflow is future work.
- **BEA direct integration**: FRED already mirrors BEA's key series (GDP,
  PCE), so `app/sources/bea` is a stub pointing at FRED instead of
  duplicating the integration.
- **U.S. Treasury, SEC, OPEC, BoE, BoJ, ONS, Japan Statistics Bureau**:
  listed in the target architecture but not yet implemented; only US (FRED/
  BLS) and Eurozone (ECB/Eurostat) fundamentals are wired, matching the
  EUR/USD-heavy validation case. Adding a country means adding one adapter
  + one entry in `app.fundamental.analysis.CURRENCY_INDICATORS`.
- **News/geopolitical research layer**: `app/sources/news/provider.py`
  defines the `NewsResearchProvider` interface and ships only a disabled
  `NullNewsResearchProvider`. No scraping of Reuters/Bloomberg/FT is wired
  up; this is intentionally optional per the spec.
- **Options-implied expected move** for SL/TP sizing: not implemented;
  SL/TP currently use a preconfigured percent-of-price band, widened around
  CRITICAL catalysts (see `app/risk/trade_math.py`).
- **Crypto-specific fundamentals** (verified ETF flows, on-chain supply):
  no free, reliable structured source is wired; BTC/ETH scoring currently
  uses only the Fed-funds liquidity proxy and is flagged with an explicit
  warning every time it runs.

## 8. A note on network access in sandboxed/CI environments

This project's own dev/CI sandbox blocks outbound HTTPS to third-party
hosts (FRED, ECB, Eurostat, etc. all return connection-refused there). This
is exactly the situation section 33's fail-closed design is meant for: with
no reachable source and no API keys, every adapter raises
`DataSourceUnavailable`, and the pipeline correctly produces **NO_TRADE**
end-to-end instead of crashing or guessing. Run this on a machine with
normal internet access (your own laptop/server) to get live data; nothing
in the code assumes internet access is available, and nothing silently
degrades when it isn't.

## 9. CLI

```bash
uv run python -m app weekly                       # full 3-candidate pipeline
uv run python -m app weekly --candidates EURUSD,GBPUSD,XAUUSD
uv run python -m app analyze EURUSD                # quick single-asset read (not journaled)
uv run python -m app report                        # re-print latest recommendation
uv run python -m app journal                        # list all journaled recommendations
uv run python -m app evaluate --export-csv benchmark.csv --export-jsonl benchmark.jsonl
```

`weekly` always compares **exactly 3** finalists, always prints the human
report (section-26 format) followed by machine-readable JSON, and always
appends one entry to the journal -- including `NO_TRADE` runs.

## 10. Human-readable output

See `app/reporting/human_report.py`. Example shape:

```
══════════════════════════════
FUNDAMENTAL TRADING ADVISOR
══════════════════════════════
DATE / DATA CUTOFF (UTC + America/Costa_Rica)
CANDIDATES CONSIDERED (exactly 3, with reasons)
SELECTED ASSET / DECISION / CONVICTION (1-10) / HORIZON
WHY (top explainable drivers)
MAIN CATALYST / ENTRY CONDITION / ENTRY / SL / TP / R:R
INVALIDATION / DO NOT ENTER IF / TIME STOP / NEXT EVENT TO WATCH
SOURCES
══════════════════════════════
```

## 11. Machine-readable output

`app/reporting/json_report.py` builds the JSON directly from the same typed
`FundamentalDecision`/`WeeklyComparison` objects the human report uses, so
the two can never drift apart. Shape matches section 27 of the spec
(`decision`, `symbol`, `conviction`, `entry`, `stop_loss`, `take_profit`,
`risk_reward`, `catalysts`, `drivers`, `sources`, `data_cutoff`, ...).

## 12. Risk & position sizing (no technical analysis)

`app/risk/trade_math.py`: SL distance = a preconfigured percent-of-price
band per instrument class (FX 0.6%, metals 1.2%, indices 1.5%, crypto
4.5%), widened 1.3x when a CRITICAL catalyst falls inside the horizon. TP
distance = SL distance x target R:R (default 2.0). If R:R would fall below
**1.5**, or the spread is too wide relative to the stop, the trade is
rejected as infeasible and the decision is downgraded to `NO_TRADE`.
Position sizing: `risk_money = equity * risk_percent`; lots are derived
from the broker's tick value/size (see `app/broker/mt5_specs.py`), rounded
to the instrument's volume step and clamped to its min/max.

## 13. Paper trading & the RecommendationJournal

Every run appends one entry to `data/journal/journal.jsonl`
(`app/journal/journal.py` / `models.py`). Statuses: `PROPOSED`,
`NOT_TRIGGERED`, `ACTIVE_SIMULATION`, `STOPPED`, `TAKE_PROFIT`,
`FUNDAMENTAL_EXIT`, `TIME_EXIT`, `CANCELLED`. Producing those outcomes
(replaying real market data against a proposed plan) is a decoupled
paper-trade evaluator that is **not** built in this version -- see
Limitations. `app/journal/metrics.py` aggregates whatever outcomes already
exist into win rate, average R, profit factor, expectancy, and breakdowns
by direction/asset/conviction bucket.

## 14. Benchmark export

```bash
uv run python -m app evaluate --export-csv data/journal/benchmark.csv --export-jsonl data/journal/benchmark.jsonl
```

Both files use exactly the cross-system comparison schema (`Date, System,
Asset, Direction, Entry, Exit, SL, TP, R, PnL, Conviction, TradeDuration,
ExitReason`) with `System = FUNDAMENTAL_ONLY`, so this project's
recommendations can be compared line-for-line against a different trading
system's own export in the same format.

## 15. The LLM layer is optional and cannot invent data

If `ANTHROPIC_API_KEY` is set, `app/llm/claude_synthesis.py` asks Claude to
turn already-computed drivers/scores/catalysts into a short narrative.
`app/llm/validator.py` then extracts every number in that narrative and
rejects it (falling back to the deterministic thesis text) if any number
isn't traceable to what Claude was given. With no key configured, the
system runs identically minus this optional narrative.

## 16. How to add a new asset

1. Add an `AssetDefinition` to `app/market/universe.py` (base/quote
   currency, relevant countries, broker symbol candidates).
2. Add a `SymbolSpec` fixture to `app/broker/mt5_specs.py` (verify against
   your own MT5 terminal).
3. If it's a new currency, add its indicator list to
   `app.fundamental.analysis.CURRENCY_INDICATORS` and a `build_..._score`
   function following the pattern of `build_currency_score`.
4. If it needs new source data, add/extend an adapter under `app/sources/`.

## 17. How to add a new data source

1. Create `app/sources/<name>/client.py` implementing
   `fetch_indicator(self, indicator: str) -> FactObservation`, using
   `app.sources.base.OfficialSourceClient` for HTTP + caching, and raising
   `DataSourceUnavailable` on any failure.
2. Register its indicators in `app.sources.repository._OWNER`.
3. Add fixture-based unit tests (respx-mocked, no real network calls).

## 18. Testing & quality gates

```bash
uv run pytest            # 99 tests, no real network calls (respx + fixtures)
uv run ruff check .
uv run ruff format --check .
uv run mypy app
git diff --check
```

All four gates pass as of this version.

## 19. Example run with real data (`scripts/demo_manual_research_run.py`)

`weekly` calls live official APIs; if you're on a network that blocks them
(as the sandbox this project was built in does) it will correctly fail
closed to `NO_TRADE`/`ANALYSIS_INCOMPLETE` rather than guess -- that's the
architecture working as intended. To see what the scoring/decision engine
actually does with real numbers, run:

```bash
uv run python scripts/demo_manual_research_run.py
```

This feeds real, hand-researched figures for the week of 2026-08-31 to
2026-09-04 (each cited with its source in the script's docstring) through
the exact same `analysis` / `catalysts` / `decision` / `risk` modules
`weekly` uses -- it does not call any network API itself. It is a fixed
historical demonstration, not a live command.

## 20. Limitations (current version)

- Several official sources are pending (see section 7 above): ISM PMI
  values, direct BEA/Treasury/SEC/OPEC/BoE/BoJ/ONS integrations.
- No live MT5 connection; prices come from a manually-maintained
  `data/manual_prices.json` (see `app/market/price_provider.py`) until a
  real Market Watch read is wired up. **Always re-verify price, spread,
  and exact symbol name in MT5 before executing manually.**
- No paper-trade evaluator that replays real market data against a
  proposed plan to auto-populate exit/PnL/R-multiple; `evaluate` only
  aggregates whatever outcomes are already recorded.
- Scoring is an explainable heuristic (documented thresholds in
  `app/fundamental/scoring.py`), not a calibrated econometric model --
  treat conviction as "how clean is the story", not a probability.
- Catalyst *dates* for FOMC/ECB come from a static, manually-updated
  config file; US release dates come from FRED's release-calendar API
  when a `FRED_API_KEY` is configured.
- Currency scoring models are implemented for USD and EUR only; GBP, JPY,
  AUD, CHF, CAD are in the tradable universe list but will raise until
  their indicator sets and scoring are added (section 16 above).

## 21. Next steps (recommended)

1. Add GBP/JPY/AUD/CHF/CAD currency scoring so the "exactly 3 finalists"
   selection can eventually be drawn from the full universe automatically
   rather than specified on the command line.
2. Wire a real MT5 read-only connection for live bid/ask/spread/spec.
3. Build the decoupled paper-trade evaluator (replay real historical
   prices against `PROPOSED` journal entries to populate exit/PnL/R).
4. Add a licensed or manual-entry ISM PMI feed.
5. Add BoE/ONS and BoJ/Japan Statistics Bureau adapters to support GBPUSD
   and USDJPY theses.

## 22. Disclaimer

This is a research/decision-support tool, not investment advice. It does
not predict outcomes, does not guarantee returns, and does not manage risk
beyond the parameters you configure. `AUTO_EXECUTION` is hardcoded off and
there is no code path in this version capable of sending a real order --
every recommendation requires a human to read it, decide, and execute
manually in MetaTrader 5. Past data does not guarantee future results.
Trading leveraged FX/CFD products carries a high risk of loss.
