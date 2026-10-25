"""Risk today: VaR, ES and exceptions of the reference book, and the backtest of the five methods."""

import pandas as pd
import streamlit as st

from app import ui

gold = ui.load_gold()
var, backtest = gold["fact_var"], gold["fact_backtest"]
methods = gold["dim_method"].set_index("method_id")["name"]
for_date = var["for_date"].max()
latest = var[var["for_date"] == for_date].set_index("method_id")
fhs = backtest[backtest["method_id"] == "fhs"].set_index("for_date")
notional = gold["dim_position"]["notional_eur"].sum()

st.title("Market Risk Monitor")
st.write(
    f"Daily market risk of a fictional {notional / 1e6:.0f} M€ book of equities, gold, a euro bond and "
    "dollars, computed every weekday night by a Python pipeline. The VaR is the loss exceeded on 1% of "
    "days; the Expected Shortfall is the average loss on the worst 2.5% of days."
)
st.caption(f"Last close: {fhs.index.max():%d %b %Y}. Figures below cover the session of {for_date:%d %b %Y}.")
columns = st.columns(3)
columns[0].metric("VaR 99%, 1 day", ui.euros(latest.loc["fhs", "var_99_eur"]), help=methods["fhs"])
columns[1].metric("Expected Shortfall 97.5%", ui.euros(latest.loc["fhs", "es_975_eur"]))
last = fhs.iloc[-1]
columns[2].metric("Exceptions in 250 days", f"{last['exceptions_250d']} ({last['zone']})")

recent = fhs.loc[fhs.index.max() - pd.DateOffset(years=2) :]
exceptions = recent.loc[recent["is_exception"], "pnl_eur"]
st.subheader("Daily P&L against the VaR of the previous close")
st.plotly_chart(ui.pnl_chart(recent["pnl_eur"], recent["var_99_eur"], exceptions, "VaR 99%"), width="stretch")

st.subheader("Five VaR methods, backtested since 2012")
summary = gold["fact_backtest_summary"]
whole = summary[summary["period"].str.contains("-")].set_index("method_id")
table = pd.DataFrame(
    {
        "Method": methods.reindex(whole.index),
        "VaR 99%": latest["var_99_eur"].reindex(whole.index),
        "ES 97.5%": latest["es_975_eur"].reindex(whole.index),
        "Exceptions": whole["n_exceptions"],
        "Expected": whole["expected_exceptions"],
        "Kupiec p": whole["kupiec_p"],
        "Christoffersen p": whole["christoffersen_p"],
        "Worst zone": whole["worst_zone"],
    }
).sort_values("Exceptions")
table[["VaR 99%", "ES 97.5%"]] = table[["VaR 99%", "ES 97.5%"]].round()
st.dataframe(
    table,
    hide_index=True,
    width="stretch",
    column_config={
        "VaR 99%": st.column_config.NumberColumn(format="%,d €"),
        "ES 97.5%": st.column_config.NumberColumn(format="%,d €"),
        "Expected": st.column_config.NumberColumn(format="%.1f"),
        "Kupiec p": st.column_config.NumberColumn(format="%.3f"),
        "Christoffersen p": st.column_config.NumberColumn(format="%.3f"),
    },
)
st.caption(
    "A sound 99% VaR is exceeded on about 1% of days (Kupiec's test) and its exceptions do not come in "
    "clusters (Christoffersen's test); a p-value below 0.05 rejects the method. The Basel traffic light "
    "counts exceptions over 250 days: green up to 4, yellow from 5, red from 10."
)
ui.links()
