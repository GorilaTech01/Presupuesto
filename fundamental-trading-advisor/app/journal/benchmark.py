"""Exports the journal to the cross-system comparison format (section 24)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from app.journal.models import SYSTEM_NAME, JournalEntry

BENCHMARK_FIELDS = [
    "Date",
    "System",
    "Asset",
    "Direction",
    "Entry",
    "Exit",
    "SL",
    "TP",
    "R",
    "PnL",
    "Conviction",
    "TradeDuration",
    "ExitReason",
]


def _row(entry: JournalEntry) -> dict[str, object]:
    duration = None
    return {
        "Date": entry.generated_at.date().isoformat(),
        "System": SYSTEM_NAME,
        "Asset": entry.asset,
        "Direction": entry.direction.value,
        "Entry": entry.entry_price_actual_or_simulated
        if entry.entry_price_actual_or_simulated is not None
        else entry.recommended_entry,
        "Exit": entry.exit_price,
        "SL": entry.stop_loss,
        "TP": entry.take_profit,
        "R": entry.r_multiple,
        "PnL": entry.pnl_percent,
        "Conviction": entry.conviction,
        "TradeDuration": duration,
        "ExitReason": entry.exit_reason,
    }


def export_benchmark_csv(entries: list[JournalEntry], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=BENCHMARK_FIELDS)
        writer.writeheader()
        for entry in entries:
            writer.writerow(_row(entry))


def export_benchmark_jsonl(entries: list[JournalEntry], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(_row(entry), default=str) + "\n")
