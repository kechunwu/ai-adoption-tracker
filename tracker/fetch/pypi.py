"""PyPI download counts via pypistats.org.

API: https://pypistats.org/api/packages/{pkg}/overall?mirrors=false
pypistats only keeps ~180 days of history, so we backfill what is available
on the first run and then upsert every week. The history in data/raw/
therefore grows over time and is the only long PyPI series we have.
"""
from __future__ import annotations

import logging
import time

import pandas as pd

from tracker.config import RAW, entities
from tracker.http import make_session
from tracker.storage import upsert

log = logging.getLogger(__name__)

BASE = "https://pypistats.org/api/packages/{pkg}/overall"
OUT = RAW / "pypi_daily.csv"


def parse_overall(payload: dict) -> pd.DataFrame:
    """Keep the 'without_mirrors' category (downloads excluding PyPI mirrors)."""
    rows = []
    pkg = payload.get("package")
    for d in payload.get("data", []):
        if d.get("category") == "without_mirrors":
            rows.append({"date": d["date"], "package": pkg, "downloads": int(d["downloads"])})
    return pd.DataFrame(rows, columns=["date", "package", "downloads"])


def packages() -> list[str]:
    seen = []
    for e in entities():
        for p in e.pypi:
            if p not in seen:
                seen.append(p)
    return seen


def run() -> pd.DataFrame:
    session = make_session()
    frames = []
    for pkg in packages():
        r = session.get(BASE.format(pkg=pkg), params={"mirrors": "false"}, timeout=60)
        if r.status_code == 404:
            log.warning("pypi %s: 404", pkg)
            continue
        r.raise_for_status()
        frames.append(parse_overall(r.json()))
        log.info("pypi %s: %d rows", pkg, len(frames[-1]))
        time.sleep(2.0)  # pypistats asks clients to be gentle
    new = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return upsert(OUT, new, keys=["date", "package"], sort=["package", "date"])
