"""Plotly chart builders with a single, consistent visual language."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .analytics import WEEKDAYS
from .format import compact_money, money, pct

INK = "#E8EEF6"
MUTED = "#8FA3BA"
GRID = "rgba(148,163,184,0.10)"
AXIS = "rgba(148,163,184,0.18)"
GREEN = "#2DD4A7"
GREEN_FILL = "rgba(45,212,167,0.14)"
CORAL = "#FB7185"
CORAL_FILL = "rgba(251,113,133,0.16)"
SKY = "#7DD3FC"
AMBER = "#FBBF24"
PURPLE = "#C084FC"
SLATE = "#64748B"
ACCOUNT_COLORS = [GREEN, SKY, PURPLE, AMBER, CORAL, "#A3E635", "#F472B6"]

FONT = "Inter, 'Segoe UI', system-ui, sans-serif"


def _layout(fig: go.Figure, height: int = 340, legend: bool = True) -> go.Figure:
    # Plotly clips tick labels that sit outside the margin box. The old 8px
    # margins pushed every y label to a negative x position, so the numbers
    # were rendered but invisible. Keep room for the ₦ prefix (and the
    # secondary right-hand axis), then let automargin grow for long labels.
    fig.update_layout(
        height=height,
        margin=dict(l=66, r=24, t=24, b=46),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=MUTED, size=12),
        hoverlabel=dict(
            bgcolor="#0E1620",
            bordercolor="rgba(148,163,184,0.25)",
            font=dict(color=INK, family=FONT, size=12),
        ),
        showlegend=legend,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=MUTED, size=11),
            itemsizing="constant",
        ),
        hovermode="x unified",
        barcornerradius=5,
        modebar=dict(bgcolor="rgba(0,0,0,0)", color=MUTED),
    )
    fig.update_xaxes(
        showgrid=False,
        linecolor=AXIS,
        linewidth=1,
        tickfont=dict(color=MUTED, size=11),
        title_font=dict(color=MUTED, size=11),
        zeroline=False,
        automargin=True,
        fixedrange=False,
    )
    fig.update_yaxes(
        gridcolor=GRID,
        zeroline=False,
        tickfont=dict(color=MUTED, size=11),
        title_font=dict(color=MUTED, size=11),
        automargin=True,
        fixedrange=False,
    )
    return fig


def _money_axis(fig: go.Figure, axis: str = "y") -> None:
    if axis == "y":
        fig.update_yaxes(tickprefix="\u20a6", tickformat=".2s")
    else:
        fig.update_yaxes(tickprefix="\u20a6", tickformat=".2s", overlaying="y", side="right")


def cash_flow_figure(daily: pd.DataFrame, height: int = 360) -> go.Figure:
    """Daily money in/out bars with a net-flow line and spike markers."""
    fig = go.Figure()
    if daily.empty:
        return _layout(fig, height, legend=False)

    fig.add_bar(
        x=daily["date"],
        y=daily["inflow"],
        name="Money in",
        marker=dict(color=GREEN, line=dict(width=0)),
        customdata=daily["inflow"],
        hovertemplate="Money in<br>%{x|%d %b %Y}<br>\u20a6%{customdata:,.0f}<extra></extra>",
    )
    fig.add_bar(
        x=daily["date"],
        y=-daily["outflow"],
        name="Money out",
        marker=dict(color=CORAL, line=dict(width=0)),
        customdata=daily["outflow"],
        hovertemplate="Money out<br>%{x|%d %b %Y}<br>\u20a6%{customdata:,.0f}<extra></extra>",
    )
    fig.add_scatter(
        x=daily["date"],
        y=daily["net"],
        name="Net flow",
        mode="lines",
        line=dict(color=SKY, width=1.6),
        hovertemplate="Net<br>%{x|%d %b %Y}<br>\u20a6%{y:,.0f}<extra></extra>",
    )

    spikes = daily.nlargest(3, "outflow")
    if not spikes.empty and spikes["outflow"].max() > 0:
        fig.add_scatter(
            x=spikes["date"],
            y=-spikes["outflow"],
            mode="markers",
            marker=dict(color=CORAL, size=9, symbol="diamond", line=dict(color="#0B1118", width=1)),
            name="Spike day",
            customdata=spikes["outflow"],
            hovertemplate="Spike<br>%{x|%d %b %Y}<br>\u20a6%{customdata:,.0f} out<extra></extra>",
        )

    average = daily["outflow"].mean()
    if average > 0:
        fig.add_hline(
            y=-average,
            line=dict(color="rgba(251,113,133,0.35)", width=1, dash="dot"),
            annotation_text="avg daily out",
            annotation_position="bottom left",
            annotation_font=dict(color=MUTED, size=10),
        )

    fig.update_layout(barmode="relative", bargap=0.25)
    _money_axis(fig)
    fig.update_xaxes(tickformat="%d %b", nticks=10)
    return _layout(fig, height)


def monthly_flow_figure(monthly: pd.DataFrame, height: int = 340) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if monthly.empty:
        return _layout(fig, height, legend=False)

    fig.add_bar(
        x=monthly["label"],
        y=monthly["inflow"],
        name="Money in",
        marker_color=GREEN,
        hovertemplate="%{x}<br>\u20a6%{y:,.0f}<extra></extra>",
    )
    fig.add_bar(
        x=monthly["label"],
        y=monthly["outflow"],
        name="Money out",
        marker_color=CORAL,
        hovertemplate="%{x}<br>\u20a6%{y:,.0f}<extra></extra>",
    )
    fig.add_scatter(
        x=monthly["label"],
        y=monthly["savings_rate"],
        name="Savings rate",
        mode="lines+markers",
        line=dict(color=AMBER, width=2),
        marker=dict(size=5),
        secondary_y=True,
        hovertemplate="%{x}<br>%{y:.1%} saved<extra></extra>",
    )
    fig.update_layout(barmode="group", bargap=0.32, bargroupgap=0.08)
    fig.update_yaxes(tickprefix="\u20a6", tickformat=".2s", secondary_y=False)
    fig.update_yaxes(
        tickformat=",.0%",
        secondary_y=True,
        showgrid=False,
        range=[0, max(0.35, float(monthly["savings_rate"].max()) * 1.4)],
    )
    return _layout(fig, height)


def category_donut(spend: pd.DataFrame, height: int = 360) -> go.Figure:
    fig = go.Figure()
    if spend.empty:
        return _layout(fig, height, legend=False)

    total = float(spend["total"].sum())
    fig.add_pie(
        labels=spend["category"],
        values=spend["total"],
        hole=0.64,
        sort=False,
        direction="clockwise",
        marker=dict(colors=spend["color"], line=dict(color="#0B1118", width=2)),
        textinfo="none",
        hovertemplate="%{label}<br>\u20a6%{value:,.0f} · %{percent}<extra></extra>",
    )
    fig.update_layout(
        annotations=[
            dict(
                text=f"<span style='font-size:11px;color:{MUTED}'>TOTAL SPEND</span><br>"
                f"<b style='font-size:22px;color:{INK}'>{compact_money(total)}</b>",
                x=0.5,
                y=0.5,
                showarrow=False,
                align="center",
            )
        ],
        legend=dict(orientation="v", x=1.0, y=0.5, xanchor="left", yanchor="middle"),
    )
    return _layout(fig, height)


def category_bar(spend: pd.DataFrame, height: int = 360) -> go.Figure:
    fig = go.Figure()
    if spend.empty:
        return _layout(fig, height, legend=False)
    data = spend.sort_values("total", ascending=True)
    fig.add_bar(
        x=data["total"],
        y=data["category"],
        orientation="h",
        marker=dict(color=data["color"], line=dict(width=0)),
        text=[f"{pct(v)}" for v in data["share"]],
        textposition="outside",
        textfont=dict(color=MUTED, size=11),
        hovertemplate="%{y}<br>\u20a6%{x:,.0f}<extra></extra>",
    )
    fig.update_xaxes(tickprefix="\u20a6", tickformat=".2s", showgrid=True, gridcolor=GRID)
    fig.update_yaxes(showgrid=False, tickfont=dict(color=INK, size=11))
    fig.update_traces(cliponaxis=False)
    return _layout(fig, height, legend=False)


def income_bar(income: pd.DataFrame, height: int = 300) -> go.Figure:
    fig = go.Figure()
    if income.empty:
        return _layout(fig, height, legend=False)
    data = income.sort_values("total", ascending=True)
    fig.add_bar(
        x=data["total"],
        y=data["category"],
        orientation="h",
        marker=dict(color=data["color"], line=dict(width=0)),
        hovertemplate="%{y}<br>\u20a6%{x:,.0f}<extra></extra>",
    )
    fig.update_xaxes(tickprefix="\u20a6", tickformat=".2s", showgrid=True, gridcolor=GRID)
    fig.update_yaxes(showgrid=False, tickfont=dict(color=INK, size=11))
    return _layout(fig, height, legend=False)


def savings_growth_figure(series: pd.DataFrame, height: int = 380) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if series.empty:
        return _layout(fig, height, legend=False)

    has_balance = "balance" in series and series["balance"].notna().any()
    main = series["balance"] if has_balance else series["cumulative_net"]
    label = "Savings balance" if has_balance else "Net saved"

    fig.add_scatter(
        x=series["date"],
        y=main,
        name=label,
        mode="lines",
        line=dict(color=SKY, width=2.4, shape="hv"),
        fill="tozeroy",
        fillcolor="rgba(56,189,248,0.12)",
        hovertemplate="%{x|%d %b %Y}<br>\u20a6%{y:,.0f}<extra></extra>",
    )
    fig.add_scatter(
        x=series["date"],
        y=series["cumulative_interest"],
        name="Interest earned",
        mode="lines",
        line=dict(color=AMBER, width=1.8, dash="dot"),
        secondary_y=True,
        hovertemplate="%{x|%d %b %Y}<br>\u20a6%{y:,.0f} interest<extra></extra>",
    )
    fig.update_yaxes(tickprefix="\u20a6", tickformat=".2s", secondary_y=False)
    fig.update_yaxes(tickprefix="\u20a6", tickformat=".2s", secondary_y=True, showgrid=False)
    fig.update_xaxes(tickformat="%d %b", nticks=10)
    return _layout(fig, height)


def savings_monthly_figure(monthly: pd.DataFrame, height: int = 340) -> go.Figure:
    fig = go.Figure()
    if monthly.empty:
        return _layout(fig, height, legend=False)

    fig.add_bar(
        x=monthly["month"],
        y=monthly["deposits"],
        name="Deposits",
        marker_color=GREEN,
        hovertemplate="%{x}<br>\u20a6%{y:,.0f} in<extra></extra>",
    )
    fig.add_bar(
        x=monthly["month"],
        y=-monthly["withdrawals"],
        name="Withdrawals",
        marker_color=CORAL,
        customdata=monthly["withdrawals"],
        hovertemplate="%{x}<br>\u20a6%{customdata:,.0f} out<extra></extra>",
    )
    fig.add_scatter(
        x=monthly["month"],
        y=monthly["interest"],
        name="Interest",
        mode="lines+markers",
        line=dict(color=AMBER, width=2),
        marker=dict(size=6),
        hovertemplate="%{x}<br>\u20a6%{y:,.0f} interest<extra></extra>",
    )
    fig.update_layout(barmode="relative", bargap=0.3)
    fig.update_xaxes(tickformat="%b %y")
    _money_axis(fig)
    return _layout(fig, height)


def interest_figure(interest_monthly: pd.DataFrame, height: int = 340) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if interest_monthly.empty:
        return _layout(fig, height, legend=False)

    fig.add_bar(
        x=interest_monthly["label"],
        y=interest_monthly["interest"],
        name="Interest credited",
        marker_color=AMBER,
        hovertemplate="%{x}<br>\u20a6%{y:,.0f}<extra></extra>",
    )
    fig.add_scatter(
        x=interest_monthly["label"],
        y=interest_monthly["cumulative"],
        name="Cumulative",
        mode="lines+markers",
        line=dict(color=GREEN, width=2),
        marker=dict(size=5),
        secondary_y=True,
        hovertemplate="%{x}<br>\u20a6%{y:,.0f} total<extra></extra>",
    )
    fig.update_yaxes(tickprefix="\u20a6", tickformat=".2s", secondary_y=False)
    fig.update_yaxes(tickprefix="\u20a6", tickformat=".2s", secondary_y=True, showgrid=False)
    fig.update_layout(bargap=0.4)
    return _layout(fig, height)


def weekday_figure(frequency: pd.DataFrame, height: int = 320) -> go.Figure:
    fig = go.Figure()
    if frequency.empty:
        return _layout(fig, height, legend=False)
    colors = [GREEN if value == frequency["count"].max() else "rgba(45,212,167,0.35)" for value in frequency["count"]]
    fig.add_bar(
        x=frequency["weekday"],
        y=frequency["count"],
        marker=dict(color=colors, line=dict(width=0)),
        customdata=frequency[["count", "total"]].to_numpy(),
        hovertemplate="%{x}<br>%{customdata[0]} transactions<br>\u20a6%{customdata[1]:,.0f} moved<extra></extra>",
    )
    fig.update_yaxes(title=None, showgrid=True)
    fig.update_xaxes(showgrid=False)
    return _layout(fig, height, legend=False)


def heatmap_figure(heatmap: pd.DataFrame, height: int = 360) -> go.Figure:
    fig = go.Figure()
    if heatmap is None or heatmap.empty:
        return _layout(fig, height, legend=False)
    fig.add_heatmap(
        z=heatmap.to_numpy(),
        x=[f"{h:02d}" for h in heatmap.columns],
        y=heatmap.index,
        colorscale=[
            [0.0, "rgba(17,25,35,0.0)"],
            [0.2, "rgba(45,212,167,0.18)"],
            [0.55, "rgba(45,212,167,0.55)"],
            [1.0, GREEN],
        ],
        xgap=2,
        ygap=3,
        hoverongaps=False,
        hovertemplate="%{y} at %{x}:00<br>%{z} transactions<extra></extra>",
        showscale=False,
    )
    fig.update_xaxes(showgrid=False, tickfont=dict(size=9), title=None)
    fig.update_yaxes(showgrid=False, autorange="reversed")
    return _layout(fig, height, legend=False)


def merchant_figure(merchants: pd.DataFrame, height: int = 380) -> go.Figure:
    fig = go.Figure()
    if merchants.empty:
        return _layout(fig, height, legend=False)
    data = merchants.sort_values("total", ascending=True)
    fig.add_bar(
        x=data["total"],
        y=data["merchant"],
        orientation="h",
        marker=dict(color="rgba(125,211,252,0.75)", line=dict(width=0)),
        customdata=data[["count", "avg"]].to_numpy(),
        hovertemplate="%{y}<br>\u20a6%{x:,.0f} total<br>%{customdata[0]} payments · avg \u20a6%{customdata[1]:,.0f}<extra></extra>",
    )
    fig.update_xaxes(tickprefix="\u20a6", tickformat=".2s", showgrid=True, gridcolor=GRID)
    fig.update_yaxes(showgrid=False, tickfont=dict(color=INK, size=11))
    return _layout(fig, height, legend=False)


def balance_figure(tx: pd.DataFrame, height: int = 340) -> go.Figure:
    fig = go.Figure()
    if tx.empty:
        return _layout(fig, height, legend=False)

    accounts = list(tx["account"].dropna().unique())
    has_balance = tx["balance"].notna().any()

    for i, account in enumerate(accounts):
        subset = tx.loc[tx["account"].eq(account)].sort_values("timestamp")
        color = ACCOUNT_COLORS[i % len(ACCOUNT_COLORS)]
        if has_balance:
            values = (
                subset.dropna(subset=["balance"])
                .groupby("timestamp")["balance"]
                .last()
            )
            name = account
        else:
            values = subset.set_index("timestamp")["amount"].cumsum()
            name = f"{account} (cumulative)"
        if values.empty:
            continue
        fig.add_scatter(
            x=values.index,
            y=values.to_numpy(),
            name=name,
            mode="lines",
            line=dict(color=color, width=2, shape="hv"),
            hovertemplate=f"{name}<br>%{{x|%d %b %Y}}<br>\u20a6%{{y:,.0f}}<extra></extra>",
        )

    fig.update_xaxes(tickformat="%d %b", nticks=9)
    fig.update_yaxes(tickprefix="\u20a6", tickformat=".2s")
    return _layout(fig, height)


def weekly_figure(weekly: pd.DataFrame, height: int = 320) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if weekly.empty:
        return _layout(fig, height, legend=False)
    fig.add_bar(
        x=weekly["week"],
        y=weekly["count"],
        name="Transactions",
        marker_color="rgba(45,212,167,0.5)",
        hovertemplate="Week of %{x|%d %b}<br>%{y} transactions<extra></extra>",
    )
    fig.add_scatter(
        x=weekly["week"],
        y=weekly["outflow"],
        name="Money out",
        mode="lines",
        line=dict(color=CORAL, width=1.8),
        secondary_y=True,
        hovertemplate="Week of %{x|%d %b}<br>\u20a6%{y:,.0f}<extra></extra>",
    )
    fig.update_yaxes(title="transactions", secondary_y=False)
    fig.update_yaxes(tickprefix="\u20a6", tickformat=".2s", secondary_y=True, showgrid=False)
    fig.update_xaxes(tickformat="%d %b", nticks=9)
    return _layout(fig, height)


def score_gauge(health: object, height: int = 260) -> go.Figure:
    total = int(getattr(health, "total", 0))
    color = getattr(health, "color", GREEN)
    grade = getattr(health, "grade", "—")

    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=total,
            number=dict(font=dict(size=54, color=INK, family=FONT), suffix=""),
            gauge=dict(
                axis=dict(
                    range=[0, 100],
                    tickvals=[0, 40, 55, 70, 85, 100],
                    tickfont=dict(color=MUTED, size=10),
                    tickcolor="rgba(0,0,0,0)",
                ),
                bar=dict(color=color, thickness=0.26),
                bgcolor="rgba(0,0,0,0)",
                borderwidth=0,
                steps=[
                    dict(range=[0, 40], color="rgba(248,113,113,0.13)"),
                    dict(range=[40, 55], color="rgba(251,146,60,0.12)"),
                    dict(range=[55, 70], color="rgba(251,191,36,0.12)"),
                    dict(range=[70, 85], color="rgba(125,211,252,0.12)"),
                    dict(range=[85, 100], color="rgba(45,212,167,0.14)"),
                ],
                threshold=dict(
                    line=dict(color=color, width=3),
                    thickness=0.82,
                    value=total,
                ),
            ),
        )
    )
    fig.update_layout(
        height=height,
        margin=dict(l=24, r=24, t=24, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=MUTED),
        annotations=[
            dict(
                text=f"<span style='font-size:12px;color:{color}'><b>GRADE {grade}</b></span>",
                x=0.5,
                y=0.02,
                showarrow=False,
                font=dict(size=12),
            )
        ],
    )
    return fig


def score_components_figure(health: object, height: int = 330) -> go.Figure:
    components = list(getattr(health, "components", []))
    fig = go.Figure()
    if not components:
        return _layout(fig, height, legend=False)

    labels = [c.label for c in components][::-1]
    scores = [c.score for c in components][::-1]
    displays = [c.display for c in components][::-1]
    advice = [c.advice for c in components][::-1]
    colors = [_score_color(s) for s in scores]

    fig.add_bar(
        x=scores,
        y=labels,
        orientation="h",
        marker=dict(color=colors, line=dict(width=0)),
        text=[f"{s:.0f}" for s in scores],
        textposition="outside",
        textfont=dict(color=INK, size=11),
        customdata=list(zip(displays, advice)),
        hovertemplate="<b>%{y}</b><br>%{customdata[0]}<br>Score %{x:.0f}/100<br><i>%{customdata[1]}</i><extra></extra>",
    )
    fig.add_vline(
        x=70,
        line=dict(color="rgba(232,238,246,0.25)", width=1, dash="dot"),
        annotation_text="target",
        annotation_position="top",
        annotation_font=dict(color=MUTED, size=10),
    )
    fig.update_xaxes(range=[0, 108], showgrid=True, gridcolor=GRID, ticksuffix="")
    fig.update_yaxes(showgrid=False, tickfont=dict(color=INK, size=11))
    callout = _layout(fig, height, legend=False)
    callout.update_layout(hovermode="closest")
    return callout


def _score_color(score: float) -> str:
    if score >= 80:
        return GREEN
    if score >= 60:
        return SKY
    if score >= 40:
        return AMBER
    return CORAL


def empty_state_figure(message: str, height: int = 300) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(color=MUTED, size=13, family=FONT),
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _layout(fig, height, legend=False)
