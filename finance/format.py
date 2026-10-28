"""Shared formatting helpers for the dashboard."""

from __future__ import annotations

SYMBOL = "\u20a6"  # Naira


def money(value: float | int | None, symbol: str = SYMBOL, decimals: int = 0) -> str:
    """Format a number as Naira, e.g. ``₦1,250,000``."""
    if value is None:
        return f"{symbol}0"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return f"{symbol}0"
    if value != value:  # NaN
        return f"{symbol}0"
    return f"{symbol}{value:,.{decimals}f}"


def compact_money(value: float | int | None, symbol: str = SYMBOL) -> str:
    """Compact currency label, e.g. ``₦1.2M``."""
    if value is None:
        return f"{symbol}0"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return f"{symbol}0"
    if value != value:  # NaN
        return f"{symbol}0"
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000_000:
        return f"{sign}{symbol}{value / 1_000_000_000:,.1f}B"
    if value >= 1_000_000:
        return f"{sign}{symbol}{value / 1_000_000:,.1f}M"
    if value >= 10_000:
        return f"{sign}{symbol}{value / 1_000:,.0f}k"
    if value >= 1_000:
        return f"{sign}{symbol}{value / 1_000:,.1f}k"
    return f"{sign}{symbol}{value:,.0f}"


def pct(value: float | None, decimals: int = 1) -> str:
    """Format a ratio as a percentage string."""
    if value is None:
        return "0.0%"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "0.0%"
    if value != value:
        return "0.0%"
    return f"{value * 100:,.{decimals}f}%"


def plain(value: float | int | None, decimals: int = 0) -> str:
    """Format a plain number with thousands separators."""
    if value is None:
        return "0"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "0"
    if value != value:
        return "0"
    return f"{value:,.{decimals}f}"
