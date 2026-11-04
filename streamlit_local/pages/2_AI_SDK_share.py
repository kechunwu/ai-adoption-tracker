import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_lib import data
from app_lib.style import VENDOR_COLOR, base_layout, footer

st.set_page_config(page_title="AI SDK share · AI Adoption Tracker", page_icon="📈", layout="wide")
st.title("AI SDK market share")
st.markdown(
    "Downloads of the official model-provider SDKs: **OpenAI vs Anthropic vs Google (Gen AI) vs Mistral**. "
    "This is a share of *SDK installs*, a developer-mindshare proxy, not API revenue or token share. "
    "Many apps reach models through gateways (LangChain, Vercel AI SDK, OpenRouter, cloud marketplaces) "
    "or via OpenAI-compatible endpoints using the `openai` SDK, which inflates OpenAI's count."
)

VENDORS = {"openai": "OpenAI", "anthropic": "Anthropic", "google-genai": "Google Gen AI", "mistralai": "Mistral"}
ew = data.entity_weekly()
if ew.empty:
    data.no_data_notice()
    st.stop()

c1, c2 = st.columns([1, 1])
reg = c1.radio("Registry", ["npm", "pypi"], horizontal=True,
               format_func=lambda r: {"npm": "npm (JavaScript/TypeScript)", "pypi": "PyPI (Python)"}[r])
since = c2.select_slider("Since", ["2023-01", "2024-01", "2025-01", "2026-01"], value="2024-01")

d = ew[(ew["registry"] == reg) & ew["entity"].isin(VENDORS) & (ew["week"] >= pd.Timestamp(since + "-01"))]
d = d.dropna(subset=["ma4"])
if d.empty:
    st.info("Not enough history yet for this registry.")
    st.stop()

wide = d.pivot_table(index="week", columns="entity", values="ma4").sort_index()
share = wide.div(wide.sum(axis=1), axis=0)

fig = go.Figure()
for e in [v for v in VENDORS if v in share]:
    fig.add_scatter(x=share.index, y=share[e], name=VENDORS[e], mode="lines", stackgroup="one",
                    line=dict(width=0.5, color="#fcfcfb"), fillcolor=VENDOR_COLOR[e],
                    hovertemplate="%{y:.1%}")
base_layout(fig, f"Share of combined SDK downloads ({reg}, 4-week average)", yfmt=".0%", height=400)
fig.update_yaxes(range=[0, 1])
st.plotly_chart(fig, use_container_width=True)

fig = go.Figure()
for e in [v for v in VENDORS if v in wide]:
    fig.add_scatter(x=wide.index, y=wide[e], name=VENDORS[e], mode="lines",
                    line=dict(width=2, color=VENDOR_COLOR[e]), hovertemplate="%{y:,.0f}")
log = st.toggle("Log scale", value=True)
base_layout(fig, f"Weekly downloads, 4-week average ({reg})", yfmt="~s", height=380)
if log:
    fig.update_yaxes(type="log")
st.plotly_chart(fig, use_container_width=True)

latest = share.iloc[-1]
year_ago = share[share.index <= share.index[-1] - pd.Timedelta(weeks=52)]
tbl = pd.DataFrame({"Share now": latest * 100})
if not year_ago.empty:
    tbl["Share 1y ago"] = year_ago.iloc[-1] * 100
    tbl["Change (pp)"] = tbl["Share now"] - tbl["Share 1y ago"]
tbl.index = [VENDORS[i] for i in tbl.index]
st.dataframe(tbl, use_container_width=True,
             column_config={c: st.column_config.NumberColumn(format="%.1f") for c in tbl.columns})
st.caption("Packages: npm openai, @anthropic-ai/sdk, @google/genai + @google/generative-ai (legacy), "
           "@mistralai/mistralai; PyPI openai, anthropic, google-genai + google-generativeai (legacy), mistralai.")

hn = data.hn()
if not hn.empty:
    h = hn[hn["entity"].isin(VENDORS) & (hn["month_dt"] >= pd.Timestamp("2022-01-01"))]
    fig = go.Figure()
    for e in [v for v in VENDORS if v in set(h["entity"])]:
        g = h[h["entity"] == e]
        fig.add_scatter(x=g["month_dt"], y=g["share_3m"], name=VENDORS[e], mode="lines",
                        line=dict(width=2, color=VENDOR_COLOR[e]), hovertemplate="%{y:.2%}")
    base_layout(fig, "Share of HN job posts mentioning each provider (3-month avg, excl. own posts)", yfmt=".1%")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Claude, Gemini and Mistral mentions are date-gated to their launches and require AI context "
               "nearby (to skip people named Claude and the Gemini crypto exchange). See Methodology.")
footer()
