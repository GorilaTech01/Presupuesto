"""CLI entry point (section 25).

python -m app analyze SYMBOL   # quick single-asset fundamental read
python -m app weekly           # full 3-candidate weekly pipeline
python -m app report           # re-render the latest recommendation
python -m app journal          # list journal entries
python -m app evaluate         # paper-trading performance + benchmark export
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from app.catalysts.service import CatalystService, annotate_thesis_impact
from app.common.logging import configure_logging
from app.config.settings import get_settings
from app.fundamental.candidate import evaluate_candidate, indicators_for_asset
from app.fundamental.decision import FundamentalDecisionEngine
from app.journal.benchmark import export_benchmark_csv, export_benchmark_jsonl
from app.journal.journal import RecommendationJournal
from app.journal.metrics import compute_performance
from app.market.universe import get_asset
from app.reporting.human_report import render_human_report
from app.reporting.json_report import to_machine_readable
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


@app.command(name="journal")
def journal_cmd() -> None:
    """List all journaled recommendations."""
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
