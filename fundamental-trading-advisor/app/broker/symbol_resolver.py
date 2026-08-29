"""BrokerSymbolResolver (section 20).

Broker symbol naming varies (suffixes like `.a`, `m`, `-ECN`, etc.), so this
never assumes a single canonical name is universally correct. It resolves
against a configured/fixture candidate list and always attaches the
verification notice.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.broker.mt5_specs import VERIFY_SYMBOL_NOTICE, SymbolSpec, get_spec
from app.common.errors import SymbolNotVerifiable
from app.market.universe import get_asset


@dataclass
class ResolvedSymbol:
    asset: str
    broker_symbol: str
    spec: SymbolSpec
    notice: str = VERIFY_SYMBOL_NOTICE


class BrokerSymbolResolver:
    """Resolves an internal asset name to a broker/MT5 symbol.

    In this version resolution is fixture-based (see app.broker.mt5_specs).
    When a live MT5 connection exists, this is the seam where a real
    `symbol_info`/Market Watch lookup would replace the fixture lookup.
    """

    def resolve(self, asset: str) -> ResolvedSymbol:
        definition = get_asset(asset)
        primary_candidate = definition.broker_symbol_candidates[0]
        try:
            spec = get_spec(primary_candidate)
        except KeyError as exc:
            raise SymbolNotVerifiable(asset) from exc
        return ResolvedSymbol(asset=asset, broker_symbol=primary_candidate, spec=spec)
