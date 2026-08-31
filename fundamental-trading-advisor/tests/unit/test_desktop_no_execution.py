"""Desktop safety audit (V1.2 spec section 23): every clickable control in
`app/desktop/` must be wired to a controller/dialog/navigation action, never
to an order-execution API. `test_no_order_execution_path.py` already scans
the whole `app/` tree (desktop included) for the forbidden MT5 order names;
this file adds a desktop-specific, button-level check plus confirmation
that no scoring/threshold logic lives in the UI layer (spec sections 3, 24).
"""

from __future__ import annotations

from pathlib import Path

DESKTOP_ROOT = Path(__file__).resolve().parents[2] / "app" / "desktop"

FORBIDDEN_EXECUTION_NAMES = (
    "order_send",
    "order_check",
    "positions_get",
    "orders_get",
    "send_order",
    "TRADE_ACTION_DEAL",
    "TRADE_ACTION_PENDING",
)

# Anything that would indicate the UI is re-deriving a trading decision
# rather than presenting one the engine already produced.
FORBIDDEN_SCORING_NAMES = (
    "def score_",
    "def compute_score",
    "def calculate_conviction",
    "STOP_PCT_BY_CLASS",
    "build_trade_math",
)


def _all_desktop_python_files() -> list[Path]:
    return sorted(DESKTOP_ROOT.rglob("*.py"))


def test_no_execution_api_referenced_anywhere_in_desktop_package() -> None:
    violations: list[str] = []
    for path in _all_desktop_python_files():
        text = path.read_text(encoding="utf-8")
        for name in FORBIDDEN_EXECUTION_NAMES:
            if name in text:
                violations.append(f"{path.relative_to(DESKTOP_ROOT.parents[1])}: '{name}'")
    assert violations == [], "execution API referenced in the desktop package:\n" + "\n".join(
        violations
    )


def test_no_scoring_or_risk_math_reimplemented_in_desktop_package() -> None:
    violations: list[str] = []
    for path in _all_desktop_python_files():
        text = path.read_text(encoding="utf-8")
        for name in FORBIDDEN_SCORING_NAMES:
            if name in text:
                violations.append(f"{path.relative_to(DESKTOP_ROOT.parents[1])}: '{name}'")
    message = "scoring/risk math re-implemented in the desktop package:\n" + "\n".join(violations)
    assert violations == [], message


def test_every_qpushbutton_click_connects_to_a_known_safe_target() -> None:
    """Every `.clicked.connect(...)` call in the desktop package must
    target a controller method, a Qt signal re-emission, or a dialog --
    never something spelled like an order/execution call. This is a
    static text check (no live Qt event loop needed) so it also catches
    a future button added without a corresponding test."""
    import re

    pattern = re.compile(r"\.clicked\.connect\(([^)]*)\)")
    forbidden_substrings = ("order", "execute", "send_order", "position")
    violations: list[str] = []
    for path in _all_desktop_python_files():
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            target = match.group(1).lower()
            for forbidden in forbidden_substrings:
                if forbidden in target:
                    violations.append(f"{path.name}: clicked.connect({match.group(1)!r})")
    assert violations == [], "a button appears wired to an execution-like target:\n" + "\n".join(
        violations
    )
