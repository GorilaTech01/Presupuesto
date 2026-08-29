"""RecommendationJournal: append-only structured log of every recommendation.

Used later to benchmark this project's recommendations against another
trading system (section 23-24). Every `weekly`/`analyze` run appends
exactly one entry, including NO_TRADE runs are NOT journaled as trades but
may optionally be logged separately by the caller for audit purposes.
"""

from __future__ import annotations

from pathlib import Path

from app.journal.models import JournalEntry


class RecommendationJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, entry: JournalEntry) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

    def load_all(self) -> list[JournalEntry]:
        if not self.path.exists():
            return []
        entries = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entries.append(JournalEntry.model_validate_json(line))
        return entries

    def update(self, recommendation_id: str, **fields: object) -> JournalEntry:
        entries = self.load_all()
        updated: JournalEntry | None = None
        for i, entry in enumerate(entries):
            if entry.recommendation_id == recommendation_id:
                merged = entry.model_copy(update=fields)
                entries[i] = merged
                updated = merged
                break
        if updated is None:
            raise KeyError(f"no journal entry with recommendation_id={recommendation_id}")
        with self.path.open("w", encoding="utf-8") as f:
            for e in entries:
                f.write(e.model_dump_json() + "\n")
        return updated

    def find(self, recommendation_id: str) -> JournalEntry | None:
        for entry in self.load_all():
            if entry.recommendation_id == recommendation_id:
                return entry
        return None
