"""Modal dialogs (V1.2).

Every dialog here only collects input or shows a message -- none of them
calls a controller directly. The caller (a view) reads the dialog's result
and passes it to the appropriate controller, keeping this module free of
any service/domain dependency.
"""

from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget


def ask_entry_price(parent: QWidget, asset: str, recommended_entry: float | None) -> float | None:
    """Prompts for the actual entry price the user got filled at in
    Pepperstone/MT5. Returns `None` if cancelled or the input isn't a
    valid, positive number -- never guesses or falls back to the
    recommended price."""
    hint = f" (recommended: {recommended_entry:g})" if recommended_entry is not None else ""
    value, ok = QInputDialog.getText(
        parent,
        "I Entered This Trade",
        f"Actual entry price for {asset}{hint}:",
    )
    if not ok or not value.strip():
        return None
    try:
        price = float(value.strip())
    except ValueError:
        show_error(
            parent,
            "Invalid Entry Price",
            f"'{value}' is not a valid number. Please enter a plain decimal price, e.g. 1.1005.",
        )
        return None
    if price <= 0:
        show_error(parent, "Invalid Entry Price", "The entry price must be greater than zero.")
        return None
    return price


def confirm_skip_trade(parent: QWidget, asset: str) -> bool:
    answer = QMessageBox.question(
        parent,
        "Skip Trade",
        f"Skip this {asset} opportunity? It will be marked CANCELLED and will no "
        "longer be monitored. This cannot be undone from this screen.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


def show_info(parent: QWidget, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)


def show_error(parent: QWidget, title: str, message: str) -> None:
    QMessageBox.critical(parent, title, message)
