import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_lib import data
from app_lib.style import INK2, NEUTRAL, PALETTE, base_layout, footer

st.set_page_config(page_title="Lead-lag study · AI Adoption Tracker", page_icon="📈", layout="wide")
st.title("Lead-lag study")
st.markdown(
    "**Question:** does YoY growth in developer-adoption signals (HN hiring-post share, package downloads) "
    "*precede* YoY growth in reported revenue for SNOW, DDOG, MDB, CFLT, ESTC and NET?\n\n"
    "For each company, signal and lag *k* = 0–4 quarters we correlate the signal's log-YoY growth in quarter "
    "*t − k* with revenue log-YoY growth in quarter *t* (fiscal quarters from SEC filings). **Every lag tried is "
    "shown.** Nothing is selected after the fact."
)

company, pooled, summ = data.leadlag()
panel = data.panel()
if company.empty:
    data.no_data_notice()
    st.stop()

SIG = {"hn": "HN hiring-post share", "npm": "npm downloads", "pypi": "PyPI downloads"}
SPEC = {"yoy": "YoY growth (primary)", "d_yoy": "Change in YoY growth (robustness)"}

# ----------------------------------------------------------- headline --
st.subheader("Headline")
c1, c2, c3 = st.columns(3)
c1.metric("Company-level tests (primary spec)", summ.get("company_tests_run", 0))
c2.metric("…with p < 0.05", summ.get("company_tests_p_lt_05", 0),
          help="p from a t-test using the autocorrelation-adjusted effective sample size")
c3.metric("Expected by chance alone", summ.get("expected_false_positives_at_05", 0))
st.caption(f"Tests surviving Benjamini-Hochberg at q < 0.10: **{summ.get('company_tests_q_lt_10', 0)}**. "
           f"Cells that could not be tested (too few overlapping quarters): {summ.get('untestable_cells', 0)}.")
findings = data.PROC / "findings.md"
if findings.exists():
    with st.container(border=True):
        st.markdown(findings.read_text())

c1, c2 = st.columns(2)
spec = c1.radio("Specification", list(SPEC), format_func=SPEC.get, horizontal=True)
sigs = [s for s in SIG if s in set(company["signal"])]
sig = c2.radio("Signal", sigs, format_func=SIG.get, horizontal=True)

# --------------------------------------------------------------- pooled --
st.subheader("Pooled across companies")
p = pooled[(pooled["signal"] == sig) & (pooled["spec"] == spec)]
if p["r"].notna().any():
    fig = go.Figure()
    for i, fe in enumerate(["company", "company+time"]):
        g = p[(p["fe"] == fe)].dropna(subset=["r"])
        if g.empty:
            continue
        off = -0.1 if i == 0 else 0.1
        fig.add_scatter(
            x=g["lag"] + off, y=g["r"], mode="markers", name={"company": "company fixed effects",
                                                              "company+time": "company + quarter fixed effects"}[fe],
            marker=dict(size=10, color=PALETTE[i], line=dict(color="#fcfcfb", width=2)),
            error_y=dict(type="data", symmetric=False, array=g["ci_hi"] - g["r"], arrayminus=g["r"] - g["ci_lo"],
                         color=PALETTE[i], thickness=2, width=4),
            customdata=np.c_[g["n"], g["p"], g["p_lag_adj"]],
            hovertemplate="lag %{x:.0f}q: r=%{y:.2f}<br>n=%{customdata[0]:.0f}, p=%{customdata[1]:.3f}, "
                          "lag-adjusted p=%{customdata[2]:.3f}<extra></extra>")
    fig.add_hline(y=0, line=dict(color=NEUTRAL, width=1))
    base_layout(fig, f"Correlation of {SIG[sig]} (t−k) with revenue (t), 95% CI", yfmt=".1f", height=380)
    fig.update_xaxes(title="lag k (quarters the signal leads revenue)", tickvals=[0, 1, 2, 3, 4])
    fig.update_yaxes(range=[-1, 1], title="correlation r")
    fig.update_layout(hovermode="closest")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Within-company demeaned and stacked. 'Company + quarter fixed effects' also removes what is common "
               "to all six companies in a calendar quarter (rates, macro, the 2021–23 software cycle), so it asks: "
               "*did the company whose signal grew faster than its peers also grow revenue faster?*")
else:
    st.info(f"Not enough overlapping quarters to test {SIG[sig]} yet. " +
            ("PyPI history only began ~180 days before the first pull, so YoY needs about a year more data."
             if sig == "pypi" else ""))

# ----------------------------------------------------------- heatmap --
st.subheader("By company")
c = company[(company["signal"] == sig) & (company["spec"] == spec)]
if c["r"].notna().any():
    hm = c.pivot(index="ticker", columns="lag", values="r")
    nn = c.pivot(index="ticker", columns="lag", values="n")
    pp = c.pivot(index="ticker", columns="lag", values="p")
    txt = hm.map(lambda v: "" if pd.isna(v) else f"{v:+.2f}") + pp.map(
        lambda v: "" if pd.isna(v) else ("*" if v < 0.05 else ""))
    fig = go.Figure(go.Heatmap(
        z=hm.values, x=[f"lag {k}" for k in hm.columns], y=hm.index, zmin=-1, zmax=1,
        colorscale=[[0, "#e34948"], [0.5, "#f1f0ec"], [1, "#2a78d6"]], text=txt.values, texttemplate="%{text}",
        customdata=np.dstack([nn.values, pp.values]), xgap=2, ygap=2,
        hovertemplate="%{y} %{x}: r=%{z:.2f}<br>n=%{customdata[0]:.0f}, p=%{customdata[1]:.3f}<extra></extra>",
        colorbar=dict(title="r", thickness=10)))
    base_layout(fig, f"r by company and lag: {SIG[sig]}, {SPEC[spec]} (* = p < 0.05, unadjusted)", height=320)
    fig.update_layout(hovermode="closest")
    st.plotly_chart(fig, use_container_width=True)

with st.expander("Full results table (every test run)", expanded=False):
    cols = ["ticker", "signal", "spec", "lag", "n", "n_eff", "r", "ci_lo", "ci_hi", "p", "p_lag_adj", "q_bh",
            "p_perm", "status"]
    st.dataframe(company[cols], hide_index=True, use_container_width=True,
                 column_config={k: st.column_config.NumberColumn(format="%.3f")
                                for k in ["n_eff", "r", "ci_lo", "ci_hi", "p", "p_lag_adj", "q_bh", "p_perm"]})
    st.caption("p: t-test with Bartlett effective n (headline). p_lag_adj: Bonferroni over the lags tried for that "
               "company/signal. q_bh: Benjamini-Hochberg across all company tests of the spec. p_perm: block "
               "permutation (secondary; anti-conservative on persistent series, see Methodology).")
    st.download_button("Download CSV", company.to_csv(index=False), "leadlag_company.csv", "text/csv")

# ------------------------------------------------------- inspect one --
st.subheader("Look at the raw series")
if not panel.empty:
    t = st.selectbox("Company", sorted(panel["ticker"].unique()))
    g = panel[panel["ticker"] == t].sort_values("period_end")
    fig = go.Figure()
    fig.add_scatter(x=g["period_end"], y=g["rev_yoy"], name="revenue", mode="lines+markers",
                    line=dict(width=2, color=INK2), marker=dict(size=8))
    for i, s in enumerate(["hn", "npm", "pypi"]):
        col = f"{s}_yoy"
        if col in g and g[col].notna().any():
            fig.add_scatter(x=g["period_end"], y=g[col], name=SIG[s], mode="lines+markers",
                            line=dict(width=2, color=PALETTE[i]), marker=dict(size=8))
    fig.add_hline(y=0, line=dict(color=NEUTRAL, width=1))
    base_layout(fig, f"{t}: log-YoY growth by fiscal quarter (same scale; log 0.4 ≈ +49%)", yfmt=".1f", height=360)
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Fiscal quarters as reported to the SEC (Q4 derived as full year minus nine-month YTD). "
               "Signals are aggregated over each company's exact fiscal-quarter dates.")

# --------------------------------------------------- can / can't --
st.subheader("What this can and can't tell you")
st.markdown("""
**Can:**
- Whether, over the history available, quarters in which a company's developer signal grew faster were followed
  by quarters in which its reported revenue grew faster, with honest uncertainty bands.
- Whether any apparent relationship survives once you account for (a) autocorrelation, (b) having tried five lags,
  and (c) a common cycle hitting all six companies at once.

**Can't:**
- **Prove causation or predict revenue.** Even a real correlation could reflect a shared driver (rates, the
  2021 boom and 2022–23 cost-cutting) rather than adoption causing revenue.
- **Give much power.** Each company has roughly 15–30 quarterly YoY observations, and YoY series overlap
  heavily, so the *effective* sample is often under 10. Only large, persistent relationships could be detected;
  a null result means "not detectable with this data", not "no relationship".
- **Isolate paid usage.** Proxies capture open-source and free-tier usage too (self-hosted MongoDB, Apache Kafka,
  OpenSearch users of Elastic clients, CI re-downloads). HN posts skew toward US startups.
- **Speak to PyPI yet.** pypistats keeps only ~180 days, so PyPI YoY needs time to accumulate.

This is a research exercise, not investment advice.
""")
footer()
