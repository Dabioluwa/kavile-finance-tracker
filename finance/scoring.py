"""Explainable 0–100 financial health score."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .format import money, pct


@dataclass
class ScoreComponent:
    key: str
    label: str
    score: float
    weight: float
    display: str
    advice: str

    @property
    def contribution(self) -> float:
        return self.score * self.weight


@dataclass
class HealthReport:
    total: int
    grade: str
    headline: str
    summary: str
    color: str
    components: list[ScoreComponent] = field(default_factory=list)

    def as_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "label": c.label,
                "score": c.score,
                "weight": c.weight,
                "display": c.display,
                "advice": c.advice,
            }
            for c in self.components
        ]


GRADE_COLORS = {
    "A": "#2DD4A7",
    "B": "#7DD3FC",
    "C": "#FBBF24",
    "D": "#FB923C",
    "E": "#F87171",
}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _score(value: float | None, good: float, bad: float) -> float:
    """Linear score where ``good`` maps to 100 and ``bad`` maps to 0."""
    if value is None:
        return 50.0
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 50.0
    if value != value:
        return 50.0
    if good == bad:
        return 100.0
    return _clamp((value - bad) / (good - bad) * 100.0)


def compute_health(kpis: dict[str, Any]) -> HealthReport:
    months = max(int(kpis.get("months", 1)), 1)
    income_base = float(kpis.get("income_base", 0.0) or 0.0)
    has_income = income_base > 0

    savings_rate = float(kpis.get("savings_rate", 0.0) or 0.0)
    expense_ratio = float(kpis.get("expense_ratio", 0.0) or 0.0)
    betting_share = float(kpis.get("betting_share", 0.0) or 0.0)
    fees_share = float(kpis.get("fees_share", 0.0) or 0.0)
    runway = max(0.0, float(kpis.get("runway_months", 0.0) or 0.0))
    positive_months = int(kpis.get("positive_months", 0) or 0)
    savings_months = int(kpis.get("savings_months", 0) or 0)

    savings_score = _score(min(savings_rate, 0.4), 0.20, 0.0) if has_income else 0.0
    spend_score = _score(expense_ratio, 0.60, 1.10) if has_income else 30.0

    if months >= 2:
        stability_score = _score(positive_months / months, 1.0, 0.20)
        consistency_score = _score(savings_months / months, 0.85, 0.10)
    else:
        stability_score = 65.0
        consistency_score = 65.0 if savings_months else 35.0

    buffer_score = _score(runway, 6.0, 0.0)
    betting_score = _score(betting_share, 0.0, 0.06)
    fee_score = _score(fees_share, 0.0, 0.025)

    components = [
        ScoreComponent(
            key="savings_rate",
            label="Savings rate",
            score=round(savings_score, 1),
            weight=0.20,
            display=(
                f"{pct(savings_rate)} of income saved"
                if has_income
                else "No income detected"
            ),
            advice=(
                "Automate at least 20% of income into savings on payday."
                if savings_score < 70
                else "Strong saving habit — keep the automation running."
            ),
        ),
        ScoreComponent(
            key="spending_control",
            label="Spending control",
            score=round(spend_score, 1),
            weight=0.22,
            display=(
                f"{pct(expense_ratio)} of income spent" if has_income else "No income detected"
            ),
            advice=(
                "Spending is outpacing income. Cap the three biggest categories."
                if spend_score < 60
                else "Spending is comfortably below income."
            ),
        ),
        ScoreComponent(
            key="stability",
            label="Cash-flow stability",
            score=round(stability_score, 1),
            weight=0.15,
            display=f"{positive_months} of {months} positive month(s)",
            advice=(
                "Build a one-month buffer so a slow month does not force borrowing."
                if stability_score < 65
                else "Most months end in the green."
            ),
        ),
        ScoreComponent(
            key="consistency",
            label="Saving consistency",
            score=round(consistency_score, 1),
            weight=0.13,
            display=f"Saved in {savings_months} of {months} month(s)",
            advice=(
                "Small, monthly deposits beat one large deposit at year end."
                if consistency_score < 65
                else "You show up for savings month after month."
            ),
        ),
        ScoreComponent(
            key="buffer",
            label="Emergency buffer",
            score=round(buffer_score, 1),
            weight=0.12,
            display=f"{runway:.1f} month(s) of expenses covered",
            advice=(
                f"Aim for 3–6 months of expenses — roughly {money(kpis.get('avg_monthly_expenses', 0) * 3)}."
                if buffer_score < 70
                else "Your buffer can absorb a real-world shock."
            ),
        ),
        ScoreComponent(
            key="betting",
            label="Betting exposure",
            score=round(betting_score, 1),
            weight=0.10,
            display=f"{pct(betting_share)} of income to betting",
            advice=(
                "Set a hard monthly betting cap or pause it for 90 days."
                if betting_score < 70
                else "Betting is a small share of income."
            ),
        ),
        ScoreComponent(
            key="fees",
            label="Fee efficiency",
            score=round(fee_score, 1),
            weight=0.08,
            display=f"{pct(fees_share)} of spending lost to fees",
            advice=(
                "Batch transfers and avoid repeated small withdrawals to cut charges."
                if fee_score < 70
                else "Fees are low relative to spending."
            ),
        ),
    ]

    weight_total = sum(c.weight for c in components)
    total = round(sum(c.score * c.weight for c in components) / weight_total)
    if total >= 85:
        grade, headline, color = "A", "Excellent financial shape", GRADE_COLORS["A"]
    elif total >= 70:
        grade, headline, color = "B", "Strong foundations", GRADE_COLORS["B"]
    elif total >= 55:
        grade, headline, color = "C", "Fair, with clear upside", GRADE_COLORS["C"]
    elif total >= 40:
        grade, headline, color = "D", "Fragile — needs attention", GRADE_COLORS["D"]
    else:
        grade, headline, color = "E", "At risk", GRADE_COLORS["E"]

    weakest = min(components, key=lambda c: c.score)
    strongest = max(components, key=lambda c: c.score)
    summary = (
        f"{strongest.label} is your strongest signal, while {weakest.label.lower()} "
        f"is holding the score back. {weakest.advice}"
    )

    return HealthReport(
        total=int(total),
        grade=grade,
        headline=headline,
        summary=summary,
        color=color,
        components=components,
    )
