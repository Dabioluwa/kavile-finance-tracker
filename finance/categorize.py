"""Rule-based transaction categorisation and merchant normalisation."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable, Sequence

import pandas as pd

# ---------------------------------------------------------------------------
# Category taxonomy
# ---------------------------------------------------------------------------

CATEGORY_META: dict[str, dict[str, str]] = {
    "Salary & Income": {"group": "Income", "color": "#34D399"},
    "OWealth Interest": {"group": "Income", "color": "#2DD4A7"},
    "Transfers In": {"group": "Income", "color": "#5EEAD4"},
    "Other Income": {"group": "Income", "color": "#7DD3FC"},
    "Savings & Investments": {"group": "Savings", "color": "#38BDF8"},
    "Food & Groceries": {"group": "Essentials", "color": "#FBBF24"},
    "Airtime & Data": {"group": "Essentials", "color": "#F59E0B"},
    "Transport": {"group": "Essentials", "color": "#60A5FA"},
    "Bills & Utilities": {"group": "Essentials", "color": "#818CF8"},
    "Health": {"group": "Essentials", "color": "#4ADE80"},
    "Education": {"group": "Essentials", "color": "#A3E635"},
    "Betting & Lottery": {"group": "Lifestyle", "color": "#FB7185"},
    "Shopping": {"group": "Lifestyle", "color": "#C084FC"},
    "Entertainment": {"group": "Lifestyle", "color": "#F472B6"},
    "Cash Withdrawal": {"group": "Cash", "color": "#94A3B8"},
    "Fees & Charges": {"group": "Financial", "color": "#F97316"},
    "Transfers Out": {"group": "Transfers", "color": "#64748B"},
    "Other Spending": {"group": "Other", "color": "#475569"},
}

CATEGORIES: list[str] = list(CATEGORY_META)
GROUP_ORDER = ["Essentials", "Lifestyle", "Financial", "Transfers", "Cash", "Other", "Savings", "Income"]

INCOME_CATEGORIES = {"Salary & Income", "OWealth Interest", "Other Income", "Transfers In"}
TRANSFER_CATEGORIES = {"Transfers In", "Transfers Out"}
DISCRETIONARY_CATEGORIES = {"Betting & Lottery", "Shopping", "Entertainment"}
ESSENTIAL_CATEGORIES = {
    "Food & Groceries",
    "Airtime & Data",
    "Transport",
    "Bills & Utilities",
    "Health",
    "Education",
}
INTERNAL_CATEGORY = "Savings & Investments"
INTEREST_CATEGORY = "OWealth Interest"

SCOPE_LABELS = {"both": "Both", "debit": "Money out", "credit": "Money in"}


def category_color(category: str) -> str:
    return CATEGORY_META.get(category, {}).get("color", "#64748B")


def category_group(category: str) -> str:
    return CATEGORY_META.get(category, {}).get("group", "Other")


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """A single keyword/regex rule.

    ``priority`` is evaluated low → high, so specific merchant rules should
    have a lower number than catch-all transfer rules.
    """

    priority: int
    pattern: str
    category: str
    scope: str = "both"  # both | debit | credit
    note: str = ""
    enabled: bool = True

    def as_dict(self) -> dict:
        return {
            "Priority": self.priority,
            "Pattern": self.pattern,
            "Category": self.category,
            "Applies to": SCOPE_LABELS.get(self.scope, "Both"),
            "Note": self.note,
            "Enabled": self.enabled,
        }


DEFAULT_RULES: tuple[Rule, ...] = (
    Rule(5, r"interest", "OWealth Interest", "credit", "Passive returns credited to savings"),
    Rule(
        10,
        r"owealth|o\s?wealth|save\s?box|safe\s?box|savings?|piggy|target\s*save|"
        r"fixed\s*deposit|mutual\s*fund|invest(?:ment)?|treasury|money\s*market|"
        r"withdrawal\s*(?:to|from)\s*(?:wallet|savings)|savings\s*withdrawal",
        "Savings & Investments",
        "both",
        "Internal movements into savings or investments",
    ),
    Rule(
        15,
        r"salary|payroll|stipend|wages|bonus|dividend|allowance",
        "Salary & Income",
        "credit",
        "Earned income",
    ),
    Rule(
        16,
        r"refund|reversal|chargeback|reimburs|returned\s*payment",
        "Other Income",
        "credit",
        "Money returned to you",
    ),
    Rule(
        20,
        r"sporty\s?bet|sportybet|bet\s?9ja|bet9ja|1x\s?bet|bet\s?king|naira\s?bet|"
        r"betway|merrybet|bangbet|betano|parimatch|melbet|hollywood\s?bets|1win|"
        r"\bstake\b|odds|lottery|lotto|baba\s?ijebu|gambl|casino",
        "Betting & Lottery",
        "debit",
        "Gambling and lottery deposits",
    ),
    Rule(
        30,
        r"airtime|recharge|mtn|\bglo\b|airtel|9mobile|etisalat|vtu|"
        r"data\s*(?:bundle|plan|top)|top\s?up|topup|smile|spectranet|ipnx",
        "Airtime & Data",
        "debit",
        "Calls, SMS and internet bundles",
    ),
    Rule(
        40,
        r"\bvat\b|fee|fees|charge|charges|commission|stamp\s*duty|maintenance|"
        r"sms\s*alert|levy|service\s*charge|penalty|e-?levy|withholding|\btax\b",
        "Fees & Charges",
        "debit",
        "Bank fees, levies and taxes",
    ),
    Rule(
        50,
        r"\batm\b|cash\s*(?:withdraw|out|advance|pickup)|withdrawal|"
        r"pos\s*withdrawal|agent\s*(?:withdrawal|cash)|bank\s*withdrawal",
        "Cash Withdrawal",
        "debit",
        "Physical cash taken out",
    ),
    Rule(
        70,
        r"electric|ikedc|ekedc|aedc|bedc|phcn|nepa|disco|dstv|gotv|startimes|"
        r"showmax|netflix|spotify|youtube|apple\s*music|itunes|google\s*play|"
        r"prime\s*video|internet|broadband|wifi|water\s*(?:board|bill)|lawma|"
        r"\brent\b|mortgage|hosting|domain|\baws\b|azure|digitalocean|vercel|"
        r"openai|chatgpt|canva|adobe|subscription|utility|utilities",
        "Bills & Utilities",
        "debit",
        "Recurring bills and subscriptions",
    ),
    Rule(
        80,
        r"food|restaurant|eatery|chowdeck|glovo|jumia\s*food|uber\s*eats|"
        r"bolt\s*food|kfc|mcdonald|chicken\s*republic|domino|pizza|burger|bakery|"
        r"cafe|coffee|starbucks|shoprite|\bspar\b|supermarket|grocer|"
        r"\bmarket\b|suya|bukka|mama\s*put|tantalizers|sweet\s*sensation|"
        r"cold\s*stone|kilimanjaro|drinks|\bbar\b",
        "Food & Groceries",
        "debit",
        "Food, groceries and eating out",
    ),
    Rule(
        90,
        r"uber|bolt|taxi|keke|tricycle|\bbus\b|\bbrt\b|transport|fare|fuel|"
        r"petrol|diesel|nnpc|total\s*energies|mobil|mtt|train|rail|flight|"
        r"airline|air\s*peace|arik|\bpark\b",
        "Transport",
        "debit",
        "Movement and fuel",
    ),
    Rule(
        100,
        r"jumia|konga|amazon|aliexpress|temu|shein|ebay|marketplace|\bstore\b|"
        r"\bshop\b|mall|fashion|clothing|cloth|shoe|electronics|gadget|phone|"
        r"laptop|\bslot\b|pointek|jiji|novare|ikeja\s*mall|palms\s*mall",
        "Shopping",
        "debit",
        "Retail and online shopping",
    ),
    Rule(
        110,
        r"hospital|clinic|pharmacy|chemist|medical|health|doctor|dental|optical|"
        r"laboratory|\blab\b|drug|\bhmo\b|reddington|reliance",
        "Health",
        "debit",
        "Health and pharmacy",
    ),
    Rule(
        120,
        r"school|tuition|course|udemy|coursera|edx|exam|waec|jamb|neco|"
        r"university|polytechnic|college|academy|book|stationery|training",
        "Education",
        "debit",
        "School fees, courses and books",
    ),
    Rule(
        130,
        r"cinema|filmhouse|silverbird|movie|concert|event|ticket|club|nightclub|"
        r"lounge|game|playstation|xbox|steam|theatre|theater|museum",
        "Entertainment",
        "debit",
        "Fun, events and gaming",
    ),
    Rule(
        140,
        r"transfer|\btrf\b|\bnip\b|neft|rtgs|standing\s*order|direct\s*debit|"
        r"sent\s*to|payment\s*to|debit\s*from|wallet\s*to\s*bank|bank\s*to\s*wallet|"
        r"mobile\s*money",
        "Transfers Out",
        "debit",
        "Outgoing transfers",
    ),
    Rule(
        141,
        r"transfer|\btrf\b|\bnip\b|neft|rtgs|received\s*from|credit\s*from|"
        r"payment\s*from|inward",
        "Transfers In",
        "credit",
        "Incoming transfers",
    ),
    Rule(900, r".", "Other Spending", "debit", "Fallback for money out"),
    Rule(901, r".", "Other Income", "credit", "Fallback for money in"),
)


def default_rules() -> list[Rule]:
    return list(DEFAULT_RULES)


def rules_to_frame(rules: Sequence[Rule]) -> pd.DataFrame:
    return pd.DataFrame([rule.as_dict() for rule in rules])


def rules_from_frame(frame: pd.DataFrame) -> list[Rule]:
    """Rebuild rules from the editable dataframe used in the UI."""
    rules: list[Rule] = []
    if frame is None or frame.empty:
        return rules
    scope_lookup = {label.lower(): scope for scope, label in SCOPE_LABELS.items()}
    for _, row in frame.iterrows():
        pattern = str(row.get("Pattern", "") or "").strip()
        category = str(row.get("Category", "") or "").strip()
        if not pattern or not category:
            continue
        scope = scope_lookup.get(str(row.get("Applies to", "Both")).strip().lower(), "both")
        try:
            priority = int(float(row.get("Priority", 500)))
        except (TypeError, ValueError):
            priority = 500
        enabled_value = row.get("Enabled", True)
        enabled = True if pd.isna(enabled_value) else bool(enabled_value)
        rules.append(
            Rule(
                priority=priority,
                pattern=pattern,
                category=category,
                scope=scope,
                note=str(row.get("Note", "") or ""),
                enabled=enabled,
            )
        )
    return sorted(rules, key=lambda r: r.priority)


def add_keyword_rule(rules: Iterable[Rule], keyword: str, category: str) -> list[Rule]:
    """Append a literal keyword rule that outranks the catch-all rules."""
    existing = list(rules)
    priority = min([r.priority for r in existing] + [800]) - 1
    priority = max(priority, 1)
    rule = Rule(
        priority=priority,
        pattern=re.escape(keyword.strip()),
        category=category,
        scope="both",
        note="Custom keyword rule",
    )
    return sorted([*existing, rule], key=lambda r: r.priority)


# ---------------------------------------------------------------------------
# Categorisation
# ---------------------------------------------------------------------------

_SAFE_CACHE: dict[str, str] = {}


def _safe_pattern(pattern: str, warnings: list[str]) -> str:
    cached = _SAFE_CACHE.get(pattern)
    if cached is not None:
        return cached
    try:
        re.compile(pattern)
        _SAFE_CACHE[pattern] = pattern
        return pattern
    except re.error:
        escaped = re.escape(pattern)
        _SAFE_CACHE[pattern] = escaped
        warnings.append(f"Invalid regex '{pattern}' was treated as plain text.")
        return escaped


def apply_categorization(
    transactions: pd.DataFrame, rules: Sequence[Rule] | None = None
) -> tuple[pd.DataFrame, list[str]]:
    """Tag every transaction with a category, group and merchant label."""
    warnings: list[str] = []
    if transactions is None or transactions.empty:
        return pd.DataFrame(columns=[*getattr(transactions, "columns", []), "category"]), warnings

    out = transactions.copy()
    rules = list(rules) if rules is not None else default_rules()

    description = out["description"].fillna("").astype(str)
    is_credit = out["amount"] > 0
    is_debit = out["amount"] < 0

    category = pd.Series("", index=out.index, dtype=object)
    assigned = pd.Series(False, index=out.index)

    for rule in sorted((r for r in rules if r.enabled), key=lambda r: r.priority):
        if rule.scope == "debit":
            scope_mask = is_debit
        elif rule.scope == "credit":
            scope_mask = is_credit
        else:
            scope_mask = pd.Series(True, index=out.index)
        mask = ~assigned & scope_mask
        if not mask.any():
            continue
        pattern = _safe_pattern(rule.pattern, warnings)
        try:
            hit = mask & description.str.contains(
                pattern, case=False, regex=True, na=False
            )
        except re.error:
            continue
        if hit.any():
            category.loc[hit] = rule.category
            assigned = assigned | hit

    category.loc[~assigned & is_credit] = "Other Income"
    category.loc[~assigned & is_debit] = "Other Spending"
    category.loc[category.eq("")] = "Other Spending"

    # The interest tracker must survive user rule edits, so detect interest
    # credits independently of the rule table.
    interest_mask = description.str.contains(r"(?i)\binterest\b", regex=True, na=False) & is_credit
    if interest_mask.any():
        category.loc[interest_mask] = INTEREST_CATEGORY

    out["category"] = category
    out["category_group"] = category.map(category_group)
    out["is_interest"] = interest_mask
    out["is_internal"] = category.eq(INTERNAL_CATEGORY)
    out["flow"] = "in"
    out.loc[is_debit, "flow"] = "out"
    out["merchant"] = description.map(extract_merchant)

    return out, warnings


# ---------------------------------------------------------------------------
# Merchant cleanup
# ---------------------------------------------------------------------------

_PREFIX = re.compile(
    r"(?i)^\s*(?:transfer(?:red)?\s*(?:to|from)|payment\s*(?:to|from)|"
    r"sent\s*to|received\s*from|withdrawal\s*(?:to|from)|"
    r"pos\s*(?:purchase|transaction)?|"
    r"purchase\s*at|debit(?:\s*alert)?|credit(?:\s*alert)?|mobile|web|app|"
    r"trf|nip|payment|deposit|withdrawal)\s*[:\-]?\s*"
)
_REF_NOISE = re.compile(
    r"(?i)\b(?:ref(?:erence)?|trx|txn|trans(?:action)?|session|auth|stan|rrn|"
    r"narration|acct|account|phone|mobile(?:\s*no)?)\s*[:#\-]?\s*[\w\-/]{3,}"
)
_LONG_NUMBERS = re.compile(r"\b\d{4,}\b")
_BANK_NOISE = re.compile(
    r"(?i)\b(?:opay|palmpay|moniepoint|kuda|gtbank|gtb|access\s*bank|zenith\s*bank|"
    r"uba|first\s*bank|wema|sterling|fidelity|union\s*bank|paystack|flutterwave|"
    r"remita|successful|completed|pending|failed)\b"
)
_ACRONYMS = {
    "mtn",
    "airtel",
    "glo",
    "dstv",
    "gotv",
    "kfc",
    "atm",
    "pos",
    "ikedc",
    "ekedc",
    "aedc",
    "bedc",
    "jamb",
    "waec",
    "neco",
    "aws",
    "hmo",
    "brt",
    "nnpc",
    "uba",
    "gtb",
    "vtu",
    "ipnx",
    "spar",
    "jiji",
    "temu",
    "shein",
    "jumia",
    "konga",
    "netflix",
    "spotify",
}


def extract_merchant(description: str) -> str:
    """Reduce a noisy narration to a readable merchant label."""
    if not description:
        return ""

    text = str(description).strip()
    text = _PREFIX.sub("", text)
    text = _REF_NOISE.sub(" ", text)
    text = _LONG_NUMBERS.sub(" ", text)

    # Prefer the first meaningful segment of a multi-part narration.
    segments = re.split(r"\s*[|/•·]\s*|\s+-\s+", text)
    chosen = ""
    for segment in segments:
        candidate = _BANK_NOISE.sub(" ", segment)
        candidate = re.sub(r"[^A-Za-z0-9&.' ]+", " ", candidate)
        candidate = re.sub(r"\s+", " ", candidate).strip(" .-_,'&")
        if len(candidate) >= 3:
            chosen = candidate
            break
    if not chosen:
        chosen = re.sub(r"[^A-Za-z0-9&.' ]+", " ", text)
        chosen = re.sub(r"\s+", " ", chosen).strip()

    words = chosen.split()[:5]
    chosen = " ".join(words)[:42].strip()

    if chosen.isupper():
        chosen = chosen.title()
    for acronym in _ACRONYMS:
        chosen = re.sub(
            rf"(?i)\b{re.escape(acronym)}\b", acronym.upper(), chosen
        )
    return chosen or str(description)[:42]
