"""Security audit (V1.1.1 spec section 13): the production application must
contain no callable order-execution path, in this file or any other.

This walks every `.py` file under `app/` (never `.venv/` or any installed
dependency -- a third-party library's own vocabulary, e.g. a syntax
highlighter's MQL keyword list, is not this project's code) and asserts
none of the forbidden order-execution names appear anywhere in production
code. The only places these strings may legitimately appear in the whole
repository are: this test (verifying the prohibition), other test files
that assert the same prohibition, and docstrings/comments that explicitly
document the prohibition (e.g. `app/broker/pepperstone.py`,
`app/market/mt5_provider.py`) -- so the check here is on `app/` source
files' *executable* use, not a blanket string ban.
"""

from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"

FORBIDDEN_ORDER_EXECUTION_NAMES = (
    "order_send",
    "order_check",
    "positions_get",
    "orders_get",
    "TRADE_ACTION_DEAL",
    "TRADE_ACTION_PENDING",
)

# These files' docstrings/comments *name* the forbidden strings specifically
# to document and enforce their prohibition -- that is not a violation.
_ALLOWED_DOCUMENTATION_FILES = {
    "app/broker/pepperstone.py",
    "app/market/mt5_provider.py",
}


def _all_app_python_files() -> list[Path]:
    return sorted(APP_ROOT.rglob("*.py"))


def test_no_order_execution_calls_anywhere_in_app() -> None:
    violations: list[str] = []
    for path in _all_app_python_files():
        rel = path.relative_to(APP_ROOT.parent).as_posix()
        text = path.read_text(encoding="utf-8")
        for name in FORBIDDEN_ORDER_EXECUTION_NAMES:
            if name not in text:
                continue
            if rel in _ALLOWED_DOCUMENTATION_FILES:
                # Confirm every occurrence is inside the module docstring
                # (a prohibition notice), not a live call -- the docstring
                # is always the first statement in these two files.
                docstring_end = text.find('"""', text.find('"""') + 3) + 3
                remaining_occurrences = text[docstring_end:].count(name)
                if remaining_occurrences > 0:
                    violations.append(f"{rel}: '{name}' appears outside its docstring notice")
                continue
            violations.append(f"{rel}: forbidden name '{name}' found")
    assert violations == [], "order-execution paths found in production code:\n" + "\n".join(
        violations
    )


def test_no_metatrader5_order_module_imported() -> None:
    """Nothing in app/ imports MetaTrader5's own order-placing surface
    directly by any alias other than the read-only provider's own lazy,
    try/except-guarded import."""
    for path in _all_app_python_files():
        rel = path.relative_to(APP_ROOT.parent).as_posix()
        text = path.read_text(encoding="utf-8")
        if "import MetaTrader5" in text:
            assert rel == "app/market/mt5_provider.py", (
                f"unexpected MetaTrader5 import in {rel}; only the read-only "
                "provider may import it, and only lazily/guarded"
            )


def test_pepperstone_gateway_is_the_only_execution_boundary() -> None:
    """`send_order` (this project's own execution entry point, not MT5's)
    exists in exactly one place and always raises -- see
    app.broker.pepperstone.PepperstoneGateway.send_order, already covered
    by test_pepperstone_gateway_never_sends_orders in test_broker.py."""
    hits = [
        path.relative_to(APP_ROOT.parent).as_posix()
        for path in _all_app_python_files()
        if "def send_order" in path.read_text(encoding="utf-8")
    ]
    assert hits == ["app/broker/pepperstone.py"]
