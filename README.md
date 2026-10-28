# Kavile finance tracking

An interactive personal-finance dashboard for Nigerian bank and wallet statements.
Drop in a messy OPay / PalmPay / Kuda / bank export and Kavile cleans it, tags every
transaction, scores your financial health, and turns a year of activity into charts you
can actually act on.

Built with **Streamlit + Pandas + Plotly**. Everything runs locally in the Streamlit
process — statements are never uploaded to a third party.

---

## Highlights

- **Messy-statement parser** — strips `₦`, commas and stray spaces; reads day-first
  dates and times; handles title rows, merged Wallet/Savings sheets, debit/credit
  columns, a single Amount + Type column, or signed amounts.
- **Dual-sheet awareness** — Wallet spending and Savings movement are kept separate, and
  internal wallet ↔ savings transfers are excluded from income/spend so nothing is
  double counted.
- **OWealth interest tracker** — interest credits are isolated, totalled, annualised
  against the average savings balance, and charted as cumulative passive returns.
- **Rule-based categorisation** — 18 categories and 19 priority-ordered regex rules.
  Rules are editable in the UI, and interest detection still works even if you rewrite
  the rules.
- **Explainable health score** — one 0–100 score blended from seven weighted signals,
  with a grade, the weakest signals, and one concrete next step.
- **Interactive Plotly views** — daily cash-flow spikes, monthly rhythm, savings growth,
  spending mix, merchant rankings, weekday/hour heatmap, and more.
- **Demo mode** — a deterministic, realistic OPay-style workbook ships with the app, so
  the dashboard is usable before you upload anything.
- **Clean export** — download the tagged, filtered transactions as UTF-8 CSV.

## Quick start

```powershell
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

```bash
# macOS / Linux
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Streamlit opens <http://localhost:8501>. Click **Explore with demo data** to see the
dashboard immediately, or drop a statement into the upload slot on the landing page.

> Tested with Python 3.11, Streamlit 1.66, Pandas 3.0, Plotly 7.1.
> `requirements.txt` allows Streamlit `>=1.40,<2.0`.

## Using the app

1. **Upload** one or more `.xlsx`, `.xls` or `.csv` files (up to 50 MB each). Multiple
   files are merged and de-duplicated.
2. **Review** the auto-tags in the sidebar filters, then open **Data & rules** to adjust
   a regex, add a keyword rule in one click, or reset to defaults.
3. **Explore** the six tabs — Overview, Cash flow, Spending, Savings & OWealth, Insights,
   and Data & rules.
4. **Export** the filtered view from **Data & rules → Export**.

No statement handy? **Explore with demo data** loads a real workbook through the full
parsing and scoring pipeline, so you can try every view before uploading your own.

## Supported statement formats

The parser is heuristic and tries several layouts per sheet:

| Area | What is handled |
| --- | --- |
| File types | `.xlsx`, `.xls` (via `openpyxl` / `xlrd`), `.csv` (comma, semicolon, tab) |
| Sheets | One or many; sheets named Wallet / Savings / OWealth are detected and labelled |
| Header rows | Titles, logos and blank rows before the real header are skipped |
| Amounts | `₦1,250,000.00`, `NGN 1,250,000`, `(1,250.00)`, `1,250.00 DR` |
| Dates | `12/03/2025`, `2025-03-12`, `12 Mar 2025 14:22`, Excel serial dates |
| Direction | Separate Debit/Credit columns, `Amount + Type`, signed amounts, running balance |
| Noise | Failed / reversed rows, opening/closing balance and total rows are dropped |
| Accounts | Wallet and Savings rows are labelled; overlapping files are deduplicated |

If a file cannot be read at all, the app shows a parse error instead of crashing.

## How the health score works

| Signal | Weight | What it looks at |
| --- | ---: | --- |
| Spending control | 22% | Share of income spent, and discretionary leakage |
| Savings rate | 20% | Deposits into savings ÷ core income (target 20%) |
| Cash-flow stability | 15% | How many months ended in the green |
| Saving consistency | 13% | How many months you actually moved money to savings |
| Emergency buffer | 12% | Savings balance ÷ average monthly expenses |
| Betting exposure | 10% | Betting outflow as a share of income |
| Fee efficiency | 8% | Bank fees and charges as a share of spending |

The weighted total maps to a grade (A–E), a headline, and advice for the lowest-scoring
signals. It is a coaching heuristic, not a credit score or financial advice.

## Project structure

```
app.py                  Streamlit UI: landing page, sidebar, tabs, CSS, session state
finance/
  cleaning.py           Workbook/CSV parsing, header detection, amount/date parsing
  categorize.py         Category taxonomy, default regex rules, rule editing helpers
  analytics.py          KPIs, daily/weekly/monthly series, savings, interest, merchants
  scoring.py            Seven-component health score, grade and advice
  charts.py             Plotly figures used across the tabs
  demo.py               Deterministic OPay-style demo workbook and CSV
  format.py             Naira, percentage and compact-number formatting
tests/
  test_core.py          Cleaning, categorisation, analytics, scoring, charts, CSV import
.streamlit/config.toml  Dark theme, upload limit, telemetry off
```

### Data flow

```
uploaded files ──► cleaning.load_statement_files ──► tidy transactions
                                                        │
                                          categorize.apply_categorization
                                                        │
                                     filter (period / accounts / categories)
                                                        │
                                   analytics.build_analysis ──► tables + KPIs
                                                        │
                              scoring.compute_health + build_insights
                                                        │
                                              app.py renders tabs
```

## Customising

- **Categories and rules** live in `finance/categorize.py` (`CATEGORIES`,
  `CATEGORY_META`, `default_rules()`). Rules are `(priority, regex, category, scope)`
  and are applied in ascending priority, first match wins.
- **Weights and thresholds** live in `finance/scoring.py`. Each component returns a
  0–100 score plus a display string and advice.
- **Charts** live in `finance/charts.py`; each figure is a plain Plotly `Figure`, so it
  can be reused or embedded elsewhere.
- **Demo data** lives in `finance/demo.py`; the generator is seeded, so numbers are
  reproducible.

## Tests

```powershell
pip install -r requirements-dev.txt
python -m pytest tests -q
```

The suite covers amount/date parsing, dual-sheet loading, failed-row filtering,
rule round-tripping, CSV import, KPI maths, score bounds, and chart construction.

## Limitations

- Layout detection is heuristic: unusual column names may need a small tweak in the
  alias sets near the bottom of `finance/cleaning.py` (`_DATE_HEADERS`, `_AMOUNT_HEADERS`, …).
- Savings balance is taken from the savings sheet's running balance; without one it
  falls back to cumulative net savings transfers.
- Interest detection depends on narration text containing `interest` (see
  `apply_categorization` in `finance/categorize.py`). If your bank words it differently,
  extend that pattern or add a rule.
- The app is single-user and session-scoped; there is no database or login.

---

Kavile is a local analysis tool, not a financial adviser. Verify important figures
against your bank statement.
