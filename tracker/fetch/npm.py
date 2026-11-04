"""npm registry download counts.

API: https://api.npmjs.org/downloads/range/{start}:{end}/{package}
Docs: https://github.com/npm/registry/blob/main/docs/download-counts.md
Limits: each range query may span at most 18 months; data starts 2015-01-10.
We therefore fetch the full history back to HISTORY_START in <=365-day chunks,
then on each weekly run re-fetch only the trailing window (with an overlap so
late-arriving counts are corrected).
"""
from __future__ import annotations

import datetime as dt
import logging
import time

import pandas as pd

from tracker.config import RAW, entities
from tracker.http import make_session
from tracker.storage import read_csv, upsert

log = logging.getLogger(__name__)

BASE = "https://api.npmjs.org/downloads/range/{start}:{end}/{pkg}"
HISTORY_START = dt.date(2016, 1, 1)   # aligns with the HN series
CHUNK_DAYS = 365
OVERLAP_DAYS = 14
OUT = RAW / "npm_daily.csv"


def parse_range_response(payload: dict) -> pd.DataFrame:
    """Turn an API payload into tidy rows (date, package, downloads)."""
    if not payload or "downloads" not in payload:
        return pd.DataFrame(columns=["date", "package", "downloads"])
    rows = [
        {"date": d["day"], "package": payload["package"], "downloads": int(d["downloads"])}
        for d in payload["downloads"]
    ]
    return pd.DataFrame(rows, columns=["date", "package", "downloads"])


def date_chunks(start: dt.date, end: dt.date, days: int = CHUNK_DAYS):
    cur = start
    while cur <= end:
        stop = min(cur + dt.timedelta(days=days - 1), end)
        yield cur, stop
        cur = stop + dt.timedelta(days=1)


def fetch_package(session, pkg: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    frames = []
    for a, b in date_chunks(start, end):
        url = BASE.format(start=a.isoformat(), end=b.isoformat(), pkg=pkg)
        r = session.get(url, timeout=60)
        if r.status_code == 404:
            log.info("npm %s: no data for %s..%s (404)", pkg, a, b)
            continue
        r.raise_for_status()
        frames.append(parse_range_response(r.json()))
        time.sleep(0.3)
    if not frames:
        return pd.DataFrame(columns=["date", "package", "downloads"])
    return pd.concat(frames, ignore_index=True)


def packages() -> list[str]:
    seen = []
    for e in entities():
        for p in e.npm:
            if p not in seen:
                seen.append(p)
    return seen


def run(full: bool = False, today: dt.date | None = None) -> pd.DataFrame:
    today = today or dt.date.today()
    end = today - dt.timedelta(days=1)
    existing = read_csv(OUT)
    session = make_session()
    new_frames = []
    for pkg in packages():
        start = HISTORY_START
        if not full and not existing.empty and pkg in set(existing["package"]):
            last = pd.to_datetime(existing.loc[existing["package"] == pkg, "date"]).max().date()
            start = max(HISTORY_START, last - dt.timedelta(days=OVERLAP_DAYS))
        log.info("npm %s: %s..%s", pkg, start, end)
        new_frames.append(fetch_package(session, pkg, start, end))
    new = pd.concat(new_frames, ignore_index=True) if new_frames else pd.DataFrame()
    return upsert(OUT, new, keys=["date", "package"], sort=["package", "date"])
