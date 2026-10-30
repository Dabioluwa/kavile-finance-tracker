"""Derived metrics, aggregations and narrative insights."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .categorize import (
    DISCRETIONARY_CATEGORIES,
    INCOME_CATEGORIES,
    INTERNAL_CATEGORY,
    INTEREST_CATEGORY,
    TRANSFER_CATEGORIES,
    category_color,
    category_group,
)
from .format import compact_money, money, pct

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAY_FULL = {
    "Mon": "Monday",
    "Tue": "Tuesday",
    "Wed": "Wednesday",
    "Thu": "Thursday",
    "Fri": "Friday",
    "Sat": "Saturday",
    "Sun": "Sunday",
}


@dataclass
class Analysis:
    transactions: pd.DataFrame
    start: pd.Timestamp
    end: pd.Timestamp
    days: int
    kpis: dict[str, Any]
    daily: pd.DataFrame
    monthly: pd.DataFrame
    weekly: pd.DataFrame
    spend_by_category: pd.DataFrame
    income_by_category: pd.DataFrame
    income_breakdown: pd.DataFrame
    top_merchants: pd.DataFrame
    frequency: pd.DataFrame
    heatmap: pd.DataFrame | None
    savings_tx: pd.DataFrame
    savings_series: pd.DataFrame
    savings_monthly: pd.DataFrame
    interest: pd.DataFrame
    interest_monthly: pd.DataFrame
    recurring: pd.DataFrame
    spikes: pd.DataFrame
    largest: pd.DataFrame
    has_time: bool
    warnings: list[str] = field(default_factory=list)


def build_analysis(
    transactions: pd.DataFrame, include_transfers_in_income: bool = False
) -> Analysis:
    """Compute every table and KPI the dashboard needs.

    ``include_transfers_in_income`` controls whether credits categorised as
    ``Transfers In`` are treated as income. It is off by default because a
    transfer is cash movement, not necessarily money earned.
    """
    if transactions is None or transactions.empty:
        raise ValueError("No transactions to analyse.")

    tx = transactions.copy()
    tx = tx.sort_values("timestamp", kind="stable").reset_index(drop=True)
    tx["month"] = tx["timestamp"].dt.strftime("%Y-%m")
    tx["month_label"] = tx["timestamp"].dt.strftime("%b %y")
    tx["weekday"] = tx["timestamp"].dt.day_name().str[:3]
    tx["hour"] = tx["timestamp"].dt.hour

    start = tx["timestamp"].min().normalize()
    end = tx["timestamp"].max().normalize()
    days = max(1, int((end - start).days) + 1)

    cash = tx.loc[~tx["is_internal"]].copy()
    inflow = float(cash.loc[cash["credit"] > 0, "credit"].sum())
    outflow = float(cash.loc[cash["debit"] > 0, "debit"].sum())
    net = inflow - outflow

    core_categories = INCOME_CATEGORIES - {"Transfers In"}
    core_income = float(cash.loc[cash["category"].isin(core_categories), "credit"].sum())
    transfers_in = float(
        cash.loc[cash["category"].eq("Transfers In"), "credit"].sum()
    )
    included_income = core_income + (
        transfers_in if include_transfers_in_income else 0.0
    )
    # If no earned income is detected, fall back to every non-internal credit so
    # the ratios still have a denominator.
    income_base = included_income if included_income > 0 else inflow
    income_breakdown = _income_breakdown(tx, include_transfers_in_income)

    savings_accounts = [
        str(a)
        for a in tx["account"].dropna().unique()
        if re.search(r"saving|owealth|o wealth|invest|target", str(a), re.IGNORECASE)
    ]
    has_savings_account = bool(savings_accounts)
    if has_savings_account:
        savings_tx = tx.loc[
            tx["account"].isin(savings_accounts) | tx["is_interest"]
        ].copy()
        savings_credits = savings_tx.loc[
            (savings_tx["credit"] > 0) & ~savings_tx["is_interest"]
        ]
        deposits = float(savings_credits["credit"].sum())
        withdrawals = float(savings_tx.loc[savings_tx["debit"] > 0, "debit"].sum())
    else:
        savings_tx = tx.loc[tx["is_internal"] | tx["is_interest"]].copy()
        deposits = float(savings_tx.loc[savings_tx["debit"] > 0, "debit"].sum())
        withdrawals = float(savings_tx.loc[savings_tx["credit"] > 0, "credit"].sum())

    interest = tx.loc[tx["is_interest"]].copy()
    interest_total = float(interest["credit"].sum())

    daily = _daily(cash, start, end)
    weekly = _weekly(cash)
    monthly = _monthly(cash, start, end)
    savings_daily = _savings_daily(savings_tx, start, end)
    savings_monthly = _savings_monthly(savings_tx, start, end)
    monthly = monthly.merge(
        savings_monthly[["month", "deposits", "withdrawals", "interest"]],
        on="month",
        how="left",
    ).fillna({"deposits": 0.0, "withdrawals": 0.0, "interest": 0.0})
    monthly["savings_rate"] = np.where(
        monthly["inflow"] > 0,
        (monthly["deposits"] / monthly["inflow"]).clip(upper=1.0),
        0.0,
    )
    monthly["label"] = pd.to_datetime(monthly["month"] + "-01").dt.strftime("%b %y")

    spend_by_category = _by_category(cash, "debit")
    income_by_category = _by_category(cash, "credit")
    top_merchants = _top_merchants(cash)
    frequency, heatmap, has_time = _frequency(cash, tx)
    interest_monthly = _interest_monthly(interest, start, end)
    recurring = _recurring(cash)
    spikes = _spikes(daily)
    largest = _largest(cash)

    savings_balance_end = _last_balance(savings_daily, "balance", "cumulative_net")
    avg_monthly_expenses = float(outflow / max(days / 30.44, 1 / 30.44))
    runway_months = (
        savings_balance_end / avg_monthly_expenses if avg_monthly_expenses > 0 else 0.0
    )

    avg_balance = (
        float(savings_daily["balance"].mean())
        if "balance" in savings_daily and savings_daily["balance"].notna().any()
        else float(savings_daily["cumulative_net"].mean())
        if not savings_daily.empty
        else 0.0
    )
    effective_rate = (
        interest_total / avg_balance * (365 / days)
        if avg_balance > 0 and interest_total > 0
        else 0.0
    )

    spend_total = float(spend_by_category["total"].sum()) if not spend_by_category.empty else 0.0
    betting_total = float(
        spend_by_category.loc[
            spend_by_category["category"].eq("Betting & Lottery"), "total"
        ].sum()
    )
    fees_total = float(
        spend_by_category.loc[
            spend_by_category["category"].eq("Fees & Charges"), "total"
        ].sum()
    )
    discretionary_total = float(
        spend_by_category.loc[
            spend_by_category["category"].isin(DISCRETIONARY_CATEGORIES), "total"
        ].sum()
    )

    completed_months = int((tx["month"].nunique()))
    positive_months = int((monthly["net"] > 0).sum())
    savings_months = int((monthly["deposits"] > 0).sum())
    days_with_savings = int(
        savings_tx.loc[savings_tx["credit"] > 0, "timestamp"].dt.normalize().nunique()
    )

    weekend_spend = float(
        cash.loc[
            (cash["debit"] > 0) & (cash["timestamp"].dt.dayofweek >= 5), "debit"
        ].sum()
    )
    other_rows = int(
        cash["category"].isin(["Other Spending", "Other Income"]).sum()
    )

    top_merchant = (
        str(top_merchants.iloc[0]["merchant"]) if not top_merchants.empty else "—"
    )
    top_category = (
        str(spend_by_category.iloc[0]["category"]) if not spend_by_category.empty else "—"
    )
    peak_day = start
    peak_outflow = 0.0
    if not spikes.empty:
        peak_day = spikes.iloc[0]["date"]
        peak_outflow = float(spikes.iloc[0]["outflow"])

    kpis: dict[str, Any] = {
        "start": start,
        "end": end,
        "days": days,
        "months": completed_months,
        "transactions": int(len(tx)),
        "cash_transactions": int(len(cash)),
        "inflow": inflow,
        "outflow": outflow,
        "net": net,
        "core_income": core_income,
        "transfers_in": transfers_in,
        "income_base": income_base,
        "income_includes_transfers": include_transfers_in_income,
        "income_fallback": included_income <= 0,
        "savings_deposits": deposits,
        "savings_withdrawals": withdrawals,
        "savings_net": deposits - withdrawals + interest_total,
        "savings_balance": savings_balance_end,
        "interest": interest_total,
        "interest_effective": effective_rate,
        "avg_savings_balance": avg_balance,
        "savings_rate": min(deposits / income_base, 1.0) if income_base > 0 else 0.0,
        "expense_ratio": outflow / income_base if income_base > 0 else 0.0,
        "runway_months": runway_months,
        "avg_monthly_expenses": avg_monthly_expenses,
        "spend_total": spend_total,
        "betting_total": betting_total,
        "fees_total": fees_total,
        "discretionary_total": discretionary_total,
        "betting_share": betting_total / income_base if income_base > 0 else 0.0,
        "fees_share": fees_total / spend_total if spend_total > 0 else 0.0,
        "discretionary_share": (
            discretionary_total / spend_total if spend_total > 0 else 0.0
        ),
        "weekend_share": weekend_spend / spend_total if spend_total > 0 else 0.0,
        "positive_months": positive_months,
        "savings_months": savings_months,
        "days_with_savings": days_with_savings,
        "avg_transaction": (
            float(cash.loc[cash["debit"] > 0, "debit"].mean()) if not cash.empty else 0.0
        ),
        "tx_per_day": len(cash) / days,
        "top_merchant": top_merchant,
        "top_category": top_category,
        "top_category_total": (
            float(spend_by_category.iloc[0]["total"])
            if not spend_by_category.empty
            else 0.0
        ),
        "peak_day": peak_day,
        "peak_outflow": peak_outflow,
        "active_days": int(cash["timestamp"].dt.normalize().nunique()),
        "other_rows": other_rows,
        "recurring_count": int(len(recurring)),
        "has_savings_account": has_savings_account,
        "net_positive": net >= 0,
    }

    analysis = Analysis(
        transactions=tx,
        start=start,
        end=end,
        days=days,
        kpis=kpis,
        daily=daily,
        monthly=monthly,
        weekly=weekly,
        spend_by_category=spend_by_category,
        income_by_category=income_by_category,
        income_breakdown=income_breakdown,
        top_merchants=top_merchants,
        frequency=frequency,
        heatmap=heatmap,
        savings_tx=savings_tx,
        savings_series=savings_daily,
        savings_monthly=savings_monthly,
        interest=interest,
        interest_monthly=interest_monthly,
        recurring=recurring,
        spikes=spikes,
        largest=largest,
        has_time=has_time,
    )
    return analysis


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------


def _daily(cash: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if cash.empty:
        return pd.DataFrame(
            columns=["date", "inflow", "outflow", "net", "count", "weekday"]
        )
    grouped = cash.groupby("date").agg(
        inflow=("credit", "sum"),
        outflow=("debit", "sum"),
        count=("txn_id", "count"),
    )
    index = pd.date_range(start, end, freq="D")
    grouped = grouped.reindex(index, fill_value=0)
    grouped.index.name = "date"
    grouped["net"] = grouped["inflow"] - grouped["outflow"]
    grouped["weekday"] = grouped.index.day_name().str[:3]
    grouped["outflow_7d"] = grouped["outflow"].rolling(7, min_periods=1).mean()
    return grouped.reset_index()


def _weekly(cash: pd.DataFrame) -> pd.DataFrame:
    if cash.empty:
        return pd.DataFrame(columns=["week", "inflow", "outflow", "count"])
    weekly = (
        cash.set_index("date")
        .resample("W-MON")
        .agg(
            inflow=("credit", "sum"),
            outflow=("debit", "sum"),
            count=("txn_id", "count"),
        )
        .reset_index()
        .rename(columns={"date": "week"})
    )
    weekly["net"] = weekly["inflow"] - weekly["outflow"]
    return weekly


def _monthly(cash: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if cash.empty:
        return pd.DataFrame(columns=["month", "inflow", "outflow", "net", "count"])
    monthly = (
        cash.groupby("month")
        .agg(
            inflow=("credit", "sum"),
            outflow=("debit", "sum"),
            net=("amount", "sum"),
            count=("txn_id", "count"),
        )
        .reset_index()
    )
    months = (
        pd.period_range(start=start.to_period("M"), end=end.to_period("M"), freq="M")
        .strftime("%Y-%m")
        .tolist()
    )
    monthly = monthly.set_index("month").reindex(months, fill_value=0)
    monthly.index.name = "month"
    monthly = monthly.reset_index()
    monthly["label"] = pd.to_datetime(monthly["month"] + "-01").dt.strftime("%b %y")
    return monthly


def _savings_daily(
    savings_tx: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    columns = [
        "date",
        "deposits",
        "withdrawals",
        "interest",
        "net",
        "cumulative_net",
        "cumulative_interest",
        "balance",
    ]
    if savings_tx.empty:
        return pd.DataFrame(columns=columns)

    grouped = pd.DataFrame(
        {
            "deposits": savings_tx.loc[~savings_tx["is_interest"]]
            .groupby("date")["credit"]
            .sum(),
            "withdrawals": savings_tx.groupby("date")["debit"].sum(),
            "interest": savings_tx.loc[savings_tx["is_interest"]]
            .groupby("date")["credit"]
            .sum(),
        }
    ).fillna(0.0)

    index = pd.date_range(start, end, freq="D")
    grouped = grouped.reindex(index, fill_value=0)
    grouped.index.name = "date"
    grouped["net"] = (
        grouped["deposits"] + grouped["interest"] - grouped["withdrawals"]
    )
    grouped["cumulative_net"] = grouped["net"].cumsum()
    grouped["cumulative_interest"] = grouped["interest"].cumsum()

    balances = savings_tx.dropna(subset=["balance"])
    if not balances.empty:
        balance_by_day = (
            balances.sort_values("timestamp")
            .groupby(balances["timestamp"].dt.normalize())["balance"]
            .last()
        )
        balance_by_day.index = pd.to_datetime(balance_by_day.index)
        grouped["balance"] = balance_by_day.reindex(index).ffill()
    else:
        grouped["balance"] = np.nan

    return grouped.reset_index()


def _savings_monthly(
    savings_tx: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    months = (
        pd.period_range(start=start.to_period("M"), end=end.to_period("M"), freq="M")
        .strftime("%Y-%m")
        .tolist()
    )
    columns = ["month", "deposits", "withdrawals", "interest"]
    if savings_tx.empty:
        return pd.DataFrame({c: [] for c in columns})

    grouped = pd.DataFrame(
        {
            "deposits": savings_tx.loc[~savings_tx["is_interest"]]
            .groupby("month")["credit"]
            .sum(),
            "withdrawals": savings_tx.groupby("month")["debit"].sum(),
            "interest": savings_tx.loc[savings_tx["is_interest"]]
            .groupby("month")["credit"]
            .sum(),
        }
    ).fillna(0.0)
    grouped = grouped.reindex(months, fill_value=0)
    grouped.index.name = "month"
    return grouped.reset_index()


def _interest_monthly(
    interest: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    months = (
        pd.period_range(start=start.to_period("M"), end=end.to_period("M"), freq="M")
        .strftime("%Y-%m")
        .tolist()
    )
    if interest.empty:
        return pd.DataFrame(columns=["month", "interest", "count"])
    grouped = interest.groupby("month").agg(
        interest=("credit", "sum"), count=("txn_id", "count")
    )
    grouped = grouped.reindex(months, fill_value=0)
    grouped.index.name = "month"
    result = grouped.reset_index()
    result["label"] = pd.to_datetime(result["month"] + "-01").dt.strftime("%b %y")
    result["cumulative"] = result["interest"].cumsum()
    return result


def _income_breakdown(
    tx: pd.DataFrame, include_transfers_in_income: bool
) -> pd.DataFrame:
    """Every credit, flagged with whether it feeds the income denominator."""
    columns = [
        "timestamp",
        "account",
        "description",
        "category",
        "credit",
        "included",
        "reason",
    ]
    if tx.empty or "credit" not in tx:
        return pd.DataFrame(columns=columns)

    credits = tx.loc[tx["credit"] > 0].copy()
    if credits.empty:
        return pd.DataFrame(columns=columns)

    included_categories = INCOME_CATEGORIES - (
        set() if include_transfers_in_income else {"Transfers In"}
    )
    credits["included"] = (~credits["is_internal"]) & credits["category"].isin(
        included_categories
    )

    def _reason(row: pd.Series) -> str:
        category = str(row["category"])
        if row["is_internal"]:
            return "Excluded — internal movement between your own accounts"
        if row["included"]:
            if category == INTEREST_CATEGORY:
                return "Counted — interest is new earnings on savings"
            if category == "Salary & Income":
                return "Counted — earned income"
            if category == "Transfers In":
                return "Counted — Transfers In included by your setting"
            return "Counted — refund or unmatched credit"
        if category == "Transfers In":
            return "Excluded — Transfers In is cash movement, not earned income"
        return f"Excluded — {category} is not treated as income"

    credits["reason"] = credits.apply(_reason, axis=1)
    return (
        credits[columns]
        .sort_values(["included", "timestamp"], ascending=[False, False])
        .reset_index(drop=True)
    )


def _by_category(cash: pd.DataFrame, side: str) -> pd.DataFrame:
    value_col = "debit" if side == "debit" else "credit"
    if cash.empty:
        return pd.DataFrame(
            columns=["category", "total", "count", "avg", "share", "group", "color"]
        )
    subset = cash.loc[cash[value_col] > 0]
    if subset.empty:
        return pd.DataFrame(
            columns=["category", "total", "count", "avg", "share", "group", "color"]
        )
    grouped = (
        subset.groupby("category")
        .agg(total=(value_col, "sum"), count=("txn_id", "count"), avg=(value_col, "mean"))
        .reset_index()
    )
    total = grouped["total"].sum()
    grouped["share"] = grouped["total"] / total if total else 0.0
    grouped["group"] = grouped["category"].map(category_group)
    grouped["color"] = grouped["category"].map(category_color)
    return grouped.sort_values("total", ascending=False).reset_index(drop=True)


def _top_merchants(cash: pd.DataFrame) -> pd.DataFrame:
    if cash.empty:
        return pd.DataFrame(columns=["merchant", "total", "count", "avg"])
    subset = cash.loc[(cash["debit"] > 0) & (cash["merchant"].astype(str).str.len() > 0)]
    if subset.empty:
        return pd.DataFrame(columns=["merchant", "total", "count", "avg"])
    grouped = (
        subset.groupby("merchant")
        .agg(
            total=("debit", "sum"),
            count=("txn_id", "count"),
            avg=("debit", "mean"),
        )
        .reset_index()
        .sort_values("total", ascending=False)
        .head(12)
        .reset_index(drop=True)
    )
    return grouped


def _frequency(
    cash: pd.DataFrame, tx: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame | None, bool]:
    if cash.empty:
        return pd.DataFrame(columns=["weekday", "count", "total", "share"]), None, False

    weekday_counts = (
        cash.groupby("weekday")
        .agg(count=("txn_id", "count"), total=("amount", lambda s: s.abs().sum()))
        .reindex(WEEKDAYS, fill_value=0)
        .reset_index()
    )
    total = weekday_counts["count"].sum()
    weekday_counts["share"] = weekday_counts["count"] / total if total else 0.0

    hours = tx["timestamp"].dt.hour
    minutes = tx["timestamp"].dt.minute
    has_time = bool((hours != 0).any() or (minutes != 0).any())

    heatmap = None
    if has_time:
        pivot = (
            tx.assign(hour=tx["timestamp"].dt.hour)
            .groupby(["weekday", "hour"])
            .size()
            .unstack(fill_value=0)
            .reindex(index=WEEKDAYS, columns=range(24), fill_value=0)
        )
        heatmap = pivot
    return weekday_counts, heatmap, has_time


def _recurring(cash: pd.DataFrame) -> pd.DataFrame:
    columns = ["merchant", "category", "months", "count", "avg", "total", "last_seen"]
    if cash.empty:
        return pd.DataFrame(columns=columns)
    subset = cash.loc[
        (cash["debit"] > 0)
        & (cash["merchant"].astype(str).str.len() > 0)
        & ~cash["category"].isin(["Other Spending", "Other Income"])
    ]
    if subset.empty:
        return pd.DataFrame(columns=columns)
    grouped = (
        subset.groupby("merchant")
        .agg(
            category=("category", lambda s: s.mode().iat[0] if not s.mode().empty else "Other Spending"),
            months=("month", "nunique"),
            count=("txn_id", "count"),
            avg=("debit", "mean"),
            total=("debit", "sum"),
            last_seen=("timestamp", "max"),
        )
        .reset_index()
    )
    grouped = grouped.loc[grouped["months"] >= 3]
    return (
        grouped.sort_values(["months", "count"], ascending=False)
        .head(15)
        .reset_index(drop=True)
    )


def _spikes(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame(columns=["date", "outflow", "inflow", "zscore", "share"])
    mean = daily["outflow"].mean()
    std = daily["outflow"].std(ddof=0)
    spikes = daily.sort_values("outflow", ascending=False).head(5).copy()
    spikes["zscore"] = (spikes["outflow"] - mean) / std if std > 0 else 0.0
    total = daily["outflow"].sum()
    spikes["share"] = spikes["outflow"] / total if total else 0.0
    return spikes.reset_index(drop=True)


def _largest(cash: pd.DataFrame) -> pd.DataFrame:
    if cash.empty:
        return pd.DataFrame(columns=["timestamp", "merchant", "description", "amount", "category"])
    subset = cash.loc[cash["debit"] > 0].nlargest(8, "debit")
    return subset[
        ["timestamp", "merchant", "description", "debit", "category"]
    ].rename(columns={"debit": "amount"}).reset_index(drop=True)


def _last_balance(series: pd.DataFrame, *columns: str) -> float:
    if series.empty:
        return 0.0
    for column in columns:
        if column in series and series[column].notna().any():
            return float(series[column].dropna().iloc[-1])
    return 0.0


# ---------------------------------------------------------------------------
# Narrative insights
# ---------------------------------------------------------------------------


def build_insights(kpis: dict[str, Any], health: Any, analysis: Analysis) -> list[dict[str, str]]:
    """Turn the numbers into short, plain-English observations."""
    insights: list[dict[str, str]] = []

    rate = float(kpis["savings_rate"])
    if kpis["savings_deposits"] > 0:
        tone = "good" if rate >= 0.15 else "warn" if rate < 0.08 else "info"
        insights.append(
            {
                "tone": tone,
                "icon": "◈",
                "title": f"You kept {pct(rate)} of income",
                "body": (
                    f"{money(kpis['savings_deposits'])} moved into savings across "
                    f"{kpis['savings_months']} month(s). "
                    + ("That is above the 15% benchmark." if rate >= 0.15 else "Aim for at least 15–20%.")
                ),
            }
        )
    else:
        insights.append(
            {
                "tone": "warn",
                "icon": "◇",
                "title": "No savings transfers detected",
                "body": "There were no OWealth or savings movements in this period. Even a small automated transfer helps.",
            }
        )

    if kpis["interest"] > 0:
        insights.append(
            {
                "tone": "good",
                "icon": "✦",
                "title": f"{money(kpis['interest'])} earned passively",
                "body": (
                    f"Interest credits on OWealth added {money(kpis['interest'])} this period"
                    + (
                        f", roughly {pct(kpis['interest_effective'])} annualised on your average balance."
                        if kpis["interest_effective"] > 0
                        else "."
                    )
                ),
            }
        )

    if kpis["betting_total"] > 0:
        share = float(kpis["betting_share"])
        outflow_share = (
            kpis["betting_total"] / kpis["spend_total"] if kpis["spend_total"] else 0.0
        )
        insights.append(
            {
                "tone": "warn" if share >= 0.05 else "info",
                "icon": "⚠",
                "title": f"Betting absorbed {pct(share)} of income",
                "body": (
                    f"{money(kpis['betting_total'])} went to betting apps — "
                    f"{pct(outflow_share)} of total money out (transfers included), "
                    f"but {pct(share)} of the income you earned. "
                    "Consider a hard monthly cap."
                ),
            }
        )

    if kpis["top_category"] != "—":
        insights.append(
            {
                "tone": "info",
                "icon": "◐",
                "title": f"{kpis['top_category']} is your biggest category",
                "body": (
                    f"{money(kpis['top_category_total'])} spent, or "
                    f"{pct(kpis['top_category_total'] / kpis['spend_total'] if kpis['spend_total'] else 0)} "
                    "of everything that left your wallet."
                ),
            }
        )

    if not analysis.spikes.empty:
        peak = analysis.spikes.iloc[0]
        insights.append(
            {
                "tone": "info",
                "icon": "↯",
                "title": f"Spending spike on {peak['date']:%d %b %Y}",
                "body": (
                    f"{money(peak['outflow'])} left your account that day — "
                    f"{pct(peak['share'])} of the period's total outflow."
                ),
            }
        )

    if kpis["fees_total"] > 0 and kpis["fees_share"] >= 0.01:
        insights.append(
            {
                "tone": "warn",
                "icon": "◎",
                "title": f"Fees took {pct(kpis['fees_share'])} of spending",
                "body": (
                    f"{money(kpis['fees_total'])} went to charges and levies. "
                    "Fewer small transfers and withdrawals usually reduce this."
                ),
            }
        )

    if kpis["weekend_share"] > 0.4:
        insights.append(
            {
                "tone": "info",
                "icon": "☾",
                "title": f"{pct(kpis['weekend_share'])} of spending happens at weekends",
                "body": "Weekend spending is outpacing weekdays. A Friday cash limit can keep it in check.",
            }
        )

    if kpis["runway_months"] > 0:
        tone = "good" if kpis["runway_months"] >= 3 else "warn" if kpis["runway_months"] < 1 else "info"
        insights.append(
            {
                "tone": tone,
                "icon": "▤",
                "title": f"{kpis['runway_months']:.1f} months of runway",
                "body": (
                    f"Your savings balance of {money(kpis['savings_balance'])} could cover "
                    f"{kpis['runway_months']:.1f} month(s) of average spending. "
                    + ("Three to six months is a healthy target." if kpis["runway_months"] < 3 else "That is a solid buffer.")
                ),
            }
        )

    if kpis["other_rows"] > 0:
        share = kpis["other_rows"] / max(kpis["cash_transactions"], 1)
        if share > 0.08:
            insights.append(
                {
                    "tone": "tip",
                    "icon": "✎",
                    "title": f"{pct(share)} of transactions are untagged",
                    "body": "Add keyword rules in Data & Rules so the category breakdown reflects reality.",
                }
            )

    if kpis["recurring_count"] > 0:
        insights.append(
            {
                "tone": "info",
                "icon": "↻",
                "title": f"{kpis['recurring_count']} recurring merchants detected",
                "body": "These are the subscriptions and habits that quietly shape your month. Review them in Insights.",
            }
        )

    return insights
