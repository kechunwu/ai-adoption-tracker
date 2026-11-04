"""Shared chart styling: fixed categorical order, color follows the entity."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

# Validated categorical palette (light surface), assigned in fixed order.
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
REGISTRY_COLOR = {"npm": PALETTE[0], "pypi": PALETTE[1]}
# AI SDK comparison: one stable color per vendor wherever it appears.
VENDOR_COLOR = {"openai": PALETTE[0], "anthropic": PALETTE[1], "google-genai": PALETTE[2], "mistralai": PALETTE[3]}
POS, NEG, NEUTRAL = "#2a78d6", "#e34948", "#8a8984"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e0"

PORTFOLIO = "https://kechunwu.github.io"
REPO = "https://github.com/kechunwu/ai-adoption-tracker"


def base_layout(fig: go.Figure, title: str | None = None, yfmt: str | None = None, height=360) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0, font=dict(size=15, color=INK)) if title else None,
        height=height, margin=dict(l=8, r=8, t=48 if title else 16, b=8),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK2, size=12), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, title=None),
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, ticks="outside", tickcolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickformat=yfmt)
    return fig


def footer():
    st.divider()
    st.caption(f"Built by Kechun Wu · [Portfolio]({PORTFOLIO}) · [Source code]({REPO}) · "
               "Free public data: npm, PyPI (pypistats), Hacker News (Algolia), GitHub, SEC EDGAR XBRL. "
               "Not investment advice.")
