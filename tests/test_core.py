"""Core test-suite for the Kavile finance engine."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from finance.analytics import build_analysis, build_insights
from finance.categorize import (
    add_keyword_rule,
    apply_categorization,
    default_rules,
    rules_from_frame,
    rules_to_frame,
)
from finance.charts import (
    balance_figure,
    cash_flow_figure,
    category_donut,
    heatmap_figure,
    interest_figure,
    monthly_flow_figure,
    savings_growth_figure,
    score_components_figure,
    score_gauge,
    weekday_figure,
)
from finance.cleaning import load_statement_files, parse_amount
from finance.demo import build_demo_workbook
from finance.scoring import compute_health


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("\u20a61,250,000.00", 1_250_000.0),
        ("\u20a6 12,500", 12_500.0),
        ("(2,000)", -2_000.0),
        ("1,000 DR", -1_000.0),
        ("4,500 CR", 4_500.0),
        ("1 234,56", 1234.56),
        ("-", np.nan),
        ("", np.nan),
        (3500, 3500.0),
        ("NGN 8,750.50", 8750.50),
    ],
)
def test_parse_amount(raw, expected):
    parsed = parse_amount(raw)
    if np.isnan(expected):
        assert np.isnan(parsed)
    else:
        assert parsed == pytest.approx(expected)


@pytest.fixture(scope="module")
def demo_statement():
    return load_statement_files(
        [("opay_demo_statement.xlsx", build_demo_workbook(pd.Timestamp("2026-10-28")))]
    )


def test_demo_dual_sheets_are_parsed(demo_statement):
    tx = demo_statement.transactions
    assert not tx.empty
    assert {"Wallet", "Savings"} <= set(tx["account"])
    assert tx["date"].notna().all()
    assert (tx["amount"] != 0).all()
    assert tx["description"].str.len().gt(0).all()
    assert tx["balance"].notna().any()

    # Failed rows must be excluded.
    assert not tx["status"].str.contains("Failed", case=False).any()


def test_demo_amounts_are_numeric_and_signed(demo_statement):
    tx = demo_statement.transactions
    assert pd.api.types.is_numeric_dtype(tx["amount"])
    assert (tx["credit"] >= 0).all()
    assert (tx["debit"] >= 0).all()
    assert tx["credit"].sum() > 5_000_000
    assert tx["debit"].sum() > 3_000_000


def test_categorisation_and_interest(demo_statement):
    categorized, warnings = apply_categorization(demo_statement.transactions)
    assert not warnings
    categories = set(categorized["category"])
    assert "OWealth Interest" in categories
    assert "Savings & Investments" in categories
    assert "Betting & Lottery" in categories
    assert "Airtime & Data" in categories

    interest = categorized.loc[categorized["is_interest"]]
    assert not interest.empty
    assert (interest["amount"] > 0).all()
    assert interest["category"].eq("OWealth Interest").all()


def test_analysis_and_scoring(demo_statement):
    categorized, _ = apply_categorization(demo_statement.transactions)
    analysis = build_analysis(categorized)

    k = analysis.kpis
    assert k["inflow"] > 0
    assert k["outflow"] > 0
    assert k["interest"] > 0
    assert k["savings_deposits"] > 0
    assert 0 <= k["savings_rate"] < 1
    assert k["runway_months"] > 0
    assert not analysis.monthly.empty
    assert len(analysis.monthly) >= 12
    assert not analysis.spend_by_category.empty
    assert not analysis.daily.empty
    assert analysis.has_time is True
    assert analysis.heatmap is not None

    health = compute_health(k)
    assert 0 <= health.total <= 100
    assert health.grade in "ABCDE"
    assert len(health.components) == 7

    insights = build_insights(k, health, analysis)
    assert len(insights) >= 4
    assert all({"tone", "title", "body"} <= set(item) for item in insights)
    betting = next(item for item in insights if "Betting" in item["title"])
    assert "total money out" in betting["body"]
    assert "of all spending" not in betting["body"]


def test_rules_roundtrip_and_custom_rule(demo_statement):
    rules = default_rules()
    frame = rules_to_frame(rules)
    rebuilt = rules_from_frame(frame)
    assert len(rebuilt) == len(rules)
    assert rebuilt[0].pattern == rules[0].pattern

    categorized, _ = apply_categorization(demo_statement.transactions, rebuilt)
    assert categorized["category"].notna().all()

    extended = add_keyword_rule(rules, "Chowdeck", "Food & Groceries")
    assert any(rule.pattern == "Chowdeck" for rule in extended)


def test_charts_build(demo_statement):
    categorized, _ = apply_categorization(demo_statement.transactions)
    analysis = build_analysis(categorized)
    health = compute_health(analysis.kpis)

    figures = [
        cash_flow_figure(analysis.daily),
        monthly_flow_figure(analysis.monthly),
        category_donut(analysis.spend_by_category),
        interest_figure(analysis.interest_monthly),
        savings_growth_figure(analysis.savings_series),
        weekday_figure(analysis.frequency),
        heatmap_figure(analysis.heatmap),
        balance_figure(analysis.transactions),
        score_gauge(health),
        score_components_figure(health),
    ]
    for figure in figures:
        assert figure.data is not None
        assert len(figure.data) >= 1

    # Tick labels must stay inside the plot box: Plotly clips anything that
    # spills into the margin, which previously hid every y-axis label.
    for figure in figures[:8]:
        assert figure.layout.xaxis.automargin is True
        assert figure.layout.yaxis.automargin is True
        assert figure.layout.margin.l >= 40
        assert figure.layout.margin.b >= 30


def test_single_sheet_csv_import(tmp_path):
    csv = tmp_path / "wallet.csv"
    csv.write_text(
        "Date,Description,Amount,Balance\n"
        "03/02/2026,MTN Airtime,-1500,48500\n"
        "05/02/2026,Transfer from CHINEDU OBI,25000,73500\n"
        "06/02/2026,Salary,500000,573500\n",
        encoding="utf-8",
    )
    dataset = load_statement_files([("wallet.csv", csv.read_bytes())])
    tx = dataset.transactions
    assert len(tx) == 3
    assert tx["account"].unique().tolist() == ["Wallet"]
    assert tx["amount"].tolist() == [-1500.0, 25000.0, 500000.0]

    categorized, _ = apply_categorization(tx)
    assert "Airtime & Data" in set(categorized["category"])
    assert "Transfers In" in set(categorized["category"])
    assert "Salary & Income" in set(categorized["category"])
