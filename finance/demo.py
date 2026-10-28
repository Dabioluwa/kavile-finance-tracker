"""Generate a realistic demo statement so the app can be explored instantly.

The workbook intentionally mimics a messy OPay export:

* two sheets — Wallet and Savings
* title/blank rows before the real header
* Naira symbols and thousands separators on the wallet sheet
* day-first dates and a separate time column
* debit/credit columns on the wallet, a signed ``Type`` column on savings
* rows in newest-first order, plus a couple of failed transactions
"""

from __future__ import annotations

import io
import random
from datetime import time

import pandas as pd

START_BALANCE_WALLET = 240_000.0
START_BALANCE_SAVINGS = 85_000.0
MONTHLY_INTEREST_RATE = 0.011

FOOD = [
    ("Chowdeck", 3_500, 9_500),
    ("Chicken Republic", 2_800, 7_500),
    ("Shoprite", 4_000, 18_000),
    ("Cafe Neo", 2_500, 6_000),
    ("Kilimanjaro", 3_000, 9_000),
    ("Suya Spot", 1_500, 4_500),
]
TRANSPORT = [
    ("Bolt", 900, 4_500),
    ("Uber", 1_200, 5_500),
    ("Total Energies", 8_000, 22_000),
    ("Keke", 400, 1_200),
]
AIRTIME = [("MTN", 500, 3_000), ("Airtel", 500, 3_000), ("Glo", 500, 2_500)]
BETTING = [("Sportybet", 1_000, 7_500), ("Bet9ja", 1_000, 5_000), ("BetKing", 1_000, 4_000)]
SHOPPING = [
    ("Jumia", 8_000, 45_000),
    ("Konga", 6_000, 35_000),
    ("Jiji", 5_000, 25_000),
    ("Slot", 15_000, 60_000),
]
FRIENDS = [
    "CHINEDU OBI",
    "AMAKA EZE",
    "TUNDE BAKARE",
    "ZAINAB MUSA",
    "IBRAHIM YUSUF",
    "FUNKE ADE",
    "KOLA ADEYEMI",
]
TRANSFER_OUT_NOTES = [
    "Transfer to {name}/Rent contribution",
    "Transfer to {name}/Ref: {ref}",
    "Transfer to {name}",
    "Payment to {name}/Ref: {ref}",
]
TRANSFER_IN_NOTES = [
    "Transfer from {name}/Ref: {ref}",
    "Received from {name}",
    "Transfer from {name}/Split",
]


def _ref(rng: random.Random) -> str:
    return f"{rng.randint(10**9, 10**10 - 1)}"


def _amount(rng: random.Random, low: int, high: int) -> int:
    return int(round(rng.randint(low, high) / 50.0) * 50)


def _ts(period: pd.Period, day: int, hour: int, minute: int) -> pd.Timestamp | None:
    try:
        base = period.start_time.normalize() + pd.Timedelta(days=day - 1)
    except (ValueError, OverflowError):
        return None
    return base + pd.Timedelta(hours=hour, minutes=minute)


def _build_events(today: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = random.Random(20261028)
    start = (today - pd.DateOffset(months=11)).replace(day=1).normalize()
    periods = pd.period_range(start=start, end=today, freq="M")

    wallet: list[dict] = []
    savings: list[dict] = []

    def add_wallet(ts, description, debit=0.0, credit=0.0, status="Successful"):
        if ts is None or ts > today + pd.Timedelta(hours=23):
            return
        wallet.append(
            {
                "timestamp": ts,
                "description": description,
                "debit": float(debit),
                "credit": float(credit),
                "status": status,
            }
        )

    def add_savings(ts, description, debit=0.0, credit=0.0):
        if ts is None or ts > today + pd.Timedelta(hours=23):
            return
        savings.append(
            {
                "timestamp": ts,
                "description": description,
                "debit": float(debit),
                "credit": float(credit),
            }
        )

    for i, period in enumerate(periods):
        days_in_month = period.days_in_month

        # --- Income ---------------------------------------------------------
        salary_day = min(25, days_in_month)
        salary = 505_000 + rng.randrange(0, 45) * 1_000
        add_wallet(
            _ts(period, salary_day, 9, 12),
            "Transfer from ACME GLOBAL LIMITED/Salary",
            credit=salary,
        )
        freelance = _amount(rng, 45_000, 120_000)
        add_wallet(
            _ts(period, min(12, days_in_month), 14, 40),
            "Transfer from KLT DESIGN STUDIO/Ref: " + _ref(rng),
            credit=freelance,
        )

        # --- Recurring bills -----------------------------------------------
        add_wallet(_ts(period, min(5, days_in_month), 7, 35), "IKEDC Electricity Token", debit=_amount(rng, 9_000, 17_000))
        add_wallet(_ts(period, min(7, days_in_month), 10, 5), "DSTV Subscription", debit=12_500)
        add_wallet(_ts(period, min(13, days_in_month), 18, 20), "Netflix Subscription", debit=4_400)
        add_wallet(_ts(period, min(19, days_in_month), 9, 50), "Spectranet Internet", debit=18_000)
        add_wallet(_ts(period, min(22, days_in_month), 8, 15), "MTN Data Bundle 20GB", debit=3_500)
        add_wallet(_ts(period, min(27, days_in_month), 11, 30), "VAT", debit=rng.choice([75, 112, 150, 225]))

        # --- Savings --------------------------------------------------------
        for day in (3, 10, 17, 24):
            if day > days_in_month:
                continue
            ts = _ts(period, day, 8, 5)
            amount = _amount(rng, 15_000, 30_000)
            add_wallet(ts, "OWealth Auto-Save", debit=amount)
            add_savings(ts + pd.Timedelta(minutes=4), "Savings from Wallet", credit=amount)

        # A manual top-up now and then.
        if rng.random() < 0.5:
            ts = _ts(period, rng.randint(1, days_in_month), 20, 45)
            amount = _amount(rng, 10_000, 40_000)
            add_wallet(ts, "OWealth Savings Top-up", debit=amount)
            add_savings(ts + pd.Timedelta(minutes=3), "Savings from Wallet", credit=amount)

        # Quarterly withdrawal back to the wallet.
        if period.month in (3, 6, 9, 12) and period.end_time <= today:
            ts = period.end_time.normalize() + pd.Timedelta(hours=16, minutes=25)
            amount = _amount(rng, 40_000, 85_000)
            add_wallet(ts, "Transfer from OWealth Savings", credit=amount)
            add_savings(ts + pd.Timedelta(minutes=2), "Withdrawal to Wallet", debit=amount)

        # --- Daily habits ---------------------------------------------------
        for day in range(1, days_in_month + 1):
            if day > today.day and period == periods[-1]:
                break
            if day > today.day and period == periods[-1]:
                break
            if period == periods[-1] and day > today.day:
                break
            # Food: most days, sometimes twice.
            if rng.random() < 0.62:
                merchant, low, high = rng.choice(FOOD)
                add_wallet(
                    _ts(period, day, rng.choice([8, 12, 13, 19, 20]), rng.randint(0, 59)),
                    f"{merchant}/POS Purchase",
                    debit=_amount(rng, low, high),
                )
            if rng.random() < 0.18:
                merchant, low, high = rng.choice(FOOD)
                add_wallet(
                    _ts(period, day, 21, rng.randint(0, 59)),
                    f"{merchant}/POS Purchase",
                    debit=_amount(rng, low, high),
                )
            # Transport.
            if rng.random() < 0.48:
                merchant, low, high = rng.choice(TRANSPORT)
                add_wallet(
                    _ts(period, day, rng.choice([7, 8, 9, 17, 18]), rng.randint(0, 59)),
                    f"{merchant}/Payment",
                    debit=_amount(rng, low, high),
                )
            # Airtime / data.
            if rng.random() < 0.28:
                merchant, low, high = rng.choice(AIRTIME)
                add_wallet(
                    _ts(period, day, rng.randint(7, 22), rng.randint(0, 59)),
                    f"{merchant} Airtime Recharge",
                    debit=_amount(rng, low, high),
                )
            # Betting.
            if rng.random() < 0.3:
                merchant, low, high = rng.choice(BETTING)
                add_wallet(
                    _ts(period, day, rng.choice([13, 16, 20, 22]), rng.randint(0, 59)),
                    f"{merchant}/Deposit",
                    debit=_amount(rng, low, high),
                )
            # Occasional shopping.
            if rng.random() < 0.055:
                merchant, low, high = rng.choice(SHOPPING)
                add_wallet(
                    _ts(period, day, rng.randint(10, 21), rng.randint(0, 59)),
                    f"{merchant}/Order",
                    debit=_amount(rng, low, high),
                )
            # Health.
            if rng.random() < 0.035:
                add_wallet(
                    _ts(period, day, rng.randint(9, 20), rng.randint(0, 59)),
                    "HealthPlus Pharmacy",
                    debit=_amount(rng, 3_000, 15_000),
                )
            # ATM cash.
            if rng.random() < 0.055:
                add_wallet(
                    _ts(period, day, rng.randint(8, 19), rng.randint(0, 59)),
                    "ATM Withdrawal",
                    debit=_amount(rng, 20_000, 50_000),
                )
            # Transfers to friends.
            if rng.random() < 0.10:
                name = rng.choice(FRIENDS)
                note = rng.choice(TRANSFER_OUT_NOTES).format(name=name, ref=_ref(rng))
                add_wallet(
                    _ts(period, day, rng.randint(9, 22), rng.randint(0, 59)),
                    note,
                    debit=_amount(rng, 5_000, 35_000),
                )
            # Transfers from friends.
            if rng.random() < 0.07:
                name = rng.choice(FRIENDS)
                note = rng.choice(TRANSFER_IN_NOTES).format(name=name, ref=_ref(rng))
                add_wallet(
                    _ts(period, day, rng.randint(9, 22), rng.randint(0, 59)),
                    note,
                    credit=_amount(rng, 5_000, 60_000),
                )

        # --- Occasional extras ---------------------------------------------
        if i % 3 == 0:
            add_wallet(
                _ts(period, min(15, days_in_month), 12, 10),
                "Udemy Course",
                debit=12_800,
            )
        if i % 2 == 0:
            add_wallet(
                _ts(period, min(21, days_in_month), 19, 30),
                "Silverbird Cinemas",
                debit=_amount(rng, 8_000, 15_000),
            )

    wallet_df = pd.DataFrame(wallet).sort_values("timestamp").reset_index(drop=True)
    savings_df = pd.DataFrame(savings).sort_values("timestamp").reset_index(drop=True)

    # Credit interest monthly on the end-of-month savings balance.
    interest_rows: list[dict] = []
    running = START_BALANCE_SAVINGS
    for period in periods:
        month_end = period.end_time.normalize() + pd.Timedelta(hours=23, minutes=59)
        if month_end > today:
            continue
        month_rows = savings_df.loc[
            (savings_df["timestamp"].dt.to_period("M") == period)
        ]
        running += float(month_rows["credit"].sum() - month_rows["debit"].sum())
        interest = round(max(running, 0.0) * MONTHLY_INTEREST_RATE, 2)
        if interest > 0:
            interest_rows.append(
                {
                    "timestamp": month_end,
                    "description": "OWealth Interest Earned",
                    "debit": 0.0,
                    "credit": interest,
                }
            )
            running += interest
    if interest_rows:
        savings_df = pd.concat(
            [savings_df, pd.DataFrame(interest_rows)], ignore_index=True
        ).sort_values("timestamp")

    # Running balances.
    wallet_df["balance"] = (
        START_BALANCE_WALLET + wallet_df["credit"].cumsum() - wallet_df["debit"].cumsum()
    )
    savings_df["balance"] = (
        START_BALANCE_SAVINGS + savings_df["credit"].cumsum() - savings_df["debit"].cumsum()
    )

    # Add two failed rows (they are excluded during cleaning and should not
    # affect balances).
    failed_at = today - pd.Timedelta(days=9)
    wallet_df = pd.concat(
        [
            wallet_df,
            pd.DataFrame(
                [
                    {
                        "timestamp": failed_at.replace(hour=15, minute=22),
                        "description": "Sportybet/Deposit",
                        "debit": 50_000.0,
                        "credit": 0.0,
                        "status": "Failed",
                        "balance": None,
                    },
                    {
                        "timestamp": failed_at.replace(hour=18, minute=4),
                        "description": "Transfer to CHINEDU OBI/Ref: 9912034812",
                        "debit": 120_000.0,
                        "credit": 0.0,
                        "status": "Failed",
                        "balance": None,
                    },
                ]
            ),
        ],
        ignore_index=True,
    ).sort_values("timestamp")

    # If the wallet would dip below a sensible floor, lift the opening balance.
    minimum = float(wallet_df["balance"].min())
    if minimum < 15_000:
        lift = 15_000 - minimum
        wallet_df["balance"] = wallet_df["balance"] + lift

    return wallet_df.sort_values("timestamp", ascending=False), savings_df.sort_values(
        "timestamp", ascending=False
    )


def _naira(value: float) -> str:
    return f"\u20a6{value:,.2f}"


def build_demo_workbook(today: pd.Timestamp | None = None) -> bytes:
    """Create the demo .xlsx file in memory."""
    today = (today or pd.Timestamp.today()).normalize()
    wallet, savings = _build_events(today)

    wallet_export = pd.DataFrame(
        {
            "Date": wallet["timestamp"].dt.strftime("%d/%m/%Y"),
            "Time": wallet["timestamp"].dt.strftime("%H:%M:%S"),
            "Transaction Details": wallet["description"],
            "Debit (\u20a6)": [
                _naira(v) if v > 0 else "" for v in wallet["debit"]
            ],
            "Credit (\u20a6)": [
                _naira(v) if v > 0 else "" for v in wallet["credit"]
            ],
            "Balance (\u20a6)": [
                _naira(v) if pd.notna(v) else "" for v in wallet["balance"]
            ],
            "Status": wallet["status"],
        }
    )

    savings_export = pd.DataFrame(
        {
            "Transaction Date": savings["timestamp"].dt.normalize(),
            "Narration": savings["description"],
            "Amount": savings["credit"] - savings["debit"],
            "Type": ["Credit" if c > 0 else "Debit" for c in savings["credit"]],
            "Balance": savings["balance"],
        }
    )

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        title = pd.DataFrame(
            [
                ["OPAY DIGITAL SERVICES — WALLET STATEMENT"],
                [f"Account holder: ADEBAYO O.   |   Period: {wallet['timestamp'].min():%d %b %Y} – {wallet['timestamp'].max():%d %b %Y}"],
                [""],
            ]
        )
        title.to_excel(writer, sheet_name="Wallet", header=False, index=False)
        wallet_export.to_excel(
            writer, sheet_name="Wallet", index=False, startrow=3
        )

        title_savings = pd.DataFrame(
            [
                ["OPAY DIGITAL SERVICES — SAVINGS (OWEALTH) STATEMENT"],
                [f"Account holder: ADEBAYO O.   |   Period: {savings['timestamp'].min():%d %b %Y} – {savings['timestamp'].max():%d %b %Y}"],
                [""],
            ]
        )
        title_savings.to_excel(writer, sheet_name="Savings", header=False, index=False)
        savings_export.to_excel(
            writer, sheet_name="Savings", index=False, startrow=3
        )

        # Tidy column widths for anyone opening the sample file directly.
        from openpyxl.utils import get_column_letter

        for sheet_name, widths in (
            ("Wallet", [12, 10, 48, 16, 16, 18, 12]),
            ("Savings", [18, 34, 16, 10, 16]),
        ):
            sheet = writer.sheets[sheet_name]
            for idx, width in enumerate(widths, start=1):
                sheet.column_dimensions[get_column_letter(idx)].width = width

    return buffer.getvalue()


def demo_csv_bytes(today: pd.Timestamp | None = None) -> bytes:
    """A single-sheet CSV version of the demo (handy for testing CSV import)."""
    today = (today or pd.Timestamp.today()).normalize()
    wallet, _ = _build_events(today)
    export = pd.DataFrame(
        {
            "Date": wallet["timestamp"].dt.strftime("%d/%m/%Y"),
            "Time": wallet["timestamp"].dt.strftime("%H:%M"),
            "Description": wallet["description"],
            "Amount": wallet["credit"] - wallet["debit"],
            "Balance": wallet["balance"],
        }
    )
    return export.to_csv(index=False).encode("utf-8")
