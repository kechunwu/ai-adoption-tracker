"""Weekly snapshots of GitHub repo stats.

Star counts have no reliable free history endpoint (the stargazers API caps
at 40k stars), so we take a snapshot every week and the history accumulates in
data/raw/github_snapshots.csv. Uses GITHUB_TOKEN (provided automatically in
GitHub Actions) for a 5,000 req/h limit.
"""
from __future__ import annotations

import datetime as dt
import logging
import re

import pandas as pd

from tracker.config import RAW, entities
from tracker.http import env, make_session
from tracker.storage import upsert

log = logging.getLogger(__name__)

API = "https://api.github.com"
OUT = RAW / "github_snapshots.csv"
_LAST_RE = re.compile(r'[?&]page=(\d+)>;\s*rel="last"')


def count_from_link(link_header: str | None, n_items_on_page: int) -> int:
    """With per_page=1 the 'last' page number equals the total count."""
    if link_header:
        m = _LAST_RE.search(link_header)
        if m:
            return int(m.group(1))
    return n_items_on_page


def _count(session, url: str, params: dict | None = None) -> int | None:
    r = session.get(url, params={"per_page": 1, **(params or {})}, timeout=60)
    if r.status_code in (204, 404):
        return 0
    if r.status_code == 403 and "too large" in r.text.lower():
        return None  # contributor list too large to compute via API
    r.raise_for_status()
    return count_from_link(r.headers.get("Link"), len(r.json()))


def repo_snapshot(session, full_name: str, today: str) -> dict:
    r = session.get(f"{API}/repos/{full_name}", timeout=60)
    r.raise_for_status()
    js = r.json()
    rel = session.get(f"{API}/repos/{full_name}/releases/latest", timeout=60)
    latest = rel.json() if rel.status_code == 200 else {}
    return {
        "snapshot_date": today,
        "repo": full_name,
        "stars": js.get("stargazers_count"),
        "forks": js.get("forks_count"),
        "watchers": js.get("subscribers_count"),
        "open_issues": js.get("open_issues_count"),
        "contributors": _count(session, f"{API}/repos/{full_name}/contributors", {"anon": "true"}),
        "releases": _count(session, f"{API}/repos/{full_name}/releases"),
        "latest_release": latest.get("tag_name"),
        "latest_release_at": latest.get("published_at"),
        "pushed_at": js.get("pushed_at"),
    }


def run(today: dt.date | None = None) -> pd.DataFrame:
    today_s = (today or dt.date.today()).isoformat()
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = env("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    session = make_session(extra_headers=headers)
    rows = []
    for e in entities():
        for repo in e.github:
            try:
                snap = repo_snapshot(session, repo, today_s)
                snap["entity"] = e.id
                rows.append(snap)
                log.info("github %s: %s stars", repo, snap["stars"])
            except Exception as exc:  # one bad repo shouldn't kill the run
                log.warning("github %s failed: %s", repo, exc)
    new = pd.DataFrame(rows)
    return upsert(OUT, new, keys=["snapshot_date", "repo"], sort=["repo", "snapshot_date"])
