"""Stress tests: past crises replayed on the visitor's book, with each position's contribution."""

import plotly.graph_objects as go
import streamlit as st

from app import analysis, ui

gold = ui.load_gold()
positions = gold["dim_position"].set_index("position_id")
st.title("Stress tests")
st.write(
    "Past crises replayed on the book: each day of the window applies that day's market moves to "
    "today's notionals. The VaR measures a bad but ordinary day; a stress test shows what a known "
    "crisis would cost."
)
with st.expander("Your book (same as on the Build your book page)"):
    notionals = ui.book_controls(positions)
if analysis.gross_notional(notionals) == 0:
    st.warning("Every position is at zero: set at least one notional.")
    st.stop()
_, estimates = ui.book_risk(tuple(notionals.items()))
var_99 = estimates["fhs_ewma"]["var"].iloc[-1]
st.metric(f"Today's VaR 99% ({analysis.METHODS['fhs_ewma']})", ui.euros(var_99))

table = analysis.stress(gold["returns"], notionals, var_99)
table[["cumulative_pnl", "worst_day_pnl"]] = table[["cumulative_pnl", "worst_day_pnl"]].round()
figure = go.Figure(
    go.Bar(
        x=table["cumulative_pnl"],
        y=table["scenario"],
        orientation="h",
        marker_color=[ui.RED if value < 0 else ui.BLUE for value in table["cumulative_pnl"]],
        hovertemplate="%{y}: %{x:,.0f} €<extra></extra>",
    )
)
figure.update_layout(
    height=300, margin={"l": 10, "r": 10, "t": 10, "b": 10}, xaxis_title="Cumulative P&L, EUR"
)
st.plotly_chart(figure, width="stretch")
st.dataframe(
    table.drop(columns="cumulative_in_vars").rename(
        columns={
            "scenario": "Scenario",
            "window": "Window",
            "sessions": "Sessions",
            "cumulative_pnl": "Cumulative P&L",
            "worst_day_pnl": "Worst day",
            "worst_day": "Date",
            "worst_day_in_vars": "Worst day, in VaRs",
        }
    ),
    hide_index=True,
    width="stretch",
    column_config={
        "Cumulative P&L": st.column_config.NumberColumn(format="%,d €"),
        "Worst day": st.column_config.NumberColumn(format="%,d €"),
        "Date": st.column_config.DateColumn(format="DD MMM YYYY"),
        "Worst day, in VaRs": st.column_config.NumberColumn(format="%.1f"),
    },
)

names = {scenario.name: scenario for scenario in analysis.SCENARIOS}
choice = st.selectbox("Contribution of each position", list(names), index=3)
scenario = names[choice]
st.caption(f"{scenario.description}.")
contributions = analysis.contributions(gold["returns"], notionals, scenario)
labels = positions["name"].reindex(contributions.index)
figure = go.Figure(
    go.Bar(
        x=contributions,
        y=labels,
        orientation="h",
        marker_color=[ui.RED if value < 0 else ui.BLUE for value in contributions],
        hovertemplate="%{y}: %{x:,.0f} €<extra></extra>",
    )
)
figure.update_layout(
    height=280, margin={"l": 10, "r": 10, "t": 10, "b": 10}, xaxis_title="P&L over the window, EUR"
)
st.plotly_chart(figure, width="stretch")
st.caption(
    "The book is held unchanged through each window; the cost of reducing it, which rises in a crisis, "
    "is not included."
)
ui.links()
