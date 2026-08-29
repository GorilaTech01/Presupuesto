"""Lookahead-bias guard (audit section 8, docs/decision_audit_eurusd_2026-08-31.md).

A backtest or a "what would this system have said" demonstration is only
honest if every input it uses was actually published at or before the
decision timestamp. This module gives that check a name so it can be
called explicitly (and tested) rather than trusted by eyeballing dates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.models import FactObservation


@dataclass
class LookaheadViolation:
    indicator: str
    publication_timestamp: datetime
    decision_time: datetime


def find_lookahead_violations(
    facts: list[FactObservation], decision_time: datetime
) -> list[LookaheadViolation]:
    """Returns every fact whose publication_timestamp is AFTER decision_time.

    An empty list means every fact was `AVAILABLE_AT_DECISION_TIME = True`.
    """
    violations = []
    for fact in facts:
        if fact.publication_timestamp > decision_time:
            violations.append(
                LookaheadViolation(
                    indicator=fact.indicator,
                    publication_timestamp=fact.publication_timestamp,
                    decision_time=decision_time,
                )
            )
    return violations


def assert_no_lookahead(facts: list[FactObservation], decision_time: datetime) -> None:
    """Raises ValueError listing every offending indicator if any fact was
    published after the decision timestamp. Call this before scoring in any
    backtest/demo/replay context.
    """
    violations = find_lookahead_violations(facts, decision_time)
    if violations:
        detail = "; ".join(
            f"{v.indicator} published {v.publication_timestamp.isoformat()} "
            f"> decision_time {v.decision_time.isoformat()}"
            for v in violations
        )
        raise ValueError(f"lookahead bias detected: {detail}")
