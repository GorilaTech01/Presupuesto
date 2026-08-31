# Pre-push decision audit: EURUSD, week of 2026-08-31 to 2026-09-04

**Status: a real, reproducible methodological bug was found and fixed.**
The corrected system's answer for this week is **NO_TRADE on all three
candidates** (EURUSD, XAUUSD, BTCUSD), not the SELL EURUSD 8/10 this audit
was triggered to investigate, and not the reference research's LONG
EURUSD either. Neither result was engineered — see section 2 for the bug
and section 3 for the corrected numbers.

Reproduce this audit's numbers: `uv run python scripts/demo_manual_research_run.py`.

---

## 0. What was audited and what changed

| # | Audit item | Finding |
|---|---|---|
| 1 | SELL vs LONG discrepancy | Both were directionally *plausible* narratives, but the SELL 8/10 output was arithmetically dominated by a scoring bug (below), not by a genuinely stronger case. |
| 2 | Real-rate calculation | **Confirmed bug.** The raw nominal policy rate was added to the score unscaled, at 10-20x the magnitude of every other driver. Fixed. |
| 3 | Expectations / priced-in | **Confirmed gap.** No OIS/FedWatch-equivalent data source exists. Now explicitly flagged (`EXPECTATIONS_DATA_INCOMPLETE`) and penalized in conviction, not silently ignored. |
| 4 | Conviction 8/10 | Reconstructed exactly (section 5). It was legitimate arithmetic on top of the buggy score, i.e. "correctly computed, wrong inputs." |
| 5 | Manual demo script | No shortcuts found (section 8). One equivalence test added. |
| 6 | Entry/SL/TP math | No technical analysis found; math re-derived and explained (section 9). Price stop vs. fundamental invalidation vs. time stop are now three explicit, separately-typed objects (`app/risk/policies.py`). |
| 7 | Immediate SELL vs. conditional entry | **Confirmed gap.** `direction=SELL` with a pending CRITICAL catalyst did not, by itself, block "enter now." Fixed with a new `trade_action` field (`ENTER_NOW` / `WAIT_FOR_TRIGGER` / `NONE`), independent of `direction`. |
| 8 | Lookahead bias | Checked and clean: none of the 14 facts used were published after the 2026-08-29 decision timestamp. A reusable `assert_no_lookahead` guard and test were added so this is enforced, not just eyeballed, in any future backtest/demo. |
| 9 | 3-candidate decomposition | Full driver-by-driver breakdown for EURUSD/XAUUSD/BTCUSD in section 4. |

Code changes (see section 10 for the full file list): `app/fundamental/scoring.py`
(bug fix + new expectations driver), `app/fundamental/decision.py` (conviction
breakdown + `trade_action`), `app/domain/enums.py` / `app/domain/models.py`
(new `TradeAction`/`ConvictionBreakdown` types), `app/risk/policies.py` (new),
`app/common/lookahead.py` (new), `app/services/weekly_pipeline.py` (wiring),
`app/reporting/*` (surfacing the new fields), `scripts/demo_manual_research_run.py`
(decomposed output + lookahead check), plus new/updated tests.

**Nothing here was tuned to reach NO_TRADE, SELL, or LONG.** The fix changes
how one driver is *scaled*, not its sign logic, and it was designed by
asking "what makes this comparable to every other driver in the module,"
not "what makes EURUSD do X." The full arithmetic is below so this claim
can be checked line by line rather than taken on faith.

---

## 1. Side-by-side variable table

Values as fed into the corrected demo run (`scripts/demo_manual_research_run.py`),
retrieved 2026-08-29. "Weight" is the fixed, documented scale factor in
`app/fundamental/scoring.py` (same file for every driver, not tuned per run).

| Variable | System value | Source | Data date | Effect on EUR | Effect on USD | Weight/formula | Contribution | Economic read | Reference-thesis read | More defensible? |
|---|---|---|---|---|---|---|---|---|---|---|
| Fed Funds Rate (upper) | 3.75% (held) | Federal Reserve FOMC statement | 2026-07-29 | — | Sets USD nominal-stance driver | `(rate-2.5)*0.15`, clamped ±0.5 | USD nominal stance **+0.19** | Rate above the ~2.5% neutral reference used here → mildly hawkish/currency-supportive | Reference treats a *future* Fed cut path (post weak-NFP) as EUR-supportive-by-relative-effect; doesn't dispute today's level | Both agree on the level; they disagree on its *forward* meaning (see Expectations row) |
| ECB Deposit Facility | 2.25% (held, hiked from 2.00% in June) | ECB Governing Council decision | 2026-07-23 | Sets EUR nominal-stance driver | — | same formula | EUR nominal stance **-0.04** | Barely below the shared 2.5% reference → roughly neutral, not restrictive | Reference cites the ECB's tightening trajectory (June hike) as EUR-supportive momentum | System only sees the *level*, not the *trajectory* (a hike just happened) — a real, disclosed limitation, not a bug |
| PCE price index | **not used** | — (contradictory secondary sources) | — | — | — | — | 0 | N/A | Reference cites "debilidad reciente de payrolls" + inflation broadly, not PCE specifically | Neither system uses PCE as decisive; this is a genuine coverage gap (see section 6/limitations) |
| Core PCE | **CONTRADICTORY, excluded** | Aggregator sites disagreed: 2.9% vs. 3.3% YoY for Jul 2026 | 2026-08-29 (retrieval) | — | — | — | 0 (excluded, not guessed) | Fed's actual preferred gauge is unavailable this run | Reference does not cite a specific core PCE figure either | System is intentionally conservative here (section 33 fail-closed rule): a contradicted number is treated as missing, not averaged/guessed |
| HICP (headline) | 2.9% YoY (prior 2.8%) | Eurostat flash estimate | 2026-08-19 | Feeds EUR inflation driver (via core, see next row) | — | — | — | Eurozone inflation *accelerating*, driven mostly by energy | Reference's LONG thesis explicitly hinges on "inflación de la eurozona" as a EUR-supportive catalyst | Both read rising HICP as *directionally* EUR-relevant; they diverge on whether it's already offset by the ECB's real-rate gap (see below) |
| Core HICP | 2.5% YoY (prior 2.4%) | Eurostat | 2026-08-19 | EUR inflation driver | — | `deviation-from-2%-target * 0.4`, clamped ±0.4 | EUR inflation **+0.20** | Above target → sustains tightening pressure (used as the inflation reference in preference to headline, per `score_inflation`) | Consistent with the reference's inflation argument | Same read, same sign — this row is NOT where the two theses disagree |
| NFP (Jul 2026, actual) | -23k (vs. +83k consensus — a miss) | BLS Employment Situation | 2026-08-07 | — | USD labor driver (as a MoM change) | `clamp(delta_k/300, ±0.3)` | USD labor **contributes to +0.07 total** (net of unemployment + JOLTS, see row below) | A single weak print; U.S. labor loosening at the margin | Reference explicitly cites this as the core EUR-supportive (USD-negative) signal | **This is the crux of the disagreement** — see the boxed discussion after this table |
| Unemployment (US) | 4.1% (prior 4.2%, i.e. *lower*) | BLS | 2026-08-07 | — | USD labor driver | `-delta*0.5` | **+0.05** | Unemployment *fell* the same month NFP missed — a genuinely mixed signal, not unambiguously weak | Reference's framing ("debilidad laboral") emphasizes the NFP miss and doesn't weight the falling unemployment rate | System's labor driver nets both signals instead of picking the one that fits a story; net contribution is a modest USD positive, not negative |
| Wage growth (US, avg hourly earnings) | 3.2% YoY (lowest since May 2021) — **not wired into any scoring function** | BLS Employment Situation | 2026-08-07 | — | — | — | 0 (not modeled) | Cooling wage growth is a genuine dovish-for-USD data point | Reference does not cite this specifically either | **Disclosed gap**: neither system's *scoring* uses wage growth; this audit surfaces it as missing rather than silently absent |
| Revisions | Included where available (e.g. unemployment 4.2%→4.1%, JOLTS ~7.35M→7.40M used as `revised_previous`) | BLS | as above | marginal | marginal | delta-based, see labor row | included above | — | Reference does not discuss revisions explicitly | System structurally distinguishes ACTUAL/PREVIOUS/REVISED (domain model), reference doesn't specify which it used |
| JOLTS | 7.40M openings (~flat, "little changed") | BLS JOLTS | 2026-08-05 (Jun 2026 data) | — | USD labor driver | `clamp(delta/500, ±0.2)` | **+0.10** | Labor demand still solid, not collapsing | Reference cites JOLTS as part of the "diferencial esperado de tasas" case, direction unspecified | Both use it as a labor-tightness gauge; system nets it against NFP instead of treating NFP alone as decisive |
| ISM Manufacturing | **not available** (no free data API; only the *release date* is computed) | n/a | n/a | — | — | — | 0 | Cannot be scored this run | Reference lists ISM among its inputs but doesn't state the reading either | Both are working from an incomplete ISM picture; system's gap is explicit (`app/sources/ism` always raises `DataSourceUnavailable`) |
| ISM Services | **not available** (same reason) | n/a | n/a | — | — | — | 0 | Cannot be scored this run | Same as above | Same as above |
| Treasury 2Y | **not fetched this run** (only used for context in `app.sources.fred`, not wired into `CURRENCY_INDICATORS`) | — | — | — | — | — | 0 | Front-end yield-curve/policy-expectations proxy unused | Reference does not cite 2Y specifically | **Disclosed gap** — see section 6 finding F1 |
| Treasury 10Y | 4.69% | U.S. Treasury / FRB H.15 | 2026-08-28 | — | context only (not separately scored beyond real yield below) | — | 0 direct (feeds real yield) | — | — | — |
| Real yields (10Y TIPS) | 2.34% (prior ~2.43%, i.e. falling) | U.S. Treasury / FRB H.15 | 2026-08-28 | — | XAUUSD driver only (`score_real_yield_and_dollar`) | `-clamp(level*0.25, ±0.5)` for gold | XAU **-0.50** (clamped — level, not the *decline*, dominates this sub-component) | A still-high absolute real yield is a headwind for gold even though it's *falling* | Not part of the EURUSD reference thesis | Flagged limitation (section 6, F2): this driver reacts to the *level*, not the *direction of change*, of real yields — a fall from 2.43%→2.34% doesn't register as "easing" the way it probably should |
| Fed/ECB forward expectations | **not available** — `EXPECTATIONS_DATA_INCOMPLETE` | n/a (no OIS/FedWatch-equivalent source wired) | n/a | 0 | 0 | fixed conviction penalty, see section 5 | 0 to score; **-8 to conviction, always** | Both banks' *next move* is unpriced in this system | Reference's LONG thesis is explicitly framed as *conditional on* upcoming data confirming a dovish Fed path — i.e. it is fundamentally an expectations trade | **This is the second crux of the disagreement** — see boxed discussion |
| Rate differential (current, monetary-policy driver only) | EUR -0.3825 vs. USD +0.1425 → **-0.525** on this driver alone | derived | — | — | — | sum of nominal + real sub-components | -0.525 (one of five EUR/USD driver pairs, not the total) | Real-rate gap is the single largest EUR-negative factor (see boxed discussion) | Reference's rate-differential argument is *directional* (BCE tightening trajectory vs. Fed cutting bias) rather than levels-based | Both are legitimate lenses; system quantifies today's level, reference argues about tomorrow's path |
| Energy/geopolitical risk | **not retrieved this run** | — | — | — | — | — | 0 | Not assessed | Reference does not cite a specific energy/geopolitical driver for this week either | Genuine gap on both sides; `app.sources.eia` exists but wasn't queried for this comparison since neither thesis leans on it |

### Why SELL (pre-fix) and LONG (reference) disagreed: the two real cruxes

1. **NFP miss vs. net labor read.** The reference thesis treats the July NFP
   miss (-23k vs. +83k consensus) as *the* USD-negative signal. The system's
   `score_labor` driver nets NFP against the *same-month* unemployment rate
   *falling* (4.2%→4.1%) and JOLTS holding at ~7.4M, producing a small net
   **positive** USD contribution (+0.07). Both readings are defensible from
   the same data; the system's is an explicit, always-applied netting rule
   (not cherry-picked for this run), the reference's is a narrower,
   single-indicator emphasis. Neither is "wrong" — they're different
   aggregation choices, and this document says so instead of letting one
   hide inside a score.

2. **Current policy vs. priced-in path.** The reference's LONG EURUSD case
   is explicitly *conditional*: it bets that a confirmed dovish shift in
   the Fed's path (plus a hawkish ECB trajectory already in motion) will
   move EURUSD, not that today's levels already justify it. The system has
   **no forward-policy-path data source** (`EXPECTATIONS_DATA_INCOMPLETE`,
   see row above) — it can only score what the policy rate *is today*, not
   what the market thinks it will be in three months. This is why the
   audit added a fixed, always-on conviction penalty for this gap (section
   5) rather than letting the system implicitly claim more forward-looking
   confidence than its inputs support.

**Bottom line:** the reference thesis and the pre-fix system output were
each *internally* defensible readings of a genuinely mixed data set. The
pre-fix SELL's real problem wasn't its reasoning — it was that one
scoring bug (section 2) let a single driver (raw nominal rate) swamp the
other four, so the "explainable" score wasn't actually explaining the
SELL call; it was mostly restating "USD's rate is a higher number."

---

## 2. The real-rate / nominal-rate bug (audit section 2)

**Confirmed: yes, this was happening, and it was worse than the prompt's
hypothesis.** The pre-audit code (`app/fundamental/scoring.py`,
`score_monetary_policy`) was:

```python
nominal_component = policy_rate.value or 0.0  # e.g. 3.75, RAW, UNSCALED
real_component = (policy_rate.value - inflation.value) * 0.5  # e.g. 0.175
contribution = nominal_component + real_component  # e.g. 3.925
```

Every *other* driver in the same module is clamped to roughly ±0.2 to
±0.5 (`score_inflation` clamps to ±0.4, `score_labor`'s sub-terms clamp to
±0.2/±0.3, `score_growth` to ±0.4/±00.2, `score_liquidity_conditions` to
±0.5). `score_monetary_policy` alone added the *raw rate level* — 3.75 for
USD, 2.25 for EUR — directly into a score whose other components live in
the tenths. That's not "the real rate dominates too much," which is what
the audit asked to check for; it's "the *nominal* rate alone was ~95% of
the entire USD score" (3.925 nominal-plus-real component out of a 4.275
total). Inflation, labor, and growth were present in the code and
correctly computed, but numerically irrelevant to the outcome — exactly
the "shortcut hidden inside an aggregate score" the audit was worried
about, confirmed.

It is also exactly the multi-part problem named in section 2 of the audit
request, item by item:

- *"Fed nominal rate - core inflation vs. ECB nominal rate - HICP, without
  considering comparability"* — confirmed: the two real-rate figures were
  computed the same way for both economies and added at full scale, with
  no normalization for the fact that a 0.5-point real-rate gap and a
  1.5-point nominal-rate gap were being combined at 1:1 weight against
  drivers scaled at 1:10.
- *"monetary policy depends on the forward path, not just the current
  rate"* — confirmed gap, addressed in section 5 below (`EXPECTATIONS_DATA_INCOMPLETE`
  + fixed conviction penalty) rather than by inventing a forward-path number.
- *"a simplified ex-post real rate shouldn't dominate the score by
  itself"* — confirmed and fixed (below).

### The fix

`score_monetary_policy` now produces two sub-components, each computed as
a **deviation from a fixed neutral reference**, clamped to the *same*
±0.5 bound every other driver uses:

```python
NEUTRAL_NOMINAL_RATE_REFERENCE = 2.5   # documented approximation, see scoring.py
NEUTRAL_REAL_RATE_REFERENCE = 0.5
POLICY_STANCE_SCALE = 0.15             # same scale as score_liquidity_conditions
REAL_RATE_SCALE = 0.3

policy_stance = clamp((rate - 2.5) * 0.15, ±0.5)
real_rate_stance = clamp(((rate - inflation) - 0.5) * 0.3, ±0.5)
contribution = policy_stance + real_rate_stance
```

This is **not** tuned to produce a particular sign. It was derived from one
requirement only: *"make this driver's typical magnitude match every other
driver's typical magnitude,"* using the same clamp value (±0.5) and a
similar scale factor (0.15) already used elsewhere in the file
(`score_liquidity_conditions`) for an analogous "rate vs. neutral
reference" calculation. The neutral-rate reference (2.5% nominal, 0.5%
real) is a documented simplification — a single shared reference for both
economies — chosen so that using one constant for both currencies cannot
by itself bias a pair toward either side (the same constant is subtracted
from both; see `app/fundamental/scoring.py` module docstring for the full
caveat). A more accurate model would use each central bank's own
published/estimated neutral rate; that is listed as a next step, not
implemented here, because doing so is a data-source/feature addition, and
this audit was scoped to fixing a **methodology bug**, not adding scope.

### Before / after, same inputs

| | USD monetary_policy (pre-fix) | USD monetary_policy (post-fix) | EUR monetary_policy (pre-fix) | EUR monetary_policy (post-fix) |
|---|---|---|---|---|
| Formula | `3.75 + (3.75-3.4)*0.5` | `clamp((3.75-2.5)*0.15) + clamp((0.35-0.5)*0.3)` | `2.25 + (2.25-2.9)*0.5` | `clamp((2.25-2.5)*0.15) + clamp((-0.65-0.5)*0.3)` |
| Value | **3.925** | **0.1425** | **1.925** | **-0.3825** |
| Share of that currency's total score | 92% (3.925 / 4.275) | 34% (0.1425 / 0.4158) | 87% (1.925 / 2.22) | 437%\* |

\* EUR's post-fix total (-0.0875) is small and of mixed sign across
drivers, so "share of total" isn't a meaningful percentage there — which is
itself the point: after the fix, EUR's score is a genuine composite of five
roughly-comparable-sized drivers pulling in different directions, not one
number wearing four decorative ones.

Regression tests: `tests/unit/test_scoring.py::test_score_monetary_policy_uses_real_rate`
(updated for the new formula), `test_score_monetary_policy_is_bounded_like_other_drivers`
(a 15% policy rate can no longer blow past the shared ±1.0 combined bound),
`test_score_monetary_policy_shared_reference_cancels_in_differential` (the
differential between two rates still behaves directionally sensibly under
the new formula).

### 2b. A second bug, found while writing this table

While filling in the NFP row of the section 1 table, the numbers didn't
add up: `score_labor`'s rationale for USD showed only two components
(unemployment, JOLTS) summing to +0.15, silently missing a third
(payrolls/NFP) that the code clearly attempts to compute. Root cause:

```python
if (
    payrolls_level is not None
    and payrolls_level.value is not None
    and payrolls_level.revised_previous        # <-- bare truthiness check
):
```

The demo script models NFP as a "MoM change" fact with a `revised_previous`
baseline of `0` (so `delta_k = value - 0 = value`, i.e. the reported change
itself). But `0.0` is falsy in Python, so `and payrolls_level.revised_previous`
evaluated to `and 0`, and the entire branch was skipped — the -23k NFP miss
that both this system and the reference thesis treat as economically
important was silently dropped from the score, with no warning anywhere.
The same bare-truthiness pattern also affected `job_openings` and
`dollar_index` in `score_real_yield_and_dollar`.

**Fix:** changed all three checks to `is not None` (matching the pattern
already used correctly for `unemployment_rate`, `positioning`, and
`inventories` elsewhere in the same file); added a zero-denominator guard
for `dollar_index` specifically, since that value is also used to divide
(a real 0 there would still need to be skipped, just for a different,
correct reason). This is a plain correctness bug, not a magnitude/scaling
issue like section 2's — it was caught by manually reconciling the
audit table against the code's own printed rationale, which is exactly
the kind of check this whole audit exercise is for.

**Effect on this run:** USD's labor driver moves from +0.1500 to
**+0.0733** (now correctly netting the -23k NFP print: `clamp(-23/300, ±0.3)
= -0.08`), USD's total from +0.4925 to **+0.4158**, and the EURUSD bias
from -0.5800 to **-0.5033**. The decision is unaffected (still NO_TRADE,
`0.50 < 0.6`), which is itself worth noting: fixing a second, independent
bug moved the number but not the conclusion, which is a mild point in
favor of the corrected model's stability rather than its fragility.
Regression tests: `tests/unit/test_scoring.py::test_score_labor_does_not_drop_a_legitimate_zero_baseline`,
`test_score_real_yield_and_dollar_zero_previous_dxy_does_not_crash`.

All figures in sections 1, 4, and 5 below use the numbers **after both
fixes** (bias -0.5033), unless a table/row is explicitly labeled
"pre-fix" or "historical reconstruction."

---

## 3. Expectations / priced-in audit (audit section 3)

**Confirmed gap, now surfaced rather than hidden.** This system has no
OIS, Fed-funds-futures, or FedWatch-equivalent data source (see README
limitations — this was already disclosed before the audit, but wasn't
enforced anywhere in the scoring/conviction math). `direction` for an FX
pair was previously computed purely from `CURRENT_POLICY`-based drivers
with no distinction from `EXPECTED_POLICY_PATH`.

Fix: `app/fundamental/scoring.py::score_market_expectations()` is now
called for every currency/asset and always returns a zero-contribution,
explicitly labeled `EXPECTATIONS_DATA_INCOMPLETE` driver (so it shows up in
the driver list, per section 1's "never hide a methodological difference
inside an aggregate score" rule) — see the `market_expectations` rows in
every candidate's decomposition in section 4. Separately,
`FundamentalDecisionEngine` now always applies a fixed
`EXPECTATIONS_INCOMPLETE_PENALTY = 8` to conviction (section 5), for every
FX/single-asset decision, regardless of direction. This is deliberately a
constant, not a per-run judgment call — a real forward-path data source
would let this become a genuine driver with its own sign; until then, the
honest move is "always penalize the gap the same amount," not "penalize it
only when convenient."

The spec's fallback options were: reduce conviction, mark
`EXPECTATIONS_DATA_INCOMPLETE`, or NO_TRADE if critical. This system does
the first two unconditionally. It does not treat the expectations gap
alone as automatically critical-enough-for-NO_TRADE (many real trades are
legitimately made on current-policy grounds), but the fixed 8-point
conviction haircut plus the explicit driver label means a reader can never
mistake this system's conviction number for one that accounts for the
forward path.

---

## 4. Decomposed candidate scoring (audit section 9)

Full output from `scripts/demo_manual_research_run.py` (corrected code),
run 2026-08-29 for the week of 2026-08-31 to 2026-09-04. Thresholds
(`MIN_BIAS_FOR_TRADE = 0.6`, `MAX_TOLERATED_WARNINGS = 1`) are unchanged
from before this audit, per the instruction not to alter thresholds during
this exercise.

### D. EURUSD

| Currency | Driver | Contribution | Rationale |
|---|---|---:|---|
| EUR | monetary_policy | -0.3825 | Policy rate 2.25% vs. ~2.5% neutral (-0.25pp) → -0.04 nominal; real rate ~-0.65pp vs. ~0.5% neutral (-1.15pp) → -0.34 real-rate stance |
| EUR | inflation | +0.2000 | Core HICP 2.50% vs. 2.0% target (+0.50pp) → tightening pressure |
| EUR | labor | +0.0000 | Unemployment unchanged (6.3% → 6.3%) |
| EUR | growth | +0.0950 | GDP +0.40% QoQ → +0.06; retail sales +0.70% YoY → +0.03 |
| EUR | market_expectations | +0.0000 | EXPECTATIONS_DATA_INCOMPLETE |
| **EUR total** | | **-0.0875** | |
| USD | monetary_policy | +0.1425 | Policy rate 3.75% vs. ~2.5% neutral (+1.25pp) → +0.19 nominal; real rate ~+0.35pp vs. ~0.5% neutral (-0.15pp) → -0.04 real-rate stance |
| USD | inflation | +0.2000 | Core CPI 2.50% vs. 2.0% target (+0.50pp) → tightening pressure |
| USD | labor | +0.0733 | Unemployment -0.10pp → +0.05; NFP -23k MoM change → -0.08; JOLTS +50k → +0.10 |
| USD | growth | +0.0000 | No GDP/retail-sales observation for the US in this run |
| USD | market_expectations | +0.0000 | EXPECTATIONS_DATA_INCOMPLETE |
| **USD total** | | **+0.4158** | |
| **Bias (EUR - USD)** | | **-0.5033** | Favors USD, i.e. a SELL-EURUSD lean |

`|bias| = 0.50 < MIN_BIAS_FOR_TRADE (0.6)` → **NO_TRADE: fundamental
asymmetry too weak.** This is a moderately close call (0.50 vs. 0.6), not a
lopsided one — appropriately so, given how mixed the underlying data is
(see section 1's boxed discussion).

### E. XAUUSD

| Driver | Contribution | Rationale |
|---|---:|---|
| market_expectations (real yields & USD) | -0.2000 | 10Y real yield +2.34% → -0.50 for gold; broad USD index -2.06% → +0.30 for gold |
| inflation | +0.2000 | Core CPI 2.50% vs. 2.0% target → +0.20 |
| supply_demand | +0.0000 | No CFTC gold positioning figure retrieved this run |
| market_expectations (forward path) | +0.0000 | EXPECTATIONS_DATA_INCOMPLETE |
| **Total** | **+0.0000** | |

`|score| = 0.00 < 0.6` → **NO_TRADE.** The real-yield headwind and the
inflation/hedge tailwind happen to cancel almost exactly with this week's
numbers — a genuinely inconclusive setup, not a forced null result.

### F. BTCUSD

| Driver | Contribution | Rationale |
|---|---:|---|
| liquidity | -0.2625 | Policy rate 3.75% vs. ~2% neutral reference → -0.26 (this uses `score_liquidity_conditions`, which was already correctly bounded before this audit) |
| market_expectations | +0.0000 | EXPECTATIONS_DATA_INCOMPLETE |
| **Total** | **-0.2625** | |

`|score| = 0.26 < 0.6` → **NO_TRADE.** Consistent with the spec's explicit
warning that BTC scoring in this version has no verified ETF-flow/on-chain
data and should be read as a low-confidence proxy at best (see
`app.fundamental.analysis.build_btc_score`'s permanent warning).

**None of the three candidates crossed the threshold.** Final pipeline
result for the week: **NO_TRADE.**

---

## 5. Conviction 8/10 audit (audit section 4)

The 8/10 (75/100) conviction from the original run was reconstructed by
hand below, using the **pre-fix** formula (this exact number can no longer
be produced by the corrected code, since EURUSD is now NO_TRADE and
NO_TRADE decisions carry no conviction breakdown by design):

| Step | Pre-fix value | Formula |
|---|---:|---|
| `raw_score` (\|bias\|) | 2.055 | `abs(EUR_total - USD_total)` = `abs(2.22 - 4.275)` |
| `normalized_score` | 41.1 → capped path to 40 | `min(90, 50 + raw_score*20)` = 91.1 → capped at 90 |
| base conviction | 90 | (the pre-fix code had no separate raw/normalized split — this is the reconstruction) |
| `missing_data_penalty` | -10 | 1 missing indicator (`us_core_pce_price_index`) × 10 |
| `source_quality_penalty` (freshness) | 0 | all inputs FRESH |
| `event_risk_penalty` | -5 | 1 CRITICAL catalyst (Sep 4 NFP) pending |
| `expectations_penalty` | **0 (did not exist)** | no such concept pre-fix |
| `contradiction_penalty` | **0 (did not exist)** | no such concept pre-fix |
| **final** | **75 → 8/10** | `90 - 10 - 5 = 75` |

**Was 8/10 "correct" given its inputs? Yes — the arithmetic was right.**
The problem audited in section 2 is that the *raw_score* feeding this
formula (2.055) was itself ~85% attributable to the unscaled nominal-rate
bug, not to a genuine 2-point fundamental gap. So 75/100 was a
mathematically correct answer to the wrong question.

**What would conviction look like under the corrected formula, had EURUSD
still cleared the trade threshold?** (Hypothetical reconstruction only —
the real corrected system returns NO_TRADE and attaches no conviction
breakdown; this is presented purely to show the audit's other requested
components, "should this be penalized for X," in a worked example.)

| Component | Value | Why |
|---|---:|---|
| `raw_score` | 0.5033 | post-fix `\|bias\|` |
| `normalized_score` | 10.07 | `min(40, 0.5033*20)` |
| base | 60.07 | `50 + 10.07` |
| `missing_data_penalty` | -10 | 1 missing indicator (`us_core_pce_price_index`) |
| `source_quality_penalty` | 0 | all inputs FRESH |
| `event_risk_penalty` | -5 | pending NFP |
| `expectations_penalty` | -8 | always applied (section 3) |
| `contradiction_penalty` | -5 | EUR's inflation (+0.20) and growth (+0.095) drivers both point BUY while the hypothetical direction is SELL — 2 disagreeing drivers ≥ the 2-driver threshold |
| **final (floored)** | **55 → 6/10** (floor `MIN_CONVICTION_FOR_TRADE`) | `60.07-10-5-8-5=32.07`, floored to 55 |

So: even in the counterfactual where the corrected score still crossed the
trade threshold, conviction would land at the **floor (55/100, 6/10)**
instead of 75/100 (8/10) — a direct, load-bearing consequence of the
audit's other findings (ISM not automated, no OIS/FedWatch, single
contradicted PCE source, mixed-sign drivers), not a number chosen to look
appropriately humble. `MIN_CONVICTION_FOR_TRADE = 55` was left unchanged
(per the instruction not to alter thresholds in this exercise); note that
it now functions as a real floor being hit, not decoration.

Regression tests: `tests/unit/test_decision_engine.py::test_conviction_breakdown_is_fully_populated_and_matches_conviction`,
`test_no_trade_has_none_trade_action_and_no_conviction_breakdown`.

---

## 6. Additional findings (not blocking, disclosed)

- **F1 — Treasury 2Y unused.** `app/sources/fred/client.py` defines
  `us_2y_yield` but it is never added to `CURRENCY_INDICATORS`, so no
  driver uses it. A 2s10s-style curve signal is a legitimate expectations
  proxy and is a reasonable next step — not implemented here (feature
  addition, out of this audit's scope).
- **F2 — Real yield driver reacts to level, not direction of change.**
  `score_real_yield_and_dollar` scores gold's real-yield component off the
  *absolute* TIPS yield level (clamped), not its recent change. A real
  yield falling from 2.43%→2.34% and a real yield falling from 2.50%→2.34%
  would score identically today even though the *momentum* differs. Flagged
  for a future revision; not changed here because it is a separate,
  narrower issue from the audited bug and changing it now would be a second
  uncontrolled variable in this audit's before/after comparison.
- **F3 — Wage growth is not modeled.** US average hourly earnings (3.2%
  YoY, the lowest since May 2021) was gathered during research but has no
  corresponding driver anywhere in `scoring.py`. Genuine coverage gap.
- **F4 — Energy/geopolitical risk not assessed this run.** `app.sources.eia`
  exists but wasn't queried for the EURUSD comparison since neither the
  system nor the reference thesis leaned on it this week.
- **F5 — `score_inflation`'s "above target = supportive" heuristic doubles
  as a rough expectations proxy** for both EUR and USD this run (both show
  identical +0.20 inflation contributions from core prints exactly 0.5pp
  above target) — worth remembering this driver is doing double duty
  (current stance *and* a crude "pressure to tighten" signal) without a
  separate label for that second job. Not changed here; noted for future
  refinement of the driver taxonomy.

None of these are "shortcuts" in the sense the audit was worried about
(they don't silently manufacture a number) — they are honestly-missing or
narrowly-scoped inputs, each disclosed via a `_missing()` driver or a
warning string rather than a guess.

---

## 7. `trade_action` vs. `direction` (audit section 7)

**Confirmed gap, now fixed.** Before this audit, `FundamentalDecisionEngine`
set `direction = BUY/SELL` as soon as `|bias| >= 0.6` and other checks
passed, and separately built an `entry_condition` string that said
"CONDITIONAL_POST_EVENT... wait for NFP" when a CRITICAL catalyst was
pending — but nothing in the *type system* stopped a caller (the pipeline,
the demo script, a future integration) from reading `direction == SELL` and
treating it as "go short now." The entry-condition text was advisory prose,
not an enforced field.

Fix: `app/domain/enums.py::TradeAction` (`ENTER_NOW` / `WAIT_FOR_TRIGGER` /
`NONE`) is now a first-class field on both `DecisionDraft` and
`FundamentalDecision`. `direction` remains the fundamental bias (matching
the user's example: `fundamental_bias = BEARISH`); `trade_action` says
whether it's executable right now (`ENTER_NOW`, matching the user's
`trade_action = WAIT` example when it isn't). Wired through:

- `FundamentalDecisionEngine._trade_action()`: `NONE` for NO_TRADE,
  `WAIT_FOR_TRIGGER` whenever `_has_critical_unresolved_catalyst()` finds a
  pending CRITICAL event, `ENTER_NOW` otherwise.
- `TradePlan.order_type` now reads *"CONDITIONAL / PENDING -- do NOT enter
  until the trigger confirms..."* instead of *"Market or limit at estimated
  entry"* whenever `trade_action is WAIT_FOR_TRIGGER` (both in
  `app/services/weekly_pipeline.py` and the demo script).
- Both the human report and the JSON report now print `trade_action`
  explicitly, with a warning line in the human report when it's
  `WAIT_FOR_TRIGGER`.

For this specific week the point is moot for the headline result (EURUSD
is NO_TRADE, so `trade_action = NONE`), but the mechanism is real and
tested (`tests/unit/test_decision_engine.py::test_conditional_post_event_entry_when_critical_catalyst_has_consensus`
now asserts `trade_action is WAIT_FOR_TRIGGER`, and
`test_enter_now_when_no_pending_critical_catalyst` asserts the converse) —
future weeks with a cleared threshold and a pending catalyst will now
correctly surface as "bias established, don't enter yet" instead of an
immediately-actionable BUY/SELL.

---

## 8. Lookahead-bias audit (audit section 8)

Checked every one of the 14 facts fed into the demo run: all have
`publication_timestamp <= 2026-08-29T12:00:00Z` (the declared decision
time), which is enforced by a new `app.common.lookahead.assert_no_lookahead()`
call at the top of `scripts/demo_manual_research_run.py::main()` — the
script raises `ValueError` and refuses to run if this is ever violated in
the future (e.g. if someone edits in a fact from after the decision date).
No violation was found in the current data set.

The 2026-09-04 NFP print used in the catalyst calendar is modeled
correctly as *unresolved*: `CatalystEvent(actual=None, consensus=90,
previous=-23)` — the system has the **consensus forecast** (which was
indeed published before 2026-08-29) but not the actual outcome, and
`_has_critical_unresolved_catalyst()` / the `_blocking_reason` /
`trade_action` logic all treat it as pending, never as a resolved input to
the score. This is exactly the CONDITIONAL_POST_EVENT design working as
intended (section 14 of the original spec), verified rather than assumed.

New regression tests: `tests/unit/test_lookahead.py` (5 cases: no
violation, single future-dated fact detected and named, `assert_`-variant
raises with the indicator name in the message, and a same-timestamp fact is
correctly allowed rather than falsely flagged).

---

## 9. Manual demo script audit (audit section 5)

Checklist from the audit request, verified against
`scripts/demo_manual_research_run.py`:

| Requirement | Verified |
|---|---|
| Doesn't skip validation | ✅ Every fact is a real `FactObservation` pydantic model — Pydantic validation runs on construction, same as a live fetch. |
| Doesn't call the decision engine bypassing normalization | ✅ Facts → `FetchResult` → `analysis.build_currency_score`/`build_xau_score`/`build_btc_score` (the *same* normalization/scoring step `WeeklyPipeline` uses) → `FundamentalDecisionEngine`. No shortcut path exists. |
| Uses the exact same models as real sources | ✅ `FactObservation`, `FetchResult`, `CatalystEvent`, `TradePlan` — no parallel/simplified types. |
| Includes source URL, observation/publication dates, retrieval timestamp | ✅ Every fact carries `source_url`, `publication_timestamp`, `observation_period`, `retrieval_timestamp=2026-08-29`. |
| actual/previous/revised/consensus where applicable | ✅ with one clarification: `FactObservation.consensus` is intentionally `None` on every historical fact (July CPI, June JOLTS, etc.) because those are already-realized ACTUALs — consensus is a forward-looking concept and only applies to the still-pending Sep 4 NFP, which is correctly modeled as a `CatalystEvent(consensus=90)`, not a `FactObservation`. This is a modeling choice, not a missing field. |
| No hidden flags forcing BUY/SELL | ✅ Grepped the script: no conditional branches keyed on a desired outcome; `direction`/`trade_action` are 100% outputs of `FundamentalDecisionEngine`. |
| No threshold modification | ✅ `MIN_BIAS_FOR_TRADE`, `MAX_TOLERATED_WARNINGS`, `MIN_CONVICTION_FOR_TRADE` are imported from `app.fundamental.decision`, never overridden in the script. |
| No artificial conviction inflation | ✅ `conviction` / `conviction_breakdown` come straight from the engine's return value; the script only *prints* them. |

**New test added for this section:**
`tests/unit/test_manual_vs_normalized_equivalence.py` proves that a fact
built the way the demo script builds it (by hand, via `FactObservation(...)`)
and a fact built the way a live source client builds it (via
`FredClient.fetch_indicator`, respx-mocked to return the same underlying
value) produce **identical** `DriverScore` and `FundamentalScore` output
when passed through `scoring.score_monetary_policy` /
`analysis.build_currency_score` — i.e. the manual-research path and the
live-API path are provably equivalent once a value is normalized into a
`FactObservation`, not two different code paths that happen to look similar.

---

## 10. SL/TP mathematical justification (audit section 6)

For illustration, using the ORIGINAL (pre-fix) SELL EURUSD trade plan
(entry 1.1582, SL 1.1672, TP 1.1401, R:R 2.0) — the corrected run doesn't
produce a trade plan (NO_TRADE), so this section explains the *mechanism*,
which is unchanged by the audit (the bug was in scoring, not in risk math).

```
mid_price = 1.1583          (approximate spot, 2026-08-28)
spread    = 0.0002          (ask 1.1584 - bid 1.1582)
stop_pct (FX)  = 0.006       # STOP_PCT_BY_CLASS[AssetClass.FX], app/risk/trade_math.py
event widening = 1.3x        # EVENT_RISK_WIDENING_MULTIPLIER, applied because a
                              # CRITICAL catalyst (Sep 4 NFP) falls inside the horizon
stop_distance  = 1.1583 * 0.006 * 1.3 = 0.009035
target_RR      = 2.0         # DEFAULT_TARGET_RISK_REWARD
tp_distance    = 0.009035 * 2.0 = 0.018069

entry (SELL) = mid - spread/2 = 1.1583 - 0.0001 = 1.1582   (approx. bid)
stop_loss    = entry + stop_distance = 1.1582 + 0.009035 = 1.167235 ≈ 1.1672
take_profit  = entry - tp_distance   = 1.1582 - 0.018069 = 1.140131 ≈ 1.1401
risk_reward  = tp_distance / stop_distance = 2.0  (by construction)
```

Confirmed **not** technical: `stop_pct` is a static per-instrument-class
constant (`app/risk/trade_math.py::STOP_PCT_BY_CLASS`), not derived from
ATR, support/resistance, or any price-history window. `take_profit` is
`stop_distance * target_RR`, a fixed multiple, not a chart-derived level.
No candle data, no lookback window, and no technical indicator appears
anywhere in `app/risk/trade_math.py` — confirmed by inspection (the module
docstring states this explicitly and `grep`-ing the file for
`ATR|support|resistance|fibonacci|moving_average` returns nothing).

**Price stop vs. fundamental invalidation, now explicit types** (new,
`app/risk/policies.py`): `PriceStopPolicy` (the numbers above),
`FundamentalInvalidationPolicy` (the *rule*: "thesis invalidated if EUR
fundamentals weaken materially relative to USD... such that the score
differential flips sign" — a statement about the *score*, not about
price), and `TimeStopPolicy` ("close/reassess by Friday market close
regardless of P&L"). These were always three separate fields on
`FundamentalDecision`/`TradePlan`; the audit's contribution is naming them
as three distinct, independently-testable policy objects
(`tests/unit/test_risk_policies.py`) so "what closes this trade" can never
collapse into one undifferentiated "stop" — a thesis can be invalidated
(and should be exited) well before, or after, price ever reaches the
numeric stop-loss.

---

## 11. What was deliberately NOT done

Per the audit's explicit constraints:

- No push, no real account connection, `AUTO_EXECUTION` untouched (still
  hard-blocked at the settings validator and `PepperstoneGateway`).
- No Telegram, no GUI, no integration with any other trading system.
- `MIN_BIAS_FOR_TRADE`, `MAX_TOLERATED_WARNINGS`, `MIN_CONVICTION_FOR_TRADE`
  are byte-for-byte unchanged.
- The monetary-policy fix's scale/reference constants
  (`NEUTRAL_NOMINAL_RATE_REFERENCE`, `NEUTRAL_REAL_RATE_REFERENCE`,
  `POLICY_STANCE_SCALE`, `REAL_RATE_SCALE`) were chosen by matching the
  *existing* magnitude convention already used by `score_liquidity_conditions`
  in the same file — not by trying values until EURUSD produced a
  particular answer. The corrected run's result (NO_TRADE, bias -0.5033)
  was not known until after the formula was fixed and the demo script was
  re-run; no backward tuning occurred.
