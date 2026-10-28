"""Statement ingestion and cleaning.

The cleaner accepts messy, real-world bank exports (Excel workbooks with
title rows, dual Wallet/Savings sheets, Naira symbols, comma grouped numbers,
day-first dates, separate debit/credit columns or a single signed amount) and
returns one tidy transaction table.

Canonical output columns
------------------------
``timestamp``, ``date``, ``description``, ``debit``, ``credit``, ``amount``,
``balance``, ``account``, ``sheet``, ``status``, ``txn_type``, ``reference``
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

CANONICAL_COLUMNS = [
    "timestamp",
    "date",
    "description",
    "debit",
    "credit",
    "amount",
    "balance",
    "account",
    "sheet",
    "status",
    "txn_type",
    "reference",
]

_CURRENCY_TOKENS = re.compile(
    r"(?i)\b(?:ngn|naira|usd|eur|gbp|ghs|kes|zar|rwd)\b|[\u20a6$\u20ac\u00a3\u00a5]"
)
_SPACES = re.compile(r"[\s\u00a0\u200b]+")
_CREDIT_HINTS = re.compile(
    r"(?i)\b(?:credit(?:ed)?|received|inward|deposit(?:ed)?|refund(?:ed)?|"
    r"reversal|interest|salary|inflow|money\s+in|payment\s+from|transfer\s+from|"
    r"cashback|reimburs\w*)\b"
)
_BAD_STATUS = re.compile(
    r"(?i)\b(?:failed|declined|cancelled|canceled|rejected|unsuccessful|error|reversed?)\b"
)
_TOTAL_ROW = re.compile(
    r"(?i)^(?:total|totals|sub\s*total|opening\s*balance|closing\s*balance|"
    r"available\s*balance|summary|grand\s*total)\b"
)


class StatementError(ValueError):
    """Raised when an uploaded file cannot be interpreted as a statement."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class StatementData:
    """A cleaned statement plus provenance about the files it came from."""

    transactions: pd.DataFrame
    warnings: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    sheet_summary: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def accounts(self) -> list[str]:
        if self.transactions.empty:
            return []
        return sorted(self.transactions["account"].dropna().unique().tolist())

    @property
    def start(self) -> pd.Timestamp | None:
        if self.transactions.empty:
            return None
        return self.transactions["timestamp"].min()

    @property
    def end(self) -> pd.Timestamp | None:
        if self.transactions.empty:
            return None
        return self.transactions["timestamp"].max()


def load_statement_files(files: Sequence[tuple[str, bytes]]) -> StatementData:
    """Read and clean one or more uploaded statement files.

    ``files`` is a sequence of ``(filename, raw_bytes)`` pairs.
    """
    if not files:
        raise StatementError("No files were provided.")

    frames: list[pd.DataFrame] = []
    warnings: list[str] = []
    used_files: list[str] = []
    summaries: list[dict] = []

    for filename, payload in files:
        if not payload:
            warnings.append(f"{filename}: the file is empty and was skipped.")
            continue

        try:
            sheets = _read_raw_sheets(filename, payload)
        except StatementError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise StatementError(f"Could not open {filename}: {exc}") from exc

        parsed_in_file = 0
        for sheet_name, raw in sheets.items():
            label = str(sheet_name) if sheet_name is not None else "Sheet"
            try:
                frame, sheet_warnings = _parse_sheet(raw, label, filename)
            except StatementError as exc:
                warnings.append(f"{filename} · {label}: {exc}")
                continue

            if frame.empty:
                warnings.append(f"{filename} · {label}: no transactions found on this sheet.")
                continue

            frames.append(frame)
            warnings.extend(f"{filename} · {label}: {w}" for w in sheet_warnings)
            used_files.append(filename)
            parsed_in_file += 1
            summaries.append(
                {
                    "file": filename,
                    "sheet": label,
                    "account": ", ".join(sorted(frame["account"].unique())),
                    "transactions": len(frame),
                    "first": frame["timestamp"].min(),
                    "last": frame["timestamp"].max(),
                    "money_in": frame["credit"].sum(),
                    "money_out": frame["debit"].sum(),
                }
            )

        if parsed_in_file == 0 and not any(f.startswith(filename) for f in warnings):
            warnings.append(f"{filename}: no transaction table was recognised.")

    if not frames:
        raise StatementError(
            "No transaction rows were found. Make sure the file contains columns "
            "such as Date, Description/Narration and Debit/Credit or Amount."
        )

    tx = pd.concat(frames, ignore_index=True)
    tx = tx.dropna(subset=["timestamp", "amount"])
    tx = tx[tx["amount"].abs() > 0]
    tx = tx.sort_values(["account", "timestamp"], kind="stable").reset_index(drop=True)

    # Multiple overlapping exports often contain the same rows twice.
    if len(used_files) > 1:
        subset = ["account", "timestamp", "description", "amount"]
        before = len(tx)
        tx = tx.drop_duplicates(subset=subset, keep="first").reset_index(drop=True)
        removed = before - len(tx)
        if removed:
            warnings.append(
                f"Removed {removed:,} duplicate transaction(s) found across the uploaded files."
            )

    tx["txn_id"] = np.arange(1, len(tx) + 1)
    tx = tx[["txn_id", *CANONICAL_COLUMNS]]

    for col in ("debit", "credit", "amount", "balance"):
        tx[col] = pd.to_numeric(tx[col], errors="coerce").astype(float)
    for col in ("description", "account", "sheet", "status", "txn_type", "reference"):
        tx[col] = tx[col].fillna("").astype(str)

    summary = pd.DataFrame(summaries)
    return StatementData(
        transactions=tx,
        warnings=_dedupe_warnings(warnings),
        files=list(dict.fromkeys(used_files)),
        sheet_summary=summary,
    )


# ---------------------------------------------------------------------------
# File readers
# ---------------------------------------------------------------------------


def _read_raw_sheets(filename: str, payload: bytes) -> dict[str, pd.DataFrame]:
    suffix = Path(filename).suffix.lower()
    stem = Path(filename).stem[:60] or "Statement"

    if suffix in {".xlsx", ".xlsm", ".xls"}:
        engine = "openpyxl" if suffix in {".xlsx", ".xlsm"} else None
        try:
            sheets = pd.read_excel(
                io.BytesIO(payload),
                sheet_name=None,
                header=None,
                dtype=object,
                engine=engine,
            )
        except ImportError as exc:  # e.g. legacy .xls without xlrd
            raise StatementError(
                "Reading legacy .xls files needs the 'xlrd' package. "
                "Install it with: pip install xlrd"
            ) from exc
        except Exception as exc:
            raise StatementError(f"Could not read the workbook: {exc}") from exc
        return {str(k) if k is not None else "Sheet": v for k, v in sheets.items()}

    if suffix in {".csv", ".txt", ""}:
        text = _decode(payload)
        delimiter = _sniff_delimiter(text)
        try:
            frame = pd.read_csv(
                io.StringIO(text),
                header=None,
                sep=delimiter,
                dtype=object,
                skip_blank_lines=False,
                on_bad_lines="skip",
            )
        except Exception as exc:
            raise StatementError(f"Could not read the CSV file: {exc}") from exc
        return {stem: frame}

    raise StatementError(
        f"'{suffix or filename}' is not a supported file type. Upload .xlsx, .xls or .csv."
    )


def _decode(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return payload.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return payload.decode("utf-8", errors="replace")


def _sniff_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        # Fall back to whichever candidate appears most often in the sample.
        counts = {d: sample.count(d) for d in (",", ";", "\t", "|")}
        best = max(counts, key=counts.get)
        return best if counts[best] else ","


# ---------------------------------------------------------------------------
# Sheet parsing
# ---------------------------------------------------------------------------


def _parse_sheet(
    raw: pd.DataFrame, sheet_name: str, filename: str
) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []

    if raw is None or len(raw) == 0:
        return pd.DataFrame(columns=CANONICAL_COLUMNS), warnings

    raw = raw.dropna(how="all").dropna(axis=1, how="all")
    if raw.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS), warnings

    raw = raw.reset_index(drop=True)
    header_idx, mapping = _find_header(raw)
    if header_idx is None or mapping is None:
        raise StatementError("no recognisable header row (Date / Description / Amount) was found.")

    body = raw.iloc[header_idx + 1 :].reset_index(drop=True)
    if body.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS), warnings

    cols = _extract_columns(body, mapping)

    # Some exports label the date column differently on every page; drop rows
    # that simply repeat the header.
    status = cols.get("status")
    if status is not None:
        bad = status.fillna("").astype(str).str.contains(_BAD_STATUS, regex=True)
        dropped = int(bad.sum())
        if dropped:
            warnings.append(f"{dropped:,} failed/declined row(s) were excluded.")
            keep = ~bad
            body = body.loc[keep.to_numpy()].reset_index(drop=True)
            cols = {k: v.loc[keep.to_numpy()].reset_index(drop=True) for k, v in cols.items()}
            status = cols.get("status")

    timestamps = _parse_datetime(cols.get("date"))
    if timestamps is None or timestamps.notna().sum() == 0:
        raise StatementError("the date column could not be parsed.")

    if cols.get("time") is not None:
        timestamps = _combine_time(timestamps, cols["time"])

    description = _build_description(cols)
    balance = _parse_money_series(cols.get("balance"))

    amount, amount_warnings = _build_amount(body, cols, timestamps, sheet_name)
    warnings.extend(amount_warnings)

    account = _build_account(cols.get("account"), sheet_name, len(body))
    txn_type = _text_series(cols.get("type")) if cols.get("type") is not None else pd.Series("", index=body.index)
    reference = (
        _text_series(cols.get("reference")) if cols.get("reference") is not None else pd.Series("", index=body.index)
    )
    status = status if status is not None else pd.Series("", index=body.index)

    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "description": description,
            "amount": amount,
            "balance": balance,
            "account": account,
            "status": status.fillna("").astype(str).str.strip(),
            "txn_type": txn_type,
            "reference": reference,
        }
    )

    valid_date = frame["timestamp"].notna()
    valid_amount = frame["amount"].notna()
    missing_dates = int((valid_amount & ~valid_date).sum())
    missing_amounts = int((valid_date & ~valid_amount).sum())

    frame = frame.loc[valid_date & valid_amount].copy()
    if frame.empty:
        raise StatementError("rows were found but none had both a valid date and amount.")

    if description.str.strip().eq("").all():
        warnings.append(
            "No description/narration column was detected; categorisation will be limited."
        )

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame["date"] = frame["timestamp"].dt.normalize()
    frame["debit"] = (-frame["amount"]).clip(lower=0)
    frame["credit"] = frame["amount"].clip(lower=0)
    frame["sheet"] = sheet_name

    # Drop rows whose description is a totals line.
    totals = frame["description"].fillna("").str.contains(_TOTAL_ROW, regex=True)
    if totals.any():
        frame = frame.loc[~totals].copy()

    if missing_dates:
        warnings.append(
            f"{missing_dates:,} row(s) with no readable date were skipped."
        )
    if missing_amounts:
        warnings.append(
            f"{missing_amounts:,} row(s) with no readable amount were skipped."
        )

    frame = frame.sort_values("timestamp", kind="stable").reset_index(drop=True)
    return frame, warnings


def _extract_columns(body: pd.DataFrame, mapping: dict[str, list[int]]) -> dict[str, pd.Series]:
    """Turn positional header matches into named series."""
    cols: dict[str, pd.Series] = {}
    for cls, indices in mapping.items():
        if not indices:
            continue
        idx = indices[0]
        if idx >= body.shape[1]:
            continue
        cols[cls] = body.iloc[:, idx]
        if cls == "description":
            extras = [i for i in indices[1:] if i < body.shape[1]]
            if extras:
                extra_text = pd.concat(
                    [_text_series(body.iloc[:, i]) for i in extras], axis=1
                ).agg(" ".join, axis=1)
                cols["description_extra"] = extra_text
    return cols


def _build_description(cols: dict[str, pd.Series]) -> pd.Series:
    if cols.get("description") is None:
        if cols.get("type") is not None:
            base = _text_series(cols["type"])
        else:
            base = pd.Series("", index=cols["date"].index)
    else:
        base = _text_series(cols["description"])

    extra = cols.get("description_extra")
    if extra is not None:
        extra = _text_series(extra)
        mask = extra.str.len() > 0
        base = base.where(~mask, (base + " · " + extra).str.strip(" ·"))
    return base


def _text_series(series: pd.Series) -> pd.Series:
    """Normalise a free-text column without leaving literal 'nan' strings."""
    text = series.where(series.notna(), "").astype(str)
    text = text.str.replace(r"\s+", " ", regex=True).str.strip()
    text = text.replace({"nan": "", "None": "", "NaT": ""})
    return text


def _clean_number_text(value: object) -> str:
    return str(value).strip()


# ---------------------------------------------------------------------------
# Amounts
# ---------------------------------------------------------------------------


def parse_amount(value: object) -> float:
    """Parse a messy currency cell into a float.

    Handles ``₦1,234.50``, ``1 234,56``, ``(2,000)``, ``1,000 DR`` and
    ordinary numeric cells. Returns ``nan`` when nothing numeric is present.
    """
    if value is None:
        return np.nan
    if isinstance(value, (int, float, np.integer, np.floating)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return np.nan
    if isinstance(value, bool):
        return float(value)

    text = _clean_number_text(value)
    if not text or text.lower() in {"-", "--", "nan", "none", "n/a", "na", "nil", "null"}:
        return np.nan

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]

    if re.search(r"(?i)\b(dr|debit|withdrawal)\b", text):
        negative = True
    elif re.search(r"(?i)\b(cr|credit|deposit)\b", text):
        negative = False

    text = _CURRENCY_TOKENS.sub("", text)
    text = _SPACES.sub("", text)

    # Normalise separators (Naira exports use commas for thousands).
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            # European style: 1.234,56
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        # A single comma followed by one or two digits is a decimal comma.
        if len(re.findall(",", text)) == 1 and re.search(r",\d{1,2}$", text):
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")

    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return np.nan
    number = float(match.group(0))
    if negative:
        number = -abs(number)
    return number


def _parse_money_series(series: pd.Series | None) -> pd.Series | None:
    if series is None:
        return None
    return series.map(parse_amount).astype(float)


def _build_amount(
    body: pd.DataFrame,
    cols: dict[str, pd.Series],
    timestamps: pd.Series,
    sheet_name: str,
) -> tuple[pd.Series, list[str]]:
    warnings: list[str] = []
    index = body.index

    debit_raw = _parse_money_series(cols.get("debit"))
    credit_raw = _parse_money_series(cols.get("credit"))
    amount_raw = _parse_money_series(cols.get("amount"))

    has_debit = debit_raw is not None and debit_raw.notna().any()
    has_credit = credit_raw is not None and credit_raw.notna().any()

    if has_debit or has_credit:
        debit = debit_raw.fillna(0).abs() if debit_raw is not None else pd.Series(0.0, index=index)
        credit = credit_raw.fillna(0).abs() if credit_raw is not None else pd.Series(0.0, index=index)
        amount = credit - debit
        # If the template has empty debit/credit columns but a usable amount,
        # prefer the single amount column.
        if amount.abs().sum() == 0 and amount_raw is not None and amount_raw.notna().any():
            amount = amount_raw
        else:
            both = (debit > 0) & (credit > 0)
            if both.any():
                warnings.append(
                    f"{int(both.sum()):,} row(s) had both debit and credit values; "
                    "the net amount was used."
                )
            return amount, warnings

    if amount_raw is None or not amount_raw.notna().any():
        raise StatementError("no debit, credit or amount column could be found.")

    amount = amount_raw.copy()
    type_series = cols.get("type")
    type_text = _text_series(type_series).str.lower() if type_series is not None else pd.Series("", index=index)

    debit_mask = type_text.str.contains(
        r"\b(?:debit|dr|withdrawal|withdrew|out|outflow|payment|expense)\b", regex=True
    )
    credit_mask = type_text.str.contains(
        r"\b(?:credit|cr|deposit|in|inflow|receipt|received)\b", regex=True
    ) & ~debit_mask

    amount.loc[debit_mask & amount.notna()] = -amount.loc[debit_mask & amount.notna()].abs()
    amount.loc[credit_mask & amount.notna()] = amount.loc[credit_mask & amount.notna()].abs()

    # Still ambiguous? Use running balance deltas, then description language.
    ambiguous = amount.notna() & (amount > 0) & ~debit_mask & ~credit_mask
    used_balance = 0
    if ambiguous.any():
        balance = _parse_money_series(cols.get("balance"))
        if balance is not None and balance.notna().sum() > 1:
            oriented, used_balance = _orient_with_balance(amount, balance, timestamps, sheet_name)
            amount = oriented
            ambiguous = amount.notna() & (amount > 0) & ~debit_mask & ~credit_mask

    used_keywords = 0
    if ambiguous.any():
        description = _build_description(cols)
        credit_hint = description.str.contains(_CREDIT_HINTS, regex=True) & ambiguous
        amount.loc[credit_hint] = amount.loc[credit_hint].abs()
        ambiguous = ambiguous & ~credit_hint
        # Anything left is treated as money out, the common case in a wallet.
        amount.loc[ambiguous] = -amount.loc[ambiguous].abs()
        used_keywords = int(ambiguous.sum())

    if used_balance:
        warnings.append(
            f"Direction for {used_balance:,} row(s) was inferred from the running balance."
        )
    if used_keywords:
        warnings.append(
            f"Direction for {used_keywords:,} row(s) without a debit/credit marker "
            "was inferred from the description."
        )

    return amount, warnings


def _orient_with_balance(
    amount: pd.Series,
    balance: pd.Series,
    timestamps: pd.Series,
    account: str,
) -> tuple[pd.Series, int]:
    """Flip unsigned amounts using changes in the running balance."""
    tmp = pd.DataFrame(
        {
            "amount": amount,
            "balance": balance,
            "timestamp": pd.to_datetime(timestamps, errors="coerce"),
            "order": np.arange(len(amount)),
        }
    ).sort_values(["timestamp", "order"], kind="stable")

    delta = tmp["balance"].diff()
    tolerance = (tmp["amount"].abs() * 0.01).clip(lower=0.02)
    usable = (
        tmp["amount"].notna()
        & (tmp["amount"] > 0)
        & delta.notna()
        & (delta.abs() > 0.005)
        & ((delta.abs() - tmp["amount"].abs()).abs() <= tolerance)
    )

    oriented = tmp["amount"].copy()
    oriented.loc[usable] = tmp.loc[usable, "amount"].abs() * np.sign(delta.loc[usable])
    oriented = oriented.reindex(amount.index)
    return oriented, int(usable.sum())


# ---------------------------------------------------------------------------
# Dates and times
# ---------------------------------------------------------------------------


def _parse_datetime(series: pd.Series | None) -> pd.Series | None:
    if series is None:
        return None
    if pd.api.types.is_datetime64_any_dtype(series):
        parsed = pd.to_datetime(series, errors="coerce")
        if getattr(parsed.dt, "tz", None) is not None:
            parsed = parsed.dt.tz_localize(None)
        return parsed

    numeric = pd.to_numeric(series, errors="coerce")
    serial_mask = numeric.notna() & numeric.between(20_000, 80_000)
    if serial_mask.mean() > 0.6:
        parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
        parsed.loc[serial_mask] = pd.to_datetime(
            numeric.loc[serial_mask], unit="D", origin="1899-12-30", errors="coerce"
        )
        text_mask = ~serial_mask
        if text_mask.any():
            parsed.loc[text_mask] = _parse_datetime_text(series.loc[text_mask])
        return parsed

    return _parse_datetime_text(series)


def _infer_dayfirst(series: pd.Series) -> bool:
    first_greater = 0
    second_greater = 0
    for value in series.dropna().astype(str).head(400):
        match = re.match(r"\s*(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", value)
        if not match:
            continue
        a, b = int(match.group(1)), int(match.group(2))
        if a > 12:
            first_greater += 1
        if b > 12:
            second_greater += 1
    return second_greater <= first_greater


def _parse_datetime_text(series: pd.Series) -> pd.Series:
    preferred = _infer_dayfirst(series)
    best: pd.Series | None = None
    best_count = -1
    for dayfirst in (preferred, not preferred):
        try:
            parsed = pd.to_datetime(
                series, errors="coerce", dayfirst=dayfirst, format="mixed"
            )
        except (ValueError, TypeError):
            try:
                parsed = pd.to_datetime(series, errors="coerce", dayfirst=dayfirst)
            except (ValueError, TypeError):
                parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
        if getattr(parsed.dt, "tz", None) is not None:
            parsed = parsed.dt.tz_localize(None)
        count = int(parsed.notna().sum())
        if count > best_count:
            best, best_count = parsed, count
    return best if best is not None else pd.Series(pd.NaT, index=series.index)


def _combine_time(timestamps: pd.Series, raw_time: pd.Series) -> pd.Series:
    """Attach a separate time column to a date column."""
    index = timestamps.index
    numeric = pd.to_numeric(raw_time, errors="coerce")

    offsets: pd.Series
    if numeric.notna().mean() >= 0.75 and numeric.notna().any():
        fraction = numeric.where(numeric.between(0, 1, inclusive="neither"))
        if fraction.notna().any():
            offsets = pd.to_timedelta((fraction * 86_400).round(), unit="s")
        else:
            offsets = pd.Series(pd.NaT, index=index, dtype="timedelta64[ns]")
    else:
        extracted = raw_time.astype(str).str.extract(
            r"(?i)(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(am|pm)?"
        )
        hours = pd.to_numeric(extracted[0], errors="coerce")
        minutes = pd.to_numeric(extracted[1], errors="coerce")
        seconds = pd.to_numeric(extracted[2], errors="coerce").fillna(0)
        suffix = extracted[3].fillna("").str.lower()
        hours = hours.mask((suffix == "pm") & (hours < 12), hours + 12)
        hours = hours.mask((suffix == "am") & (hours == 12), 0)
        offsets = (
            pd.to_timedelta(hours, unit="h")
            + pd.to_timedelta(minutes, unit="m")
            + pd.to_timedelta(seconds, unit="s")
        )

    offsets = offsets.reindex(index)
    combined = timestamps.copy()
    mask = offsets.notna() & timestamps.notna()
    combined.loc[mask] = (
        timestamps.loc[mask].dt.normalize() + offsets.loc[mask]
    )
    return combined


# ---------------------------------------------------------------------------
# Header detection
# ---------------------------------------------------------------------------

_DATE_HEADERS = {
    "date",
    "transaction date",
    "trans date",
    "trans. date",
    "value date",
    "posting date",
    "posted date",
    "txn date",
    "timestamp",
    "date time",
}
_TIME_HEADERS = {"time", "transaction time", "trans time", "txn time", "time of transaction"}
_BALANCE_HEADERS = {
    "balance",
    "running balance",
    "available balance",
    "closing balance",
    "ledger balance",
    "balance ngn",
}
_DEBIT_HEADERS = {
    "debit",
    "debit amount",
    "withdrawal",
    "withdrawals",
    "money out",
    "amount out",
    "dr",
    "dr amount",
}
_CREDIT_HEADERS = {
    "credit",
    "credit amount",
    "deposit",
    "deposits",
    "money in",
    "amount in",
    "cr",
    "cr amount",
}
_AMOUNT_HEADERS = {"amount", "transaction amount", "amt", "value", "transaction value"}
_DESC_HINTS = ("description", "narration", "details", "remarks", "remark", "particulars", "particular", "memo")
_TYPE_HEADERS = {"type", "transaction type", "txn type", "dr cr", "drcr", "direction", "entry type"}
_STATUS_HEADERS = {"status", "transaction status", "txn status"}
_REF_HINTS = ("reference", "ref no", "ref", "transaction ref", "trans ref", "trx ref")
_ACCOUNT_HEADERS = {"account", "wallet", "source", "sub account", "account type", "account name"}
_CATEGORY_HINTS = ("category",)


def _normalise_header(value: object) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _classify_header(value: object) -> str | None:
    header = _normalise_header(value)
    if not header or header.isdigit():
        return None

    stripped = re.sub(r"\s*(ngn|naira|usd|gbp|eur)\s*$", "", header).strip()
    stripped = stripped.strip("() ").strip()

    if header in _DATE_HEADERS or stripped in _DATE_HEADERS:
        return "date"
    if "date" in header and "time" not in header and "update" not in header:
        return "date"
    if header in _TIME_HEADERS:
        return "time"
    if header in _BALANCE_HEADERS or stripped in _BALANCE_HEADERS:
        return "balance"
    if header in _DEBIT_HEADERS or stripped in _DEBIT_HEADERS:
        return "debit"
    if header in _CREDIT_HEADERS or stripped in _CREDIT_HEADERS:
        return "credit"
    if header in _AMOUNT_HEADERS or stripped in _AMOUNT_HEADERS:
        return "amount"
    if any(hint in header for hint in _DESC_HINTS):
        return "description"
    if header in _TYPE_HEADERS:
        return "type"
    if header in _STATUS_HEADERS:
        return "status"
    if any(hint in header for hint in _REF_HINTS):
        return "reference"
    if header in _ACCOUNT_HEADERS:
        return "account"
    if any(hint in header for hint in _CATEGORY_HINTS):
        return "category"
    return None


def _find_header(raw: pd.DataFrame) -> tuple[int | None, dict[str, list[int]] | None]:
    best_idx: int | None = None
    best_mapping: dict[str, list[int]] | None = None
    best_score = 0

    limit = min(len(raw), 30)
    for row_idx in range(limit):
        mapping: dict[str, list[int]] = {}
        for col_idx, value in enumerate(raw.iloc[row_idx].tolist()):
            if value is None or (isinstance(value, float) and np.isnan(value)):
                continue
            cls = _classify_header(value)
            if cls:
                mapping.setdefault(cls, []).append(col_idx)
        if not mapping:
            continue

        score = 0
        if "date" in mapping:
            score += 6
        if "description" in mapping:
            score += 4
        if "debit" in mapping or "credit" in mapping:
            score += 4
        if "amount" in mapping:
            score += 4
        if "balance" in mapping:
            score += 2
        score += min(len(mapping), 6)

        has_money = any(k in mapping for k in ("debit", "credit", "amount", "balance"))
        if "date" in mapping and (has_money or "description" in mapping) and score > best_score:
            best_idx, best_mapping, best_score = row_idx, mapping, score

    if best_idx is None or best_score < 8:
        return None, None

    # Keep only the most useful columns when a header repeats (e.g. two dates).
    cleaned: dict[str, list[int]] = {}
    for key, indices in best_mapping.items():
        if key in {"date", "amount", "balance", "debit", "credit", "type", "status", "reference", "account"}:
            cleaned[key] = indices[:1]
        elif key == "description":
            cleaned[key] = indices[:3]
        else:
            cleaned[key] = indices[:1]
    return best_idx, cleaned


# ---------------------------------------------------------------------------
# Account labels
# ---------------------------------------------------------------------------


def _build_account(raw_account: pd.Series | None, sheet_name: str, rows: int) -> pd.Series:
    default = _account_from_sheet(sheet_name)
    if raw_account is None:
        return pd.Series(default, index=range(rows))

    values = _text_series(raw_account).reset_index(drop=True)
    meaningful = values[values.str.len() > 0]
    if meaningful.empty or meaningful.nunique() > 8:
        return pd.Series(default, index=range(rows))
    if meaningful.str.len().max() > 24:
        return pd.Series(default, index=range(rows))

    return values.where(values.str.len() > 0, default).str.title()


def _account_from_sheet(sheet_name: str) -> str:
    name = re.sub(r"(?i)\b(statement|transactions?|account|history|details|sheet)\b", " ", sheet_name)
    name = re.sub(r"\s+", " ", name).strip(" -_")
    key = name.lower()
    if not name:
        return "Statement"
    if any(word in key for word in ("saving", "owealth", "o wealth", "invest", "target")):
        return "Savings"
    if "wallet" in key:
        return "Wallet"
    if "current" in key:
        return "Current"
    if key in {"sheet1", "sheet 1", "sheet2", "sheet 2"}:
        return "Statement"
    return name.title()


def _dedupe_warnings(warnings: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for warning in warnings:
        if warning not in seen:
            seen.add(warning)
            output.append(warning)
    return output
