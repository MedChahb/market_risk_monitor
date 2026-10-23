"""Shared pieces of the public app: data loading, the book's sliders, number formats and charts."""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app import analysis

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "gold"
REPO = "https://github.com/MedChahb/market_risk_monitor"
GREY, BLUE, RED = "#a9a8a3", "#2a78d6", "#e34948"
NOTIONAL_RANGE = (-5.0, 5.0)  # millions of euros per position; negative is a short position


@st.cache_data
def load_gold() -> dict[str, pd.DataFrame]:
    names = ["fact_pnl", "dim_position", "dim_method", "fact_var", "fact_backtest", "fact_backtest_summary"]
    tables = {name: pd.read_parquet(GOLD / f"{name}.parquet") for name in names}
    tables["fact_var"]["for_date"] = pd.to_datetime(tables["fact_var"]["for_date"])
    tables["fact_backtest"]["for_date"] = pd.to_datetime(tables["fact_backtest"]["for_date"])
    tables["returns"] = analysis.complete_returns(tables["fact_pnl"])
    return tables


@st.cache_data
def book_risk(notionals: tuple[tuple[str, float], ...]) -> tuple[pd.Series, dict[str, pd.DataFrame]]:
    book = pd.Series(dict(notionals))
    pnl = analysis.book_pnl(load_gold()["returns"], book)
    return pnl, analysis.var_estimates(pnl, analysis.gross_notional(book))


def euros(value: float) -> str:
    return f"{value:,.0f} €"


def pnl_chart(pnl: pd.Series, var: pd.Series, exceptions: pd.Series, var_label: str) -> go.Figure:
    figure = go.Figure()
    figure.add_bar(x=pnl.index, y=pnl, name="Daily P&L", marker_color=GREY, marker_line_width=0)
    figure.add_scatter(
        x=var.index, y=-var, mode="lines", name=f"Minus {var_label}", line={"color": BLUE, "width": 2}
    )
    figure.add_scatter(
        x=exceptions.index, y=exceptions, mode="markers", name="Exception", marker={"color": RED, "size": 8}
    )
    figure.update_layout(
        height=360,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        legend={"orientation": "h", "y": 1.12},
        yaxis_title="EUR",
        hovermode="x unified",
        bargap=0,
    )
    return figure


def links() -> None:
    st.caption(
        f"[Code and methodology]({REPO}) · [Power BI report (PDF)]({REPO}/blob/main/docs/report.pdf) · "
        f"[Release with the report file and a tour]({REPO}/releases/latest). "
        "Fictional book; data from Yahoo Finance, the ECB and FRED."
    )


def keep_book_state(positions: pd.DataFrame) -> None:
    """Start the sliders at the reference book and keep their values when the visitor changes page."""
    for position_id, notional in positions["notional_eur"].items():
        key = f"notional_{position_id}"
        st.session_state[key] = st.session_state.get(key, notional / 1e6)


def reset_book(positions: pd.DataFrame) -> None:
    for position_id, notional in positions["notional_eur"].items():
        st.session_state[f"notional_{position_id}"] = notional / 1e6


def book_controls(positions: pd.DataFrame) -> pd.Series:
    columns = st.columns(3)
    for index, (position_id, row) in enumerate(positions.iterrows()):
        columns[index % 3].slider(
            row["name"], *NOTIONAL_RANGE, step=0.25, format="%.2f M€", key=f"notional_{position_id}"
        )
    st.button("Reset to the reference book", on_click=reset_book, args=(positions,))
    return pd.Series(
        {position_id: st.session_state[f"notional_{position_id}"] * 1e6 for position_id in positions.index}
    )
