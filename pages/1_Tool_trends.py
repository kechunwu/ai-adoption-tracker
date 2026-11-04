import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_lib import data
from app_lib.style import PALETTE, REGISTRY_COLOR, base_layout, footer
from tracker.config import entities

st.set_page_config(page_title="Tool trends · AI Adoption Tracker", page_icon="📈", layout="wide")
st.title("Tool trends")

ents = entities()
ew = data.entity_weekly()
wk = data.weekly()
hn = data.hn()
if ew.empty and hn.empty:
    data.no_data_notice()
    st.stop()

groups = {"AI tools": "ai_tool", "Public data-infra companies": "public", "Private references": "private"}
c1, c2, c3 = st.columns([1, 1.4, 1])
grp = c1.radio("Group", list(groups), horizontal=False)
opts = [e for e in ents if e.kind == groups[grp]]
ent = c2.selectbox("Tool / company", opts, format_func=lambda e: f"{e.name} ({e.ticker})" if e.ticker else e.name)
years = c3.select_slider("History", ["1y", "2y", "3y", "5y", "All"], value="3y")
start = None if years == "All" else pd.Timestamp.today() - pd.DateOffset(years=int(years[0]))

st.caption("Proxies: " + " · ".join(
    [f"npm `{p}`" for p in ent.npm] + [f"PyPI `{p}`" for p in ent.pypi]) +
    ("  ·  see `config/tracked.yaml` for why each proxy was chosen."))

sub = ew[ew["entity"] == ent.id] if not ew.empty else ew
if start is not None and not sub.empty:
    sub = sub[sub["week"] >= start]

left, right = st.columns(2)
with left:
    fig = go.Figure()
    for reg, g in sub.groupby("registry"):
        fig.add_scatter(x=g["week"], y=g["downloads"], name=f"{reg} weekly", mode="lines",
                        line=dict(width=1, color=REGISTRY_COLOR[reg]), opacity=0.3, showlegend=False,
                        hovertemplate="%{y:,.0f}")
        fig.add_scatter(x=g["week"], y=g["ma4"], name=f"{reg} (4-wk avg)", mode="lines",
                        line=dict(width=2, color=REGISTRY_COLOR[reg]), hovertemplate="%{y:,.0f}")
    base_layout(fig, "Weekly downloads (thin = raw week, bold = 4-week average)", yfmt="~s")
    if sub.empty:
        st.info("No package-download proxy for this entity.")
    else:
        st.plotly_chart(fig, use_container_width=True)
        if "pypi" in set(sub["registry"]):
            st.caption("PyPI history starts where pypistats' ~180-day window began and grows weekly from there.")

with right:
    fig = go.Figure()
    for reg, g in sub.groupby("registry"):
        g = g.dropna(subset=["yoy"])
        if g.empty:
            continue
        fig.add_scatter(x=g["week"], y=g["yoy"], name=reg, mode="lines",
                        line=dict(width=2, color=REGISTRY_COLOR[reg]), hovertemplate="%{y:+.0%}")
    fig.add_hline(y=0, line=dict(color="#8a8984", width=1))
    base_layout(fig, "YoY growth of 4-week average downloads", yfmt="+.0%")
    if fig.data:
        st.plotly_chart(fig, use_container_width=True)
    elif not sub.empty:
        st.info("YoY needs 56+ weeks of history for this registry; it will appear as data accumulates.")

h = hn[hn["entity"] == ent.id] if not hn.empty else hn
if not h.empty:
    if start is not None:
        h = h[h["month_dt"] >= start - pd.DateOffset(months=0)]
    fig = go.Figure()
    fig.add_bar(x=h["month_dt"], y=h["share_ex_employer"], name="monthly", marker_color="#cde2fb",
                hovertemplate="%{y:.2%}")
    fig.add_scatter(x=h["month_dt"], y=h["share_3m"], name="3-month avg", mode="lines",
                    line=dict(width=2, color=PALETTE[0]), hovertemplate="%{y:.2%}")
    base_layout(fig, "Share of 'Ask HN: Who is hiring?' posts mentioning it (excluding the company's own posts)",
                yfmt=".1%")
    st.plotly_chart(fig, use_container_width=True)
    last = h.iloc[-1]
    st.caption(f"{last['month']}: {int(last['mentions_ex_employer'])} of {int(last['total_posts'])} job posts "
               f"({last['share_ex_employer']:.2%}); posts *by* {ent.name} itself: {int(last['employer_posts'])}.")
    with st.expander("Audit: sample matched posts (snippets)"):
        m = data.hn_matches()
        if not m.empty:
            mm = m[m["entity"] == ent.id].sort_values("month", ascending=False).head(25)
            st.dataframe(mm[["month", "post_id", "is_employer", "snippet"]], hide_index=True, use_container_width=True)
            st.caption("Each row links to news.ycombinator.com/item?id=<post_id>. Rules: config/tracked.yaml + tracker/hn_match.py.")
else:
    st.caption("No HN alias for this tool (name too ambiguous to match reliably in free text).")

gh = data.github()
if not gh.empty and ent.github:
    g = gh[gh["repo"].isin(ent.github)].sort_values("snapshot_date")
    if not g.empty:
        st.subheader("GitHub (weekly snapshots)")
        latest = g.groupby("repo").tail(1)
        st.dataframe(latest[["repo", "stars", "forks", "contributors", "releases", "latest_release", "snapshot_date"]],
                     hide_index=True, use_container_width=True)
        if g["snapshot_date"].nunique() >= 3:
            fig = go.Figure()
            for i, (repo, r) in enumerate(g.groupby("repo")):
                fig.add_scatter(x=r["snapshot_date"], y=r["stars"], name=repo, mode="lines+markers",
                                line=dict(width=2, color=PALETTE[i % 8]), marker=dict(size=8))
            st.plotly_chart(base_layout(fig, "Stars over time", yfmt="~s"), use_container_width=True)
        else:
            st.caption("Star history builds up from weekly snapshots (GitHub has no free star-history endpoint).")
footer()
