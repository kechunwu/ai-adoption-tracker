"""AI Adoption Tracker: home page / what moved this week."""
import pandas as pd
import streamlit as st

from app_lib import data
from app_lib.style import PORTFOLIO, REPO, footer

st.set_page_config(page_title="AI Adoption Tracker", page_icon="📈", layout="wide")

st.title("AI Adoption Tracker")
st.markdown(
    "**Do developer-adoption signals lead revenue for data-infrastructure companies?** "
    "This app tracks how fast developers and companies adopt AI and data-infrastructure tools, "
    "using free public data (package downloads, *Ask HN: Who is hiring?* posts, GitHub), "
    "and tests whether those signals lead the reported revenue of six public companies "
    "(SNOW, DDOG, MDB, CFLT, ESTC, NET)."
)
st.caption(f"By Kechun Wu · [Portfolio]({PORTFOLIO}) · [GitHub]({REPO}) · Data refreshed weekly by GitHub Actions")

moved = data.moved()
weekly = data.weekly()
hn = data.hn()
_, _, ll = data.leadlag()

if moved.empty and hn.empty:
    data.no_data_notice()
    footer()
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Packages tracked", f"{weekly['package'].nunique() if not weekly.empty else 0}")
c2.metric("Latest full week", moved["week"].max() if not moved.empty else "n/a")
c3.metric("HN hiring threads", f"{hn['month'].nunique() if not hn.empty else 0}",
          help="Monthly 'Ask HN: Who is hiring?' threads parsed since 2016-01")
if ll:
    c4.metric("Lead/lag tests significant (p<0.05)",
              f"{ll.get('company_tests_p_lt_05', 0)} / {ll.get('company_tests_run', 0)}",
              help=f"Expected by chance alone: ~{ll.get('expected_false_positives_at_05')}. See the Lead-lag study page.")

st.subheader("What moved this week")
summary = data.summary_md()
if summary:
    with st.container(border=True):
        st.markdown(summary.split("-->", 1)[-1])
        st.caption("Auto-written by Claude Haiku from the table below. Describes data only; not investment advice.")

if not moved.empty:
    show = moved.copy()
    names = sorted(show["name"].unique())
    pick = st.multiselect("Filter tools", names, placeholder="All tools")
    if pick:
        show = show[show["name"].isin(pick)]
    cols = {"name": "Tool", "registry": "Registry", "package": "Package", "downloads": "Downloads (last week)",
            "wow": "vs prior week", "vs_prior4": "vs prior 4-wk avg", "yoy_4wk": "YoY (4-wk avg)",
            "hn_month": "HN month", "hn_share": "HN share"}
    show = show[[c for c in cols if c in show]].rename(columns=cols)
    for c in ["vs prior week", "vs prior 4-wk avg", "YoY (4-wk avg)"]:
        show[c] = show[c] * 100
    if "HN share" in show:
        show["HN share"] = show["HN share"] * 100
    st.dataframe(
        show, hide_index=True, use_container_width=True,
        column_config={
            "Downloads (last week)": st.column_config.NumberColumn(format="localized"),
            "vs prior week": st.column_config.NumberColumn(format="%+.1f%%"),
            "vs prior 4-wk avg": st.column_config.NumberColumn(format="%+.1f%%"),
            "YoY (4-wk avg)": st.column_config.NumberColumn(format="%+.0f%%"),
            "HN share": st.column_config.NumberColumn(format="%.2f%%",
                                                      help="Share of HN job posts mentioning the tool (excl. its own posts)"),
        },
    )
    st.caption("Sorted by the size of the move vs the prior 4-week average. One-week moves in download "
               "counts are noisy (CI pipelines, mirrors, holidays). Treat them as prompts to look, not as signals.")

log = data.run_log()
if log:
    bad = [k for k, v in log.get("steps", {}).items() if not v.get("ok")]
    st.caption(f"Last pipeline run: {log.get('finished', '?')} UTC"
               + (f" · ⚠️ failed steps: {', '.join(bad)}" if bad else " · all steps OK"))

st.markdown(
    "**Pages:** *Tool trends* (per-tool downloads, YoY, hiring share) · *AI SDK share* "
    "(OpenAI vs Anthropic vs Google vs Mistral) · *Lead-lag study* (the main analysis) · *Methodology*."
)
footer()
