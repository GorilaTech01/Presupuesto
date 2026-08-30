"""CLI entry point (section 25; monitoring added in V1.1; automatic
execution-price input added in V1.1.1).

python -m app analyze SYMBOL   # quick single-asset fundamental read
python -m app weekly           # full 3-candidate weekly pipeline
python -m app report           # re-render the latest recommendation
python -m app journal          # list journal entries
python -m app journal enter --opportunity-id <id> --price <price>  # record a manual entry
python -m app journal skip --opportunity-id <id>                   # record a manual skip
python -m app evaluate         # paper-trading performance + benchmark export
python -m app monitor          # one fundamental re-evaluation pass over monitored opportunities
python -m app quote SYMBOL     # current bid/ask via PRICE_PROVIDER (never a directional signal)
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from app.broker.symbol_resolver import BrokerSymbolResolver
from app.catalysts.service import CatalystService, annotate_thesis_impact
from app.common.errors import DataSourceUnavailable, StaleDataError, SymbolNotVerifiable
from app.common.event_bus import DomainEvent
from app.common.logging import configure_logging
from app.common.time_utils import format_utc
from app.config.settings import get_settings
from app.domain.enums import JournalStatus
from app.fundamental.candidate import evaluate_candidate, indicators_for_asset
from app.fundamental.decision import FundamentalDecisionEngine
from app.journal.benchmark import export_benchmark_csv, export_benchmark_jsonl
from app.journal.journal import RecommendationJournal
from app.journal.metrics import compute_performance
from app.market.price_router import build_price_provider
from app.market.universe import get_asset
from app.monitor.alerts import AlertPolicy, ConsoleAlertSink
from app.monitor.service import TradeOpportunityMonitorService
from app.monitor.store import OpportunityStore
from app.reporting.human_report import render_human_report
from app.reporting.json_report import to_machine_readable
from app.reporting.monitor_report import render_monitor_report
from app.reporting.monitor_report import to_machine_readable as monitor_to_machine_readable
from app.services.weekly_pipeline import WeeklyPipeline
from app.sources.repository import FundamentalDataRepository

app = typer.Typer(
    add_completion=False, help="Fundamental-only trading advisor (READ/ANALYZE/RECOMMEND/LOG)."
)
console = Console()


@app.command()
def weekly(
    candidates: str = typer.Option(
        "EURUSD,XAUUSD,BTCUSD", help="Exactly 3 comma-separated finalist symbols to compare."
    ),
    json_out: Path | None = typer.Option(
        None, "--json-out", help="Write machine-readable JSON to this path."
    ),
) -> None:
    """Run the full weekly research -> comparison -> decision pipeline."""
    configure_logging()
    settings = get_settings()
    symbols = [s.strip().upper() for s in candidates.split(",") if s.strip()]
    pipeline = WeeklyPipeline(settings)
    try:
        comparison = pipeline.run(symbols)
    finally:
        pipeline.close()

    console.print(render_human_report(comparison, settings.timezone))
    payload = to_machine_readable(comparison)
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(payload, indent=2, default=str))
        console.print(f"\n[dim]Machine-readable JSON written to {json_out}[/dim]")
    else:
        console.print("\n--- JSON ---")
        console.print(json.dumps(payload, indent=2, default=str))


@app.command()
def analyze(
    symbol: str = typer.Argument(..., help="Single asset to analyze, e.g. EURUSD, XAUUSD, BTCUSD."),
) -> None:
    """Quick single-asset fundamental read (no 3-way comparison, not journaled)."""
    configure_logging()
    settings = get_settings()
    symbol = symbol.strip().upper()
    definition = get_asset(symbol)
    repo = FundamentalDataRepository(settings)
    try:
        needed = indicators_for_asset(definition)
        result = repo.fetch_many(needed)
        evaluation = evaluate_candidate(definition, result)
        catalyst_service = CatalystService(repo.fred if settings.fred_api_key else None)
        calendar = catalyst_service.build_calendar(
            needed, timezone_name=settings.timezone, facts=result.facts
        )
        annotated = annotate_thesis_impact(
            calendar, favored_country="US", direction_label="BUY" if evaluation.bias > 0 else "SELL"
        )
        facts_freshness = [result.facts[i].freshness for i in needed if i in result.facts]
        engine = FundamentalDecisionEngine()
        if evaluation.base_score is not None and evaluation.quote_score is not None:
            draft = engine.decide_fx_pair(
                symbol=symbol,
                base_ccy=definition.base_ccy or "",
                quote_ccy=definition.quote_ccy or "",
                base_score=evaluation.base_score,
                quote_score=evaluation.quote_score,
                bias=evaluation.bias,
                catalysts=annotated,
                facts_freshness=facts_freshness or [],
            )
        else:
            draft = engine.decide_single_asset(
                symbol=symbol,
                score=evaluation.score,
                catalysts=annotated,
                facts_freshness=facts_freshness or [],
            )
        console.print(
            f"[bold]{symbol}[/bold]: {draft.direction.value} (conviction {draft.conviction}/100)"
        )
        console.print(draft.thesis)
        console.print("\nWarnings:")
        for w in evaluation.score.warnings:
            console.print(f"  - {w}")
    finally:
        repo.close()


@app.command()
def report(
    recommendation_id: str | None = typer.Option(None, "--id", help="Specific recommendation id."),
) -> None:
    """Re-print the latest (or a specific) journaled recommendation."""
    settings = get_settings()
    journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
    entries = journal.load_all()
    if not entries:
        console.print("[yellow]Journal is empty. Run `weekly` first.[/yellow]")
        raise typer.Exit(code=1)
    entry = journal.find(recommendation_id) if recommendation_id else entries[-1]
    if entry is None:
        console.print(f"[red]No entry with id {recommendation_id}[/red]")
        raise typer.Exit(code=1)
    console.print_json(entry.model_dump_json())


journal_app = typer.Typer(
    add_completion=False, help="List journaled recommendations, or record a manual decision."
)


def _print_journal_table() -> None:
    settings = get_settings()
    journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
    entries = journal.load_all()
    table = Table(title="Recommendation Journal")
    for col in ("id", "generated_at", "asset", "direction", "conviction", "status"):
        table.add_column(col)
    for e in entries:
        table.add_row(
            e.recommendation_id[:8],
            e.generated_at.isoformat(),
            e.asset,
            e.direction.value,
            str(e.conviction),
            e.status.value,
        )
    console.print(table)


@journal_app.callback(invoke_without_command=True)
def journal_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _print_journal_table()


@journal_app.command(name="list")
def journal_list() -> None:
    """List all journaled recommendations."""
    _print_journal_table()


@journal_app.command(name="enter")
def journal_enter(
    opportunity_id: str = typer.Option(
        ..., "--opportunity-id", help="MonitoredTradeOpportunity id."
    ),
    price: float = typer.Option(..., "--price", help="Price at which YOU manually entered in MT5."),
) -> None:
    """Record that you manually entered this trade in MT5. Never sends an order."""
    settings = get_settings()
    store = OpportunityStore(settings.data_dir / "monitor" / "opportunities.jsonl")
    opportunity = store.get(opportunity_id)
    if opportunity is None:
        console.print(f"[red]No monitored opportunity with id {opportunity_id}[/red]")
        raise typer.Exit(code=1)
    if opportunity.trade_action.value != "READY_TO_TRADE":
        console.print(
            f"[yellow]Warning: trade_action is {opportunity.trade_action.value}, "
            "not READY_TO_TRADE. Recording anyway -- this is your call.[/yellow]"
        )
    journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
    try:
        journal.update(
            opportunity.recommendation_id,
            status=JournalStatus.ACTIVE_SIMULATION,
            entry_price_actual_or_simulated=price,
        )
    except KeyError:
        console.print(
            "[red]No journal entry linked to recommendation_id "
            f"{opportunity.recommendation_id}[/red]"
        )
        raise typer.Exit(code=1) from None
    console.print(
        f"Recorded manual entry for {opportunity.symbol} at {price}. "
        "No order was sent -- this only logs that you executed manually in MT5."
    )


@journal_app.command(name="skip")
def journal_skip(
    opportunity_id: str = typer.Option(
        ..., "--opportunity-id", help="MonitoredTradeOpportunity id."
    ),
) -> None:
    """Record that you decided NOT to take this opportunity."""
    settings = get_settings()
    store = OpportunityStore(settings.data_dir / "monitor" / "opportunities.jsonl")
    opportunity = store.get(opportunity_id)
    if opportunity is None:
        console.print(f"[red]No monitored opportunity with id {opportunity_id}[/red]")
        raise typer.Exit(code=1)
    journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
    try:
        journal.update(
            opportunity.recommendation_id,
            status=JournalStatus.CANCELLED,
            exit_reason="USER_SKIPPED",
        )
    except KeyError:
        console.print(
            "[red]No journal entry linked to recommendation_id "
            f"{opportunity.recommendation_id}[/red]"
        )
        raise typer.Exit(code=1) from None
    console.print(f"Recorded: skipped {opportunity.symbol}.")


app.add_typer(journal_app, name="journal")


@app.command()
def monitor(
    opportunity_id: str | None = typer.Option(
        None, "--opportunity-id", help="Re-evaluate only this opportunity."
    ),
    all_opportunities: bool = typer.Option(
        False, "--all", help="Re-evaluate every active opportunity (default when no id is given)."
    ),
    full_refresh: bool = typer.Option(
        False, "--full-refresh", help="Bypass the source cache and force a real re-fetch."
    ),
    json_out: Path | None = typer.Option(
        None, "--json-out", help="Write machine-readable JSON to this path."
    ),
) -> None:
    """Run ONE fundamental re-evaluation pass over monitored opportunities, then exit.

    This is not a daemon and never loops -- schedule it externally (cron,
    Claude/Cowork, systemd timer, ...) if you want periodic checks.
    """
    # refresh_all is also the default behavior with no --opportunity-id
    del all_opportunities
    configure_logging()
    settings = get_settings()
    service = TradeOpportunityMonitorService(settings)
    alert_policy = AlertPolicy(ConsoleAlertSink())

    def _on_event(event: DomainEvent) -> None:
        alert_policy.handle(event)

    service.event_bus.subscribe(_on_event)
    try:
        if opportunity_id:
            opportunity = service.store.get(opportunity_id)
            if opportunity is None:
                console.print(f"[red]No monitored opportunity with id {opportunity_id}[/red]")
                raise typer.Exit(code=1)
            results = [service.refresh_one(opportunity, full_refresh=full_refresh)]
        else:
            results = service.refresh_all(full_refresh=full_refresh)

        if not results:
            console.print("[dim]No active monitored opportunities.[/dim]")
            return

        payloads = []
        for opportunity, state_changed in results:
            console.print(
                render_monitor_report(opportunity, settings.timezone, state_changed=state_changed)
            )
            console.print("")
            payloads.append(monitor_to_machine_readable(opportunity, state_changed=state_changed))

        payload_json = json.dumps(payloads, indent=2, default=str)
        if json_out is not None:
            json_out.parent.mkdir(parents=True, exist_ok=True)
            json_out.write_text(payload_json)
            console.print(f"[dim]Machine-readable JSON written to {json_out}[/dim]")
        else:
            console.print("--- JSON ---")
            console.print(payload_json)
    finally:
        service.close()


@app.command()
def quote(
    symbol: str = typer.Argument(..., help="Asset to quote, e.g. EURUSD, XAUUSD, BTCUSD."),
) -> None:
    """Print the current bid/ask via PRICE_PROVIDER (auto/mt5/manual).

    For inspection only -- this never feeds into fundamental_bias, BUY/SELL
    direction, conviction, or catalyst confirmation. See docs/monitoring.md.
    """
    configure_logging()
    settings = get_settings()
    symbol = symbol.strip().upper()
    resolver = BrokerSymbolResolver()
    provider = build_price_provider(settings)
    try:
        resolved = resolver.resolve(symbol)
    except SymbolNotVerifiable as exc:
        console.print(f"[red]SYMBOL_UNVERIFIED: {exc}[/red]")
        raise typer.Exit(code=1) from None
    try:
        market_quote = provider.get_quote(resolved.broker_symbol)
    except StaleDataError as exc:
        console.print(f"[yellow]PRICE_STALE: {exc}[/yellow]")
        raise typer.Exit(code=1) from None
    except DataSourceUnavailable as exc:
        console.print(f"[red]PRICE_UNAVAILABLE: {exc}[/red]")
        raise typer.Exit(code=1) from None
    console.print(f"Symbol: {symbol}")
    console.print(f"Broker symbol: {resolved.broker_symbol}")
    console.print(f"Bid: {market_quote.bid}")
    console.print(f"Ask: {market_quote.ask}")
    console.print(f"Spread: {market_quote.spread}")
    console.print(f"Timestamp: {format_utc(market_quote.timestamp)}")
    console.print(f"Source: {market_quote.source}")
    console.print(f"Fresh: {'YES' if market_quote.freshness.value == 'FRESH' else 'NO'}")


@app.command()
def evaluate(
    export_csv: Path | None = typer.Option(None, help="Export benchmark.csv to this path."),
    export_jsonl: Path | None = typer.Option(None, help="Export benchmark.jsonl to this path."),
) -> None:
    """Compute paper-trading performance stats and optionally export the benchmark files."""
    settings = get_settings()
    journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
    entries = journal.load_all()
    perf = compute_performance(entries)
    console.print(perf)
    if export_csv:
        export_benchmark_csv(entries, export_csv)
        console.print(f"benchmark.csv written to {export_csv}")
    if export_jsonl:
        export_benchmark_jsonl(entries, export_jsonl)
        console.print(f"benchmark.jsonl written to {export_jsonl}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
