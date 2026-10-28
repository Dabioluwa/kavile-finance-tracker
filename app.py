"""Kavile finance tracking — an interactive personal finance dashboard.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import html
import time
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from finance.analytics import Analysis, build_analysis, build_insights
from finance.categorize import (
    CATEGORIES,
    CATEGORY_META,
    SCOPE_LABELS,
    Rule,
    add_keyword_rule,
    apply_categorization,
    default_rules,
    rules_from_frame,
    rules_to_frame,
)
from finance.charts import (
    balance_figure,
    cash_flow_figure,
    category_bar,
    category_donut,
    empty_state_figure,
    heatmap_figure,
    income_bar,
    interest_figure,
    merchant_figure,
    monthly_flow_figure,
    savings_growth_figure,
    savings_monthly_figure,
    score_components_figure,
    score_gauge,
    weekday_figure,
    weekly_figure,
)
from finance.cleaning import StatementData, StatementError, load_statement_files
from finance.demo import build_demo_workbook
from finance.format import compact_money, money, pct
from finance.scoring import HealthReport, compute_health

GREEN = "#2DD4A7"
SKY = "#7DD3FC"
AMBER = "#FBBF24"
CORAL = "#FB7185"
MUTED = "#8FA3BA"
INK = "#E8EEF6"

st.set_page_config(
    page_title="Kavile finance tracking",
    page_icon=str(Path(__file__).parent / "assets" / "favicon.png"),
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Sora:wght@500;600;700&display=swap');

:root {
    --bg: #070B10;
    --panel: #0F1620;
    --line: rgba(148,163,184,0.11);
    --muted: #8FA3BA;
    --ink: #E8EEF6;
    --green: #2DD4A7;
}

html, body, [class*="css"] { font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; }

/* Streamlit ships Source Sans on markdown/captions; keep the dashboard on Inter. */
.stApp [data-testid="stMarkdownContainer"],
.stApp [data-testid="stMarkdownContainer"] p,
.stApp [data-testid="stMarkdownContainer"] li,
.stApp [data-testid="stCaptionContainer"],
.stApp [data-testid="stCaptionContainer"] p {
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
}

.stApp {
    background:
        radial-gradient(1100px 520px at 8% -12%, rgba(45,212,167,0.10), transparent 60%),
        radial-gradient(900px 460px at 96% -4%, rgba(56,189,248,0.07), transparent 55%),
        #070B10;
}
header[data-testid="stHeader"] { background: transparent; }
/* Keep the sidebar toggle, but hide Streamlit's Deploy button, main menu and
   running indicator so the app reads as a product, not a dev preview. */
[data-testid="stAppDeployButton"],
[data-testid="stMainMenu"],
[data-testid="stStatusWidget"] { display: none !important; }
.block-container { padding-top: 1.6rem; padding-bottom: 4rem; max-width: 1440px; }

h1, h2, h3, h4 { font-family: 'Sora', 'Inter', sans-serif; letter-spacing: -0.02em; color: var(--ink); }
.stApp [data-testid="stMarkdownContainer"] h1,
.stApp [data-testid="stMarkdownContainer"] h2,
.stApp [data-testid="stMarkdownContainer"] h3,
.stApp [data-testid="stMarkdownContainer"] h4 {
    font-family: 'Sora', 'Inter', sans-serif;
    letter-spacing: -0.02em;
    color: var(--ink);
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0A1017 0%, #080C11 100%);
    border-right: 1px solid var(--line);
}
[data-testid="stSidebar"] > div:first-child { padding-top: 1.1rem; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: var(--muted); }
.side-brand { display: flex; align-items: center; gap: 10px; margin: 0 0 4px 0; }
.side-logo {
    width: 34px; height: 34px; border-radius: 10px;
    background: linear-gradient(135deg, rgba(45,212,167,0.22), rgba(56,189,248,0.14));
    border: 1px solid rgba(45,212,167,0.30);
    display: flex; align-items: center; justify-content: center;
    color: var(--green); font-size: 17px; font-weight: 700;
}
.side-name { font-family: 'Sora', sans-serif; font-size: 17px; font-weight: 700; color: var(--ink); letter-spacing: -0.02em; }
.side-tag { font-size: 10.5px; letter-spacing: 0.16em; color: var(--green); text-transform: uppercase; margin-top: 1px; }
.side-section { font-size: 10.5px; letter-spacing: 0.14em; text-transform: uppercase; color: #64748B; font-weight: 600; margin: 18px 0 6px; }

/* Hero */
.hero { padding: 34px 0 10px; }
.hero .eyebrow, .eyebrow { font-size: 11px; letter-spacing: 0.19em; text-transform: uppercase; color: var(--green); font-weight: 700; }
.hero h1 { font-size: clamp(34px, 4.2vw, 58px); line-height: 1.04; margin: 0.55rem 0 0.85rem; max-width: 900px; }
.hero h1 span { background: linear-gradient(100deg, #2DD4A7 0%, #7DD3FC 55%, #C084FC 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.hero p { color: var(--muted); font-size: 16px; line-height: 1.7; max-width: 700px; }

/* Top bar when data is loaded */
.topbar { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; padding: 4px 0 14px; flex-wrap: wrap; }
.topbar h1 { font-size: 30px; margin: 0.15rem 0 0.2rem; }
.topbar p { color: var(--muted); font-size: 13px; margin: 0; }
.period-pill {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 8px 13px; border-radius: 999px;
    background: rgba(15,22,32,0.85); border: 1px solid var(--line);
    color: #B8C7D9; font-size: 12px; white-space: nowrap;
}
.period-pill b { color: var(--ink); font-weight: 600; }

/* KPI cards */
.kpi {
    position: relative; height: 100%;
    padding: 15px 17px 14px;
    border: 1px solid var(--line);
    border-radius: 16px;
    background: linear-gradient(160deg, rgba(20,30,42,0.92), rgba(10,16,23,0.94));
    overflow: hidden;
}
.kpi::before {
    content: ""; position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, var(--accent), transparent 78%);
    opacity: 0.75;
}
.kpi-head { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
.kpi-label { font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
.kpi-tag { font-size: 9.5px; letter-spacing: 0.08em; color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent); border: 1px solid color-mix(in srgb, var(--accent) 22%, transparent); padding: 2px 7px; border-radius: 999px; font-weight: 700; white-space: nowrap; }
.kpi-value { font-family: 'Sora', sans-serif; font-size: 24px; font-weight: 600; color: var(--ink); margin: 10px 0 5px; letter-spacing: -0.03em; }
.kpi-foot { font-size: 11.5px; color: var(--muted); line-height: 1.4; }
.kpi-bar { height: 4px; border-radius: 999px; background: rgba(148,163,184,0.12); margin: 9px 0 7px; overflow: hidden; }
.kpi-bar span { display: block; height: 100%; border-radius: 999px; }

/* Panels */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: linear-gradient(168deg, rgba(16,24,34,0.86), rgba(9,14,21,0.92));
    border: 1px solid var(--line) !important;
    border-radius: 18px;
    padding: 5px 7px;
    box-shadow: 0 24px 60px -42px rgba(0,0,0,0.95);
}
.panel-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; padding: 6px 8px 0; flex-wrap: wrap; }
.panel-title { font-family: 'Sora', sans-serif; font-size: 14.5px; font-weight: 600; color: var(--ink); letter-spacing: -0.01em; }
.panel-sub { font-size: 11.5px; color: var(--muted); }

/* Tabs */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 4px; background: rgba(15,22,32,0.72); padding: 5px;
    border-radius: 999px; border: 1px solid var(--line);
    width: fit-content; margin-bottom: 14px;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
    background: transparent; border-radius: 999px; padding: 8px 16px;
    color: var(--muted); font-size: 13px; font-weight: 500; height: auto;
}
[data-testid="stTabs"] [aria-selected="true"] { background: rgba(45,212,167,0.13); color: var(--ink); }
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] { display: none; }
[data-testid="stTabs"] [data-baseweb="tab"]:hover { color: var(--ink); }

/* Buttons */
.stButton > button, [data-testid="stDownloadButton"] > button {
    border-radius: 10px; border: 1px solid rgba(148,163,184,0.22);
    background: rgba(18,27,38,0.92); color: var(--ink);
    font-weight: 600; font-size: 13px; transition: all 0.15s ease;
}
.stButton > button:hover, [data-testid="stDownloadButton"] > button:hover {
    border-color: rgba(45,212,167,0.55); color: var(--green);
    background: rgba(22,34,46,0.95);
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #2DD4A7, #1FB98E);
    border: 1px solid rgba(45,212,167,0.6); color: #05130E;
}
.stButton > button[kind="primary"]:hover { filter: brightness(1.06); color: #05130E; }

/* Uploader */
[data-testid="stFileUploader"] section {
    background: rgba(13,20,29,0.85); border: 1px dashed rgba(45,212,167,0.35);
    border-radius: 14px; padding: 14px;
}
[data-testid="stFileUploader"] section:hover { border-color: rgba(45,212,167,0.65); }
[data-testid="stFileUploader"] small { color: #64748B; }

/* Inputs */
[data-baseweb="select"] > div, .stTextInput input, .stDateInput input, .stNumberInput input {
    background: rgba(13,20,29,0.92) !important;
    border-color: rgba(148,163,184,0.18) !important;
    color: var(--ink) !important;
}
.stTextInput label, .stDateInput label, .stMultiSelect label, .stSelectbox label { color: var(--muted) !important; font-size: 12px; }

/* Dataframes */
[data-testid="stDataFrame"] { border-radius: 14px; overflow: hidden; border: 1px solid var(--line); }
[data-testid="stDataFrame"] [role="columnheader"] { background: #0D141D !important; }

/* Expander */
[data-testid="stExpander"] { border: 1px solid var(--line); border-radius: 14px; background: rgba(13,20,29,0.6); }
[data-testid="stExpander"] summary { color: #B8C7D9; font-size: 12.5px; }

/* Feature cards */
.feature {
    height: 100%; padding: 21px 20px;
    border: 1px solid var(--line); border-radius: 17px;
    background: linear-gradient(165deg, rgba(18,27,38,0.80), rgba(9,14,21,0.85));
}
.feature .icon {
    width: 40px; height: 40px; border-radius: 12px; margin-bottom: 15px;
    background: rgba(45,212,167,0.10); border: 1px solid rgba(45,212,167,0.20);
    display: flex; align-items: center; justify-content: center;
    color: var(--green); font-size: 18px;
}
.feature h4 { font-size: 15px; margin: 0 0 7px; }
.feature p { color: var(--muted); font-size: 12.8px; line-height: 1.62; margin: 0; }

.step { display: flex; gap: 13px; padding: 12px 0; border-bottom: 1px solid rgba(148,163,184,0.08); }
.step:last-child { border-bottom: none; }
.step .num {
    flex: 0 0 28px; height: 28px; border-radius: 9px;
    background: rgba(45,212,167,0.10); color: var(--green);
    font-size: 12px; font-weight: 700; display: flex; align-items: center; justify-content: center;
}
.step b { display: block; color: var(--ink); font-size: 13px; margin-bottom: 2px; }
.step span { color: var(--muted); font-size: 12.3px; line-height: 1.5; }

/* Insights */
.insight {
    height: 100%; padding: 16px 17px;
    border: 1px solid var(--line); border-left: 2px solid var(--tone);
    border-radius: 14px;
    background: linear-gradient(165deg, rgba(18,27,38,0.82), rgba(9,14,21,0.90));
}
.insight .i-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.insight .i-icon { color: var(--tone); font-size: 13px; }
.insight .i-title { color: var(--ink); font-size: 13.5px; font-weight: 600; line-height: 1.35; }
.insight .i-body { color: var(--muted); font-size: 12.4px; line-height: 1.6; }

/* Health banner */
.health-banner {
    padding: 15px 17px; border-radius: 14px;
    border: 1px solid color-mix(in srgb, var(--score-color) 28%, transparent);
    background: linear-gradient(135deg, color-mix(in srgb, var(--score-color) 11%, transparent), rgba(11,17,24,0.6));
    margin-top: 4px;
}
.health-banner .grade { color: var(--score-color); font-family: 'Sora'; font-size: 12px; letter-spacing: 0.1em; font-weight: 700; text-transform: uppercase; }
.health-banner .headline { color: var(--ink); font-family: 'Sora'; font-size: 18px; font-weight: 600; margin: 3px 0 4px; }
.health-banner .summary { color: var(--muted); font-size: 12.4px; line-height: 1.55; }

.mini-kpi { padding: 13px 15px; border: 1px solid var(--line); border-radius: 13px; background: rgba(14,22,31,0.7); }
.mini-kpi .label { font-size: 10px; letter-spacing: 0.11em; text-transform: uppercase; color: var(--muted); }
.mini-kpi .value { font-family: 'Sora'; font-size: 19px; font-weight: 600; color: var(--ink); margin-top: 4px; }
.mini-kpi .sub { font-size: 10.8px; color: var(--muted); margin-top: 3px; }

.callout { padding: 14px 16px; border-radius: 13px; border: 1px solid rgba(251,191,36,0.28); background: rgba(251,191,36,0.07); color: #FDE68A; font-size: 13px; }
.muted { color: var(--muted); font-size: 12px; }
.footer { margin-top: 34px; padding-top: 14px; border-top: 1px solid var(--line); color: #52627A; font-size: 11.5px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
.pill-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
.pill { font-size: 11px; color: #9FB0C4; border: 1px solid var(--line); background: rgba(15,22,32,0.7); padding: 5px 10px; border-radius: 999px; }
.upload-label { font-size: 10.5px; letter-spacing: 0.14em; text-transform: uppercase; color: #64748B; font-weight: 600; margin: 2px 0 7px; }
</style>
"""

LANDING_CSS = """
<style>
/* The landing page carries its own upload slot, so the sidebar would only
   duplicate it. It returns with the filters once a statement is loaded. */
[data-testid="stSidebar"],
[data-testid="stExpandSidebarButton"],
[data-testid="stSidebarResizeHandle"] { display: none !important; }
</style>
"""

LOADING_CSS = """
<style>
.kavile-loader {
    position: fixed; inset: 0; z-index: 999999;
    display: flex; align-items: center; justify-content: center;
    padding: 24px;
    background:
        radial-gradient(560px 340px at 50% 45%, rgba(45,212,167,0.10), transparent 65%),
        #070B10;
    animation: kl-in 0.28s ease-out both;
}
.kavile-loader.kl-leaving { animation: kl-out 0.45s ease-in forwards; pointer-events: none; }
.kl-stack { display: flex; flex-direction: column; align-items: center; text-align: center; }
.kl-spinner {
    position: relative; width: 44px; height: 44px; margin-bottom: 20px;
    border-radius: 50%;
    background: conic-gradient(from 90deg, rgba(45,212,167,0) 0%, #2DD4A7 55%, #7DD3FC 100%);
    -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 3px));
    mask: radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 3px));
    animation: kl-spin 0.9s linear infinite;
}
.kl-spinner::after {
    content: ""; position: absolute; inset: 0; border-radius: 50%;
    background: conic-gradient(from 90deg, rgba(45,212,167,0) 0%, #2DD4A7 55%, #7DD3FC 100%);
    filter: blur(10px); opacity: 0.35;
}
.kl-copy {
    font-family: 'Sora', 'Inter', sans-serif; color: #E8EEF6;
    font-size: 15px; font-weight: 600; letter-spacing: -0.01em;
}
.kl-sub {
    margin-top: 6px; max-width: 340px;
    font-size: 12px; color: #7E8FA6;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
@keyframes kl-spin { to { transform: rotate(360deg); } }
@keyframes kl-in { from { opacity: 0; } to { opacity: 1; } }
@keyframes kl-out { from { opacity: 1; } to { opacity: 0; } }
</style>
"""


def esc(value: object) -> str:
    return html.escape(str(value))


# ---------------------------------------------------------------------------
# Cached loaders
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def _load_files(files: tuple[tuple[str, bytes], ...]) -> StatementData:
    return load_statement_files(list(files))


@st.cache_data(show_spinner=False)
def _demo_file() -> bytes:
    return build_demo_workbook()


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

EDITOR_KEY = "rules_editor"


def _init_state() -> None:
    st.session_state.setdefault("dataset", None)
    st.session_state.setdefault("source_label", "")
    st.session_state.setdefault("parse_error", "")
    st.session_state.setdefault("rules", default_rules())
    st.session_state.setdefault("uploader_nonce", 0)
    st.session_state.setdefault("upload_sig", None)
    st.session_state.setdefault("pending_upload", None)
    st.session_state.setdefault("pending_names", ())
    st.session_state.setdefault("rules_nonce", 0)


def _set_dataset(dataset: StatementData, label: str) -> None:
    st.session_state.dataset = dataset
    st.session_state.source_label = label
    st.session_state.parse_error = ""
    # Streamlit drops deleted widget state from the backend but keeps the last
    # rendered value in the browser. Assign the new defaults instead of popping
    # keys so the sidebar and the data stay in sync.
    st.session_state["filter_reset_all"] = True
    st.session_state["tx_search"] = ""


def _reset_filters() -> None:
    st.session_state["filter_reset_all"] = True
    st.session_state["tx_search"] = ""
    st.rerun()


def _load_demo() -> None:
    try:
        dataset = _load_files((("opay_demo_statement.xlsx", _demo_file()),))
    except Exception as exc:  # pragma: no cover - defensive
        st.session_state.parse_error = f"Could not build the demo statement: {exc}"
        return
    _set_dataset(dataset, "Demo statement")
    st.session_state.upload_sig = None
    st.session_state.uploader_nonce += 1


def _clear_data() -> None:
    st.session_state.dataset = None
    st.session_state.source_label = ""
    st.session_state.parse_error = ""
    st.session_state.upload_sig = None
    st.session_state.uploader_nonce += 1
    st.session_state["filter_reset_all"] = True
    st.session_state["tx_search"] = ""


# ---------------------------------------------------------------------------
# Small UI components
# ---------------------------------------------------------------------------


def kpi_card(
    label: str,
    value: str,
    foot: str,
    accent: str = GREEN,
    tag: str | None = None,
    progress: float | None = None,
) -> str:
    tag_html = f'<span class="kpi-tag">{esc(tag)}</span>' if tag else ""
    if progress is None:
        bar = ""
    else:
        width = max(0.0, min(1.0, progress)) * 100
        bar = (
            f'<div class="kpi-bar"><span style="width:{width:.1f}%;'
            f'background:{accent}"></span></div>'
        )
    return (
        f'<div class="kpi" style="--accent:{accent}">'
        f'<div class="kpi-head"><span class="kpi-label">{esc(label)}</span>{tag_html}</div>'
        f'<div class="kpi-value">{esc(value)}</div>'
        f"{bar}"
        f'<div class="kpi-foot">{foot}</div>'
        f"</div>"
    )


def mini_kpi(label: str, value: str, sub: str) -> str:
    return (
        f'<div class="mini-kpi"><div class="label">{esc(label)}</div>'
        f'<div class="value">{esc(value)}</div>'
        f'<div class="sub">{sub}</div></div>'
    )


def insight_card(insight: dict[str, str]) -> str:
    tone = insight.get("tone", "info")
    color = {"good": GREEN, "warn": CORAL, "info": SKY, "tip": AMBER}.get(tone, SKY)
    return (
        f'<div class="insight" style="--tone:{color}">'
        f'<div class="i-head"><span class="i-icon">{esc(insight.get("icon", "•"))}</span>'
        f'<span class="i-title">{esc(insight.get("title", ""))}</span></div>'
        f'<div class="i-body">{esc(insight.get("body", ""))}</div>'
        f"</div>"
    )


@contextmanager
def panel(title: str, subtitle: str | None = None):
    with st.container(border=True):
        sub = f'<span class="panel-sub">{esc(subtitle)}</span>' if subtitle else ""
        st.markdown(
            f'<div class="panel-head"><span class="panel-title">{esc(title)}</span>{sub}</div>',
            unsafe_allow_html=True,
        )
        yield


def show_chart(fig, key: str) -> None:
    st.plotly_chart(
        fig,
        width="stretch",
        theme=None,
        config={"displayModeBar": False, "responsive": True},
        key=key,
    )


def show_table(frame: pd.DataFrame, height: int | None = None) -> None:
    kwargs: dict = {"width": "stretch", "hide_index": True}
    if height is not None:
        kwargs["height"] = height
    st.dataframe(frame, **kwargs)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


def render_loading(
    slot: DeltaGenerator, names: tuple[str, ...], leaving: bool = False
) -> None:
    """Minimal full-screen interlude while the statement is parsed.

    ``leaving`` swaps in the fade-out state so the overlay can dissolve into
    the dashboard instead of vanishing between reruns.
    """
    files = ", ".join(names) if names else "your statement"
    classes = "kavile-loader kl-leaving" if leaving else "kavile-loader"
    slot.markdown(
        LOADING_CSS
        + f'<div class="{classes}" role="status" aria-live="polite">'
        f'<div class="kl-stack">'
        f'<div class="kl-spinner"></div>'
        f'<div class="kl-copy">Loading your statement</div>'
        f'<div class="kl-sub">{esc(files)}</div>'
        f"</div></div>",
        unsafe_allow_html=True,
    )


def _on_upload(uploaded_key: str) -> None:
    """Hand the dropped files to the next run, which shows the loader first.

    Parsing here would block before Streamlit could paint anything, so the
    callback only snapshots the bytes. ``main`` renders the loading screen,
    parses, then reruns into the dashboard.
    """
    uploaded = st.session_state.get(uploaded_key) or []
    if not uploaded:
        return
    signature = tuple(sorted((f.name, getattr(f, "size", 0)) for f in uploaded))
    if signature == st.session_state.upload_sig:
        return
    # Remember the signature even on failure so a broken file is not re-parsed
    # on every rerun while the user reads the error message.
    st.session_state.upload_sig = signature
    st.session_state.pending_upload = tuple(
        (f.name, f.getvalue()) for f in uploaded
    )
    st.session_state.pending_names = tuple(f.name for f in uploaded)


def render_uploader(key: str) -> None:
    st.file_uploader(
        "Upload bank or wallet statement",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
        key=key,
        help="Any bank or wallet export — Excel or CSV. Multiple files are merged.",
        label_visibility="collapsed",
        on_change=_on_upload,
        args=(key,),
    )


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            """
            <div class="side-brand">
                <div class="side-logo">◈</div>
                <div>
                    <div class="side-name">Kavile</div>
                    <div class="side-tag">Finance tracking</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<div class="side-section">Statement</div>', unsafe_allow_html=True)
        render_uploader(f"uploader_{st.session_state.uploader_nonce}")

        cta1, cta2 = st.columns(2)
        with cta1:
            st.button(
                "Demo data",
                on_click=_load_demo,
                width="stretch",
                key="side_demo",
            )
        with cta2:
            st.button(
                "Clear",
                on_click=_clear_data,
                width="stretch",
                key="side_clear",
            )

        st.markdown('<div class="side-section">Method</div>', unsafe_allow_html=True)
        with st.expander("How the score works"):
            st.markdown(
                """
                <div style="font-size:12px;line-height:1.65;color:#8FA3BA">
                The 0–100 score blends seven signals: savings rate (20%),
                spending control (22%), cash-flow stability (15%),
                saving consistency (13%), emergency buffer (12%),
                betting exposure (10%) and fee efficiency (8%).
                <br><br>
                A healthy target is saving 20% of income and holding
                3–6 months of expenses in savings.
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.caption("Local-first. Your statements never leave this machine.")


def render_filters(categorized: pd.DataFrame) -> None:
    """Date, account and category filters, rendered below the uploader."""
    start = categorized["timestamp"].min().date()
    end = categorized["timestamp"].max().date()
    accounts = sorted(categorized["account"].unique().tolist())
    order = {category: index for index, category in enumerate(CATEGORIES)}
    categories = sorted(
        categorized["category"].unique().tolist(),
        key=lambda category: order.get(category, 999),
    )

    if st.session_state.pop("filter_reset_all", False):
        st.session_state["filter_period"] = (start, end)
        st.session_state["filter_accounts"] = accounts
        st.session_state["filter_categories"] = categories
    if st.session_state.pop("filter_reset_categories", False):
        st.session_state["filter_categories"] = categories

    # Seed the widget state instead of passing value=/default= alongside key=.
    # Streamlit warns when both are supplied, and seeding keeps the browser and
    # backend in sync after a reset.
    st.session_state.setdefault("filter_period", (start, end))
    st.session_state.setdefault("filter_accounts", accounts)
    st.session_state.setdefault("filter_categories", categories)

    st.markdown('<div class="side-section">Filters</div>', unsafe_allow_html=True)
    st.date_input(
        "Period",
        min_value=start,
        max_value=end,
        format="DD/MM/YYYY",
        key="filter_period",
    )
    st.multiselect(
        "Accounts",
        options=accounts,
        key="filter_accounts",
    )
    st.multiselect(
        "Categories",
        options=categories,
        key="filter_categories",
    )
    if st.button("Reset filters", width="stretch", key="side_reset_filters"):
        _reset_filters()
    selected = st.session_state.get("filter_categories")
    if selected is not None and len(selected) == 0:
        st.caption("No category selected — showing all.")


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------


def render_landing() -> None:
    st.markdown(
        """
        <div class="hero">
            <div class="eyebrow">Kavile finance tracker</div>
            <h1>Your bank statement,<br><span>finally making sense.</span></h1>
            <p>
                Drop a messy wallet or bank export. Kavile strips the ₦ signs,
                untangles Wallet and Savings sheets, tags every transaction, and
                turns the whole year into a financial health score you can act on.
            </p>
            <div class="pill-row">
                <span class="pill">Compatible with any bank</span>
                <span class="pill">.xlsx / .xls / .csv</span>
                <span class="pill">Dual-sheet statements</span>
                <span class="pill">Interest tracking</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.write("")
    hero_left, hero_right = st.columns([1.05, 2.55], gap="medium")
    with hero_left:
        st.markdown('<div class="upload-label">Try it with demo data</div>', unsafe_allow_html=True)
        st.button(
            "Explore with demo data",
            type="primary",
            on_click=_load_demo,
            width="stretch",
            key="hero_demo",
        )
    with hero_right:
        st.markdown('<div class="upload-label">Upload a statement</div>', unsafe_allow_html=True)
        render_uploader(f"landing_upload_{st.session_state.uploader_nonce}")

    st.write("")
    st.write("")
    cols = st.columns(3, gap="medium")
    features = [
        (
            "⌁",
            "Cleans the mess",
            "Strips ₦ symbols and commas, reads day-first dates, merges Wallet and "
            "Savings sheets, and ignores failed transactions — automatically.",
        ),
        (
            "◎",
            "Reads between the lines",
            "A regex + keyword engine tags Airtime, Sportybet, OWealth, food, bills, "
            "fees and names. Add your own rules in seconds.",
        ),
        (
            "◈",
            "Scores your money health",
            "Seven weighted signals become one 0–100 score, with OWealth interest, "
            "savings growth and daily cash-flow spikes surfaced.",
        ),
    ]
    for column, (icon, title, body) in zip(cols, features):
        with column:
            st.markdown(
                f'<div class="feature"><div class="icon">{icon}</div>'
                f"<h4>{esc(title)}</h4><p>{esc(body)}</p></div>",
                unsafe_allow_html=True,
            )

    st.write("")
    st.write("")
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        st.markdown("### Three steps to clarity")
        steps = [
            ("01", "Upload", "Drop one or more statements into the upload slot — or try the demo first."),
            ("02", "Review", "Check the auto-tags, adjust a keyword rule, and filter the period you care about."),
            ("03", "Act", "Use the score breakdown, category leaks and savings runway to make one concrete change."),
        ]
        body = "".join(
            f'<div class="step"><div class="num">{n}</div><div><b>{esc(t)}</b><span>{esc(d)}</span></div></div>'
            for n, t, d in steps
        )
        st.markdown(body, unsafe_allow_html=True)
    with right:
        st.markdown("### Built for Nigerian statements")
        st.markdown(
            """
            <div class="feature" style="padding:18px 19px">
                <p style="margin-bottom:12px">
                The parser understands the patterns real wallet exports throw at it:
                </p>
                <div class="pill-row" style="margin-top:0">
                    <span class="pill">₦1,250,000.00</span>
                    <span class="pill">12/03/2025</span>
                    <span class="pill">Debit / Credit columns</span>
                    <span class="pill">Single Amount + Type</span>
                    <span class="pill">OWealth Interest Earned</span>
                    <span class="pill">Failed transactions</span>
                    <span class="pill">Running balance</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Dashboard header
# ---------------------------------------------------------------------------


def render_header(
    dataset: StatementData,
    analysis: Analysis,
    health: HealthReport,
) -> None:
    start = analysis.start
    end = analysis.end
    source = st.session_state.source_label or "Statement"
    st.markdown(
        f"""
        <div class="topbar">
            <div>
                <div class="eyebrow">Financial health overview</div>
                <h1>Your money, in focus.</h1>
                <p>{esc(source)} · {analysis.kpis['transactions']:,} transactions across {len(dataset.files)} file(s)</p>
            </div>
            <div class="period-pill">◷ <b>{start:%d %b %Y}</b> → <b>{end:%d %b %Y}</b>
                <span style="color:{health.color};font-weight:700">· {health.grade} {health.total}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpis(analysis: Analysis, health: HealthReport) -> None:
    k = analysis.kpis
    net = k["net"]
    net_color = GREEN if net >= 0 else CORAL
    retained = net / k["inflow"] if k["inflow"] else 0.0
    # Count only cash rows: internal wallet <-> savings transfers are excluded
    # from inflow/outflow, so counting them here would inflate the transaction
    # counts and understate the average credit.
    cash = analysis.transactions.loc[~analysis.transactions["is_internal"]]
    in_count = int((cash["credit"] > 0).sum())
    out_count = int((cash["debit"] > 0).sum())
    daily_burn = k["outflow"] / max(k["days"], 1)

    cards = [
        kpi_card(
            "Net cash flow",
            money(net),
            f"{pct(retained)} of money in retained",
            accent=net_color,
            tag="surplus" if net >= 0 else "deficit",
        ),
        kpi_card(
            "Money in",
            money(k["inflow"]),
            f"{in_count:,} credits · avg {money(k['inflow'] / max(in_count, 1))}",
            accent=SKY,
        ),
        kpi_card(
            "Money out",
            money(k["outflow"]),
            f"{out_count:,} debits · {money(daily_burn)}/day",
            accent=CORAL,
        ),
        kpi_card(
            "Savings rate",
            pct(k["savings_rate"]),
            f"{money(k['savings_deposits'])} moved to savings",
            accent=AMBER,
            tag="target 20%",
            progress=min(k["savings_rate"] / 0.20, 1.0),
        ),
        kpi_card(
            "Health score",
            f"{health.total} / 100",
            f"Grade {health.grade} · {health.headline}",
            accent=health.color,
            progress=health.total / 100,
        ),
    ]

    columns = st.columns(5, gap="small")
    for column, card in zip(columns, cards):
        with column:
            st.markdown(card, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------


def render_overview(analysis: Analysis, health: HealthReport, insights: list[dict]) -> None:
    left, right = st.columns([1.0, 1.75], gap="medium")
    with left:
        with panel("Financial health", "Weighted, explainable score"):
            show_chart(score_gauge(health, height=230), "gauge")
            st.markdown(
                f"""
                <div class="health-banner" style="--score-color:{health.color}">
                    <div class="grade">Grade {health.grade} · {health.total}/100</div>
                    <div class="headline">{esc(health.headline)}</div>
                    <div class="summary">{esc(health.summary)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    with right:
        with panel("Score breakdown", "Hover a bar for the advice"):
            show_chart(score_components_figure(health, height=350), "score_components")

    with panel("Daily cash-flow pulse", "Bars are money in/out · line is net · diamonds mark spikes"):
        show_chart(cash_flow_figure(analysis.daily, height=330), "overview_cashflow")

    left, right = st.columns([1.0, 1.35], gap="medium")
    with left:
        with panel("Where the money went", f"{money(analysis.kpis['spend_total'])} total spend"):
            if analysis.spend_by_category.empty:
                st.info("No spending recorded in this period.")
            else:
                show_chart(category_donut(analysis.spend_by_category, height=350), "overview_donut")
    with right:
        with panel("What stands out", "Automated observations"):
            if insights:
                for insight in insights[:4]:
                    st.markdown(insight_card(insight), unsafe_allow_html=True)
                    st.write("")
            else:
                st.info("No notable patterns yet.")

    left, right = st.columns([1.55, 1.0], gap="medium")
    with left:
        with panel("Savings trajectory", "Cumulative balance with interest overlay"):
            if analysis.savings_series.empty:
                st.markdown(
                    '<div class="callout">No savings movements found. Tag transfers as '
                    "Savings in Data & Rules, or upload a statement with a savings sheet.</div>",
                    unsafe_allow_html=True,
                )
            else:
                show_chart(savings_growth_figure(analysis.savings_series, height=320), "overview_savings")
    with right:
        with panel("Monthly rhythm", "Income, spend and savings rate"):
            show_chart(monthly_flow_figure(analysis.monthly, height=320), "overview_monthly")


def render_cash_flow(analysis: Analysis) -> None:
    with panel("Daily cash flow", "Every inflow and outflow, with the three biggest spike days"):
        show_chart(cash_flow_figure(analysis.daily, height=380), "cf_daily")

    left, right = st.columns(2, gap="medium")
    with left:
        with panel("Monthly income vs spending", "Bars sized to your real cash flow"):
            show_chart(monthly_flow_figure(analysis.monthly, height=340), "cf_monthly")
    with right:
        with panel("Weekly transaction frequency", "Volume vs money leaving"):
            show_chart(weekly_figure(analysis.weekly, height=340), "cf_weekly")

    left, right = st.columns([1.55, 1.0], gap="medium")
    with left:
        with panel("Account balances over time", "Wallet and savings side by side"):
            show_chart(balance_figure(analysis.transactions, height=340), "cf_balance")
    with right:
        with panel("Peak spending days", "Top outflow days in this period"):
            if analysis.spikes.empty:
                st.info("Not enough data to detect spikes.")
            else:
                spikes = analysis.spikes.copy()
                spikes["Date"] = spikes["date"].dt.strftime("%d %b %Y")
                spikes["Outflow"] = spikes["outflow"].map(money)
                spikes["Share"] = spikes["share"].map(pct)
                spikes["vs average"] = spikes["zscore"].map(lambda v: f"{v:+.1f}σ")
                show_table(spikes[["Date", "Outflow", "Share", "vs average"]], height=300)

    with panel("Net flow by month", "A positive month means you kept more than you spent"):
        monthly = analysis.monthly.copy()
        monthly["Net"] = monthly["net"].map(money)
        monthly["In"] = monthly["inflow"].map(money)
        monthly["Out"] = monthly["outflow"].map(money)
        monthly["Saved"] = monthly["savings_rate"].map(pct)
        show_table(
            monthly[["label", "In", "Out", "Net", "Saved"]].rename(
                columns={"label": "Month", "Saved": "Savings rate"}
            ),
            height=320,
        )


def render_spending(analysis: Analysis) -> None:
    spend = analysis.spend_by_category
    if spend.empty:
        st.info("No spending found for the selected filters.")
        return

    left, right = st.columns([1.0, 1.35], gap="medium")
    with left:
        with panel("Spending mix", f"{len(spend)} categories detected"):
            show_chart(category_donut(spend, height=370), "sp_donut")
    with right:
        with panel("Category ranking", "Share of every Naira that left your wallet"):
            show_chart(category_bar(spend, height=370), "sp_bar")

    left, right = st.columns([1.55, 1.0], gap="medium")
    with left:
        with panel("When you spend", "Day of week × hour of day"):
            if analysis.heatmap is None:
                st.markdown(
                    '<div class="callout">This statement has no time-of-day data, '
                    "so the hourly heatmap is unavailable.</div>",
                    unsafe_allow_html=True,
                )
                show_chart(weekday_figure(analysis.frequency, height=280), "sp_weekday_fallback")
            else:
                show_chart(heatmap_figure(analysis.heatmap, height=350), "sp_heatmap")
    with right:
        with panel("Busiest days", "Transaction count by weekday"):
            show_chart(weekday_figure(analysis.frequency, height=350), "sp_weekday")

    left, right = st.columns([1.2, 1.0], gap="medium")
    with left:
        with panel("Top merchants", "Where repeated spending accumulates"):
            if analysis.top_merchants.empty:
                st.info("No merchant names detected.")
            else:
                show_chart(merchant_figure(analysis.top_merchants, height=380), "sp_merchants")
    with right:
        with panel("Category detail", "Totals, share and average payment"):
            table = spend.copy()
            table["Total"] = table["total"].map(money)
            table["Share"] = table["share"].map(pct)
            table["Transactions"] = table["count"]
            table["Average"] = table["avg"].map(money)
            table["Group"] = table["group"]
            show_table(
                table[["category", "Group", "Total", "Share", "Transactions", "Average"]].rename(
                    columns={"category": "Category"}
                ),
                height=380,
            )

    with panel("Income sources", "Money in, excluding transfers between your own accounts"):
        if analysis.income_by_category.empty:
            st.info("No inflows in this period.")
        else:
            income = analysis.income_by_category.copy()
            income["Total"] = income["total"].map(money)
            income["Share"] = income["share"].map(pct)
            income["Transactions"] = income["count"]
            show_table(
                income[["category", "Total", "Share", "Transactions"]].rename(
                    columns={"category": "Source"}
                ),
                height=260,
            )


def render_savings(analysis: Analysis, health: HealthReport) -> None:
    k = analysis.kpis
    cards = [
        mini_kpi("Interest earned", money(k["interest"]), "OWealth passive returns"),
        mini_kpi("Saved in", money(k["savings_deposits"]), f"{k['savings_months']} active month(s)"),
        mini_kpi("Withdrawn", money(k["savings_withdrawals"]), "Back to the wallet"),
        mini_kpi("Savings balance", money(k["savings_balance"]), f"{k['runway_months']:.1f} months of runway"),
        mini_kpi("Effective yield", pct(k["interest_effective"]), "Annualised on average balance"),
    ]
    columns = st.columns(5, gap="small")
    for column, card in zip(columns, cards):
        with column:
            st.markdown(card, unsafe_allow_html=True)

    left, right = st.columns([1.6, 1.0], gap="medium")
    with left:
        with panel("Savings growth", "Balance over time with cumulative interest overlay"):
            if analysis.savings_series.empty:
                st.info("No savings data for these filters.")
            else:
                show_chart(savings_growth_figure(analysis.savings_series, height=380), "sv_growth")
    with right:
        with panel("Deposits, withdrawals and interest", "Monthly savings activity"):
            if analysis.savings_monthly.empty:
                st.info("No savings activity.")
            else:
                show_chart(savings_monthly_figure(analysis.savings_monthly, height=380), "sv_monthly")

    left, right = st.columns([1.35, 1.0], gap="medium")
    with left:
        with panel("OWealth interest tracker", "Monthly credits and cumulative returns"):
            if analysis.interest.empty:
                st.markdown(
                    '<div class="callout">No rows matched “interest”. OWealth interest '
                    "rows are detected from credit narrations automatically.</div>",
                    unsafe_allow_html=True,
                )
                show_chart(
                    empty_state_figure("No interest credits found in this period.", height=300),
                    "sv_interest_empty",
                )
            else:
                show_chart(interest_figure(analysis.interest_monthly, height=320), "sv_interest")
    with right:
        with panel("Interest ledger", "Every passive-return row"):
            if analysis.interest.empty:
                st.info("Nothing to list.")
            else:
                table = analysis.interest.copy()
                table["Date"] = table["timestamp"].dt.strftime("%d %b %Y")
                table["Amount"] = table["credit"].map(money)
                table["Description"] = table["description"].str.slice(0, 46)
                show_table(
                    table[["Date", "Description", "Amount"]].sort_values(
                        "Date", ascending=False
                    ),
                    height=320,
                )

    with panel("How this is calculated", None):
        st.markdown(
            f"""
            <div style="font-size:12.5px;color:#8FA3BA;line-height:1.7;padding:2px 8px 8px">
            <b style="color:#E8EEF6">Savings balance</b> is the last running balance on the
            savings/wealth sheet, or the cumulative net of savings transfers when no balance
            column exists. <b style="color:#E8EEF6">Deposits</b> exclude interest credits to
            avoid double counting. <b style="color:#E8EEF6">Effective yield</b> annualises
            {money(k['interest'])} of interest against an average balance of
            {money(k['avg_savings_balance'])} over {k['days']} days. Internal wallet ↔ savings
            movements are excluded from income and spending, so they never inflate your cash flow.
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_insights(analysis: Analysis, health: HealthReport, insights: list[dict]) -> None:
    st.markdown("### Observations")
    if not insights:
        st.info("Not enough activity yet to generate insights.")
    for index in range(0, len(insights), 2):
        columns = st.columns(2, gap="medium")
        for column, insight in zip(columns, insights[index : index + 2]):
            with column:
                st.markdown(insight_card(insight), unsafe_allow_html=True)

    st.write("")
    left, right = st.columns(2, gap="medium")
    with left:
        with panel("Recurring merchants", "Seen in 3+ different months"):
            if analysis.recurring.empty:
                st.info("No recurring patterns detected yet.")
            else:
                recurring = analysis.recurring.copy()
                recurring["Months"] = recurring["months"]
                recurring["Payments"] = recurring["count"]
                recurring["Average"] = recurring["avg"].map(money)
                recurring["Last seen"] = recurring["last_seen"].dt.strftime("%d %b")
                show_table(
                    recurring[["merchant", "category", "Months", "Payments", "Average", "Last seen"]].rename(
                        columns={"merchant": "Merchant", "category": "Category"}
                    ),
                    height=360,
                )
    with right:
        with panel("Largest transactions", "The eight biggest outflows"):
            if analysis.largest.empty:
                st.info("No outflows to show.")
            else:
                largest = analysis.largest.copy()
                largest["Date"] = largest["timestamp"].dt.strftime("%d %b %Y")
                largest["Amount"] = largest["amount"].map(money)
                largest["Description"] = largest["description"].str.slice(0, 52)
                show_table(
                    largest[["Date", "merchant", "category", "Amount", "Description"]].rename(
                        columns={
                            "merchant": "Merchant",
                            "category": "Category",
                        }
                    ),
                    height=360,
                )

    with panel("What to work on next", "The lowest-scoring signals, in order"):
        weak = sorted(health.components, key=lambda component: component.score)[:3]
        rows = [
            {
                "Signal": component.label,
                "Score": f"{component.score:.0f} / 100",
                "What we see": component.display,
                "Move": component.advice,
            }
            for component in weak
        ]
        show_table(pd.DataFrame(rows), height=180)


def render_data(
    dataset: StatementData,
    analysis: Analysis,
    health: HealthReport,
    warnings: list[str],
) -> None:
    st.markdown("### Parsing report")
    summary = dataset.sheet_summary.copy()
    if not summary.empty:
        summary["first"] = pd.to_datetime(summary["first"]).dt.strftime("%d %b %Y")
        summary["last"] = pd.to_datetime(summary["last"]).dt.strftime("%d %b %Y")
        summary["money_in"] = summary["money_in"].map(money)
        summary["money_out"] = summary["money_out"].map(money)
        show_table(
            summary.rename(
                columns={
                    "file": "File",
                    "sheet": "Sheet",
                    "account": "Account",
                    "transactions": "Rows",
                    "first": "First",
                    "last": "Last",
                    "money_in": "Money in",
                    "money_out": "Money out",
                }
            ),
        )

    all_warnings = [*dataset.warnings, *warnings]
    if all_warnings:
        with st.expander(f"Data quality notes ({len(all_warnings)})"):
            for warning in all_warnings[:40]:
                st.markdown(f"- {warning}")
    else:
        st.caption("No parsing issues. Everything mapped cleanly.")

    st.write("")
    st.markdown("### Categorisation rules")
    st.caption(
        "Rules run in ascending priority. The first match wins, so keep specific merchant "
        "rules below 100 and catch-all transfer rules above them."
    )

    rules = st.session_state.rules
    editor_key = f"{EDITOR_KEY}_{st.session_state.rules_nonce}"
    edited = st.data_editor(
        rules_to_frame(rules),
        width="stretch",
        height=420,
        hide_index=True,
        num_rows="dynamic",
        key=editor_key,
        column_config={
            "Priority": st.column_config.NumberColumn(
                "Priority", min_value=1, max_value=9999, step=1, width="small"
            ),
            "Pattern": st.column_config.TextColumn(
                "Pattern (regex)", width="large", required=True
            ),
            "Category": st.column_config.SelectboxColumn(
                "Category", options=CATEGORIES, required=True, width="medium"
            ),
            "Applies to": st.column_config.SelectboxColumn(
                "Applies to", options=list(SCOPE_LABELS.values()), width="small"
            ),
            "Note": st.column_config.TextColumn("Note", width="medium"),
            "Enabled": st.column_config.CheckboxColumn("Enabled", width="small"),
        },
    )

    action1, action2, action3 = st.columns([1, 1, 2])
    with action1:
        if st.button("Apply rule changes", type="primary", width="stretch", key="apply_rules"):
            new_rules = rules_from_frame(edited)
            if not new_rules:
                st.error("Keep at least one enabled rule.")
            else:
                st.session_state.rules = new_rules
                st.session_state.rules_nonce += 1
                st.session_state["filter_reset_categories"] = True
                st.rerun()
    with action2:
        if st.button("Reset defaults", width="stretch", key="reset_rules"):
            st.session_state.rules = default_rules()
            st.session_state.rules_nonce += 1
            st.session_state["filter_reset_categories"] = True
            st.rerun()
    with action3:
        st.caption(
            f"{sum(1 for r in rules if r.enabled)} enabled of {len(rules)} rules · "
            f"{health.total}/100 health score on the filtered view."
        )

    st.write("")
    left, right = st.columns([1.15, 1.0], gap="medium")
    with left:
        with panel("Tag a merchant in one click", "Creates a high-priority keyword rule"):
            uncategorised = analysis.transactions.loc[
                analysis.transactions["category"].isin(["Other Spending", "Other Income"])
                & analysis.transactions["merchant"].ne("")
            ]
            candidates = uncategorised["merchant"].value_counts().head(50).index.tolist()
            if not candidates:
                st.caption("No untagged merchants — nice work. You can still add a rule below.")
                candidates = sorted(
                    analysis.transactions["merchant"].dropna().unique().tolist()
                )[:50]
            if candidates:
                c1, c2 = st.columns([1.4, 1.0])
                with c1:
                    keyword = st.selectbox(
                        "Merchant or keyword",
                        options=candidates,
                        key="quick_keyword",
                        label_visibility="collapsed",
                    )
                with c2:
                    category = st.selectbox(
                        "Category",
                        options=CATEGORIES,
                        index=CATEGORIES.index("Other Spending") if "Other Spending" in CATEGORIES else 0,
                        key="quick_category",
                        label_visibility="collapsed",
                    )
                if st.button("Create keyword rule", key="create_quick_rule"):
                    st.session_state.rules = add_keyword_rule(
                        st.session_state.rules, keyword, category
                    )
                    st.session_state.rules_nonce += 1
                    st.session_state["filter_reset_categories"] = True
                    st.rerun()
    with right:
        with panel("Export", "Clean data, ready for a spreadsheet"):
            export = analysis.transactions.copy()
            export["Date"] = export["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
            export["Amount"] = export["amount"].round(2)
            export["Debit"] = export["debit"].round(2)
            export["Credit"] = export["credit"].round(2)
            export["Balance"] = export["balance"].round(2)
            export = export[
                [
                    "Date",
                    "account",
                    "description",
                    "merchant",
                    "category",
                    "Amount",
                    "Debit",
                    "Credit",
                    "Balance",
                ]
            ].rename(
                columns={
                    "account": "Account",
                    "description": "Description",
                    "merchant": "Merchant",
                    "category": "Category",
                }
            )
            st.caption(
                f"{len(export):,} rows in the current filtered view. Amount is signed "
                "(negative = money out)."
            )
            st.download_button(
                "Download cleaned CSV",
                data=export.to_csv(index=False).encode("utf-8-sig"),
                file_name="kavile_transactions.csv",
                mime="text/csv",
                width="stretch",
                key="download_clean",
            )

    st.write("")
    st.markdown("### Transaction explorer")
    query = st.text_input(
        "Search description, merchant or category",
        placeholder="e.g. sportybet, airtime, Chinedu…",
        key="tx_search",
    )
    view = analysis.transactions.copy()
    if query.strip():
        needle = query.strip()
        mask = (
            view["description"].str.contains(needle, case=False, na=False, regex=False)
            | view["merchant"].str.contains(needle, case=False, na=False, regex=False)
            | view["category"].str.contains(needle, case=False, na=False, regex=False)
        )
        view = view.loc[mask]

    view["Date"] = view["timestamp"].dt.strftime("%d %b %Y %H:%M")
    view["Amount"] = view.apply(
        lambda row: ("−" if row["amount"] < 0 else "+") + money(abs(row["amount"])), axis=1
    )
    view = view[
        ["Date", "account", "merchant", "description", "category", "Amount", "balance"]
    ].rename(
        columns={
            "account": "Account",
            "merchant": "Merchant",
            "description": "Description",
            "category": "Category",
            "balance": "Balance",
        }
    )
    view["Balance"] = view["Balance"].map(
        lambda value: money(value) if pd.notna(value) else "—"
    )
    show_table(view, height=430)
    st.caption(f"Showing {len(view):,} of {len(analysis.transactions):,} filtered transactions.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)

    _init_state()

    pending = st.session_state.pop("pending_upload", None)
    if pending:
        names = tuple(st.session_state.pop("pending_names", ()))
        slot = st.empty()
        render_loading(slot, names)
        # Give the overlay a beat to paint before parsing blocks the run.
        time.sleep(0.55)
        try:
            dataset = _load_files(tuple(pending))
            _set_dataset(dataset, "Uploaded · " + ", ".join(names))
        except StatementError as exc:
            st.session_state.parse_error = str(exc)
        except Exception as exc:  # pragma: no cover - defensive
            st.session_state.parse_error = (
                f"Unexpected problem while reading the file: {exc}"
            )
        # Data is ready: dissolve the overlay before rerunning into the app.
        render_loading(slot, names, leaving=True)
        time.sleep(0.5)
        st.rerun()

    dataset: StatementData | None = st.session_state.dataset

    if dataset is None:
        st.markdown(LANDING_CSS, unsafe_allow_html=True)

    if st.session_state.parse_error:
        st.error(st.session_state.parse_error)

    if dataset is None:
        render_landing()
        if st.session_state.dataset is None:
            st.markdown(
                '<div class="footer"><span>Kavile finance tracking · built with Streamlit, Pandas & Plotly</span>'
                "<span>Statements are processed locally in this session.</span></div>",
                unsafe_allow_html=True,
            )
            return
        dataset = st.session_state.dataset

    render_sidebar()

    categorized, cat_warnings = apply_categorization(
        dataset.transactions, st.session_state.rules
    )

    with st.sidebar:
        render_filters(categorized)

    tx = categorized
    start_default = tx["timestamp"].min().date()
    end_default = tx["timestamp"].max().date()
    period = st.session_state.get("filter_period", (start_default, end_default))
    if isinstance(period, (tuple, list)):
        if len(period) == 2:
            start_date, end_date = period
        elif len(period) == 1:
            start_date = end_date = period[0]
        else:
            start_date, end_date = start_default, end_default
    else:
        start_date, end_date = start_default, end_default

    available_accounts = sorted(tx["account"].unique().tolist())
    selected_accounts = st.session_state.get("filter_accounts") or available_accounts
    selected_accounts = [a for a in selected_accounts if a in available_accounts]

    available_categories = tx["category"].unique().tolist()
    selected_categories = st.session_state.get("filter_categories") or available_categories
    selected_categories = [c for c in selected_categories if c in available_categories]

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1)
    mask = (
        tx["timestamp"].ge(start_ts)
        & tx["timestamp"].lt(end_ts)
        & tx["account"].isin(selected_accounts)
        & tx["category"].isin(selected_categories)
    )
    filtered = tx.loc[mask].copy()

    if filtered.empty:
        st.markdown("### No transactions in this view")
        st.markdown(
            '<div class="callout">Your filters removed every transaction. Widen the period, '
            "re-select an account or category, or reset the view.</div>",
            unsafe_allow_html=True,
        )
        st.button("Reset filters", on_click=_reset_filters, key="empty_reset")
        return

    try:
        analysis = build_analysis(filtered)
        health = compute_health(analysis.kpis)
        insights = build_insights(analysis.kpis, health, analysis)
    except Exception as exc:  # pragma: no cover - defensive
        st.error(f"Could not analyse this selection: {exc}")
        st.exception(exc)
        return

    render_header(dataset, analysis, health)
    render_kpis(analysis, health)

    tab_overview, tab_cash, tab_spend, tab_savings, tab_insights, tab_data = st.tabs(
        [
            "Overview",
            "Cash flow",
            "Spending",
            "Savings & OWealth",
            "Insights",
            "Data & rules",
        ]
    )

    with tab_overview:
        render_overview(analysis, health, insights)
    with tab_cash:
        render_cash_flow(analysis)
    with tab_spend:
        render_spending(analysis)
    with tab_savings:
        render_savings(analysis, health)
    with tab_insights:
        render_insights(analysis, health, insights)
    with tab_data:
        render_data(dataset, analysis, health, cat_warnings)

    st.markdown(
        f'<div class="footer"><span>Kavile finance tracking · {analysis.kpis["transactions"]:,} transactions '
        f'analysed · score {health.total}/100 (grade {health.grade})</span>'
        "<span>Not financial advice. Verify important figures against your bank.</span></div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
