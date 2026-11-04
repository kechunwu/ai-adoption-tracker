"""Cached loaders for the Streamlit app (reads only files committed in data/)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
PROC = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"


def _csv(path: Path, dates=()) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    for d in dates:
        if d in df:
            df[d] = pd.to_datetime(df[d])
    return df


@st.cache_data(ttl=3600)
def weekly() -> pd.DataFrame:
    return _csv(PROC / "downloads_weekly.csv", ["week"])


@st.cache_data(ttl=3600)
def entity_weekly() -> pd.DataFrame:
    return _csv(PROC / "entity_weekly.csv", ["week"])


@st.cache_data(ttl=3600)
def hn() -> pd.DataFrame:
    df = _csv(PROC / "hn_share.csv")
    if not df.empty:
        df["month_dt"] = pd.to_datetime(df["month"] + "-01")
    return df


@st.cache_data(ttl=3600)
def hn_matches() -> pd.DataFrame:
    p = RAW / "hn_matches.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


@st.cache_data(ttl=3600)
def moved() -> pd.DataFrame:
    return _csv(PROC / "what_moved.csv")


@st.cache_data(ttl=3600)
def github() -> pd.DataFrame:
    return _csv(RAW / "github_snapshots.csv", ["snapshot_date"])


@st.cache_data(ttl=3600)
def panel() -> pd.DataFrame:
    return _csv(PROC / "quarterly_panel.csv", ["period_end"])


@st.cache_data(ttl=3600)
def leadlag() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    s = PROC / "leadlag_summary.json"
    return (_csv(PROC / "leadlag_company.csv"), _csv(PROC / "leadlag_pooled.csv"),
            json.loads(s.read_text()) if s.exists() else {})


def summary_md() -> str | None:
    p = PROC / "summary.md"
    return p.read_text() if p.exists() else None


def run_log() -> dict:
    p = ROOT / "data" / "run_log.json"
    return json.loads(p.read_text()) if p.exists() else {}


def no_data_notice():
    st.info("No data has been pulled yet. Run the **Weekly data pull** GitHub Action "
            "(Actions tab → Weekly data pull → Run workflow); the app reads the CSVs it commits to `data/`.")
