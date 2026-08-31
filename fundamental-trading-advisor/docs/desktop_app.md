# Desktop App (V1.2 — Control Panel)

A local desktop GUI (PySide6/Qt) that sits on top of the exact same engine
the CLI uses. It is a **presentation layer only**: every button calls one
of the existing services (`WeeklyPipeline`, `TradeOpportunityMonitorService`,
the journal, `PriceProvider`) through a thin controller in
`app/desktop/controllers.py` — nothing here re-scores, re-thresholds, or
reinterprets a decision, and nothing here places an order.

```
ANALYSIS -> RECOMMENDATION -> YOU DECIDE -> MANUAL EXECUTION IN MT5
```

The desktop app changes none of that. It just gives you a window instead
of a terminal.

## 1. Install

From the project root, with [uv](https://docs.astral.sh/uv/) installed:

```bash
uv sync
```

This installs PySide6 (the GUI toolkit) along with everything the CLI
already needed. No new backend server, no database, no internet
connection is required to render the UI itself (only the analysis engine
itself needs the network, exactly as it already did for the CLI).

## 2. Start the app

```bash
uv run python -m app desktop
```

or, equivalently:

```bash
uv run python scripts/run_desktop.py
```

On Windows, you can also double-click **`run_desktop.bat`** in the project
root (it just runs the command above from that folder).

The window title is **"Fundamental Trading Advisor"**.

## 3. Layout

A left sidebar switches between five screens:

- **Dashboard** — today's status at a glance, plus the two primary
  actions (below), plus the full trade plan when one is READY_TO_TRADE.
- **Daily Analysis** — the full 3-candidate weekly comparison behind
  today's Dashboard summary (scores, thesis, top drivers).
- **Opportunities** — every monitored opportunity (past and present) in
  a table, with a detail panel (Overview / Catalysts / History / Sources)
  for the selected row.
- **Journal** — a read-only render of `data/journal/journal.jsonl`.
- **Settings & System Status** — read-only configuration and health
  summary (see section 7 below).

## 4. What each button does

| Button | Does exactly the same thing as | Notes |
|---|---|---|
| **Run Daily Analysis** | `python -m app daily` | Runs the full weekly pipeline + refreshes every monitored opportunity. Runs on a background thread — the window stays responsive; the button is disabled and shows "Running analysis…" while it works. |
| **Re-check Opportunities** | `python -m app monitor --all` | Re-evaluates every persisted opportunity against current data. Also runs on a background thread. |
| **Refresh UI Data** (Opportunities/Journal/Settings screens) | Nothing new — just re-reads what's already on disk | Distinct from the two buttons above: it never calls the pipeline, MT5, or any network API. Use it after switching screens if you want the latest saved state re-rendered. |
| **I Entered This Trade** | `python -m app journal enter --opportunity-id ... --price ...` | Only visible when an opportunity is READY_TO_TRADE. Asks for the actual fill price you got in Pepperstone/MT5, validates it's a positive number, then records it in the journal. **Never sends an order** — it only records what you already did manually. |
| **Skip Trade** | `python -m app journal skip --opportunity-id ...` | Asks for confirmation, then marks the opportunity CANCELLED and the linked journal entry CANCELLED. |

There is no buy/sell/submit button anywhere in the app, and no setting
that enables one.

## 5. Status meanings

| Status | Meaning |
|---|---|
| **WAIT** | A fundamental bias exists but the entry trigger hasn't confirmed yet. |
| **READY_TO_TRADE** | The trigger confirmed and a full manual trade plan is available (see the Dashboard). |
| **NO_TRADE** | No tradable fundamental edge was found. |
| **CANCELLED** | The opportunity was invalidated by a contradicting catalyst, expired, or you chose "Skip Trade". |
| **NO_CHANGE** (re-check result) | The opportunity was re-evaluated and nothing about its state changed. |

Colors are a presentation-only convenience (`app/desktop/theme.py`) — the
underlying state machine has no concept of color and is unaffected by it.

## 6. Recording a trade you took manually

1. Wait for **READY_TO_TRADE** on the Dashboard.
2. Read the plan: entry, stop loss, take profit, R:R, invalidation, valid
   until. **Verify the price, spread, and exact symbol in Pepperstone/MT5
   yourself before entering anything** — the app does not check this for
   you and does not know your broker's live quote.
3. Place the trade manually in MT5.
4. Back in the app, press **"I Entered This Trade"** and enter the actual
   price you were filled at.
5. The journal entry is updated; check the **Journal** screen to confirm.

If you decide not to take the trade, press **"Skip Trade"** instead.

## 7. Settings & System Status screen

Read-only in this phase — nothing on this screen can change a setting.
It shows:

- Application version, fundamental engine health (OK/ERROR).
- Price provider mode (MT5 / MANUAL / UNAVAILABLE) and whether MT5 is
  enabled.
- MT5 terminal AVAILABLE/UNAVAILABLE — only probed when MT5 is enabled in
  `.env`; if MT5 is disabled this reads "not applicable" rather than an
  error, since a disabled MT5 integration is expected, not broken.
- **Auto Execution: DISABLED** — always, with no control to change it.
- Paper trading flag, timezone, risk percent, account equity, max quote
  age.
- Which data sources are configured — **never** the API key/token values
  themselves, only whether one is present.

## 8. MT5-unavailable behavior

If `MT5_ENABLED=false` (the default) or no MT5 package/terminal is
present, the app never treats this as a fatal error: System Status simply
shows MT5 as disabled/unavailable and the rest of the app (fundamental
analysis, journal, opportunities) works exactly the same, using the
manual price provider instead.

## 9. Errors

Data-source failures never crash the app and never get silently turned
into a trade signal: a failed source shows up as "Analysis incomplete"
with the reason, and the affected candidate/opportunity stays at
NO_TRADE/WAIT. Invalid input (e.g. a non-numeric entry price) shows a
plain-language dialog naming the actual problem rather than a raw
exception or an unhelpful "Something went wrong".

## 10. Logs

There is no dedicated desktop log file in this phase (errors are shown as
in-app dialogs rather than only written to disk). If you add file logging
later, keep it at `logs/desktop.log` and never write API keys, passwords,
tokens, or MT5 credentials to it, consistent with the rest of the project.

## 11. Known limitations

- **Risk Amount / Position Size** are not shown on the READY_TO_TRADE
  card (rendered as "—"). The pipeline computes them transiently at
  decision time (`app.risk.trade_math.build_trade_math`) but does not
  currently persist them onto the stored `TradePlan`, so the desktop app
  — which only presents already-persisted fields and never recomputes
  risk math itself — has nothing to read back. Recompute them yourself
  from the shown entry/stop distance and your own account settings, or
  treat this as a candidate for a future phase that persists those two
  fields.
- No packaged `.exe` yet — this phase runs from Python via `uv run`.
- No dark/light theme toggle; the app ships with a single dark,
  trading-desk-style theme.
- The Daily Analysis and Opportunities screens do not auto-refresh while
  open; use "Refresh UI Data" or re-run the relevant action.
