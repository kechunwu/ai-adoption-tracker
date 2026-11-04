"""Hacker News "Ask HN: Who is hiring?" threads via the Algolia HN API.

1. Discover monthly threads posted by the `whoishiring` account
   (search_by_date, tags=story,author_whoishiring) back to 2016-01.
2. For each thread, GET /items/{id} and keep the top-level comments: by the
   thread rules each top-level comment is one job post.
3. Match every post against the alias rules (tracker/hn_match.py) and store
   - data/raw/hn_threads.csv        one row per month (thread id, #posts)
   - data/raw/hn_matches.parquet    one row per (post, entity) mention,
                                    with a short snippet for auditing
   - data/raw/hn_monthly.csv        per month x entity counts and shares

We don't store full post text (it would be >100 MB); if the matching rules
change (rules hash differs), all months are re-fetched and re-matched.
Months still accumulating posts (the latest two) are always refreshed.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import time

import pandas as pd

from tracker.config import RAW, entities, hn_context_settings
from tracker.hn_match import build_matchers, match_post, rules_hash
from tracker.http import make_session
from tracker.storage import read_csv

log = logging.getLogger(__name__)

API = "https://hn.algolia.com/api/v1"
START_MONTH = "2016-01"
TITLE_RE = re.compile(r"^Ask HN:\s*Who is hiring\?\s*\(([A-Za-z]+)\s+(\d{4})\)", re.I)
THREADS = RAW / "hn_threads.csv"
MATCHES = RAW / "hn_matches.parquet"
MONTHLY = RAW / "hn_monthly.csv"
REFRESH_RECENT = 2


def parse_thread_title(title: str) -> str | None:
    """'Ask HN: Who is hiring? (March 2024)' -> '2024-03'."""
    m = TITLE_RE.match(title or "")
    if not m:
        return None
    try:
        d = dt.datetime.strptime(f"{m.group(1)[:3]} {m.group(2)}", "%b %Y")
    except ValueError:
        return None
    return d.strftime("%Y-%m")


def threads_from_search(hits: list[dict]) -> pd.DataFrame:
    rows = []
    for h in hits:
        month = parse_thread_title(h.get("title", ""))
        if month and month >= START_MONTH:
            rows.append({
                "month": month,
                "story_id": int(h["objectID"]),
                "title": h["title"],
                "num_comments": h.get("num_comments") or 0,
            })
    df = pd.DataFrame(rows, columns=["month", "story_id", "title", "num_comments"])
    # if a month somehow has two threads, keep the bigger one
    df = df.sort_values("num_comments").drop_duplicates("month", keep="last")
    return df.sort_values("month").reset_index(drop=True)


def discover_threads(session) -> pd.DataFrame:
    since = int(dt.datetime(2015, 12, 15).timestamp())
    hits, page = [], 0
    while True:
        r = session.get(
            f"{API}/search_by_date",
            params={"tags": "story,author_whoishiring", "hitsPerPage": 200, "page": page,
                    "numericFilters": f"created_at_i>{since}"},
            timeout=60,
        )
        r.raise_for_status()
        js = r.json()
        hits.extend(js.get("hits", []))
        page += 1
        if page >= js.get("nbPages", 0):
            break
        time.sleep(0.5)
    return threads_from_search(hits)


def top_level_posts(item: dict) -> list[dict]:
    """Top-level, non-deleted comments of a thread item."""
    out = []
    for c in item.get("children", []) or []:
        if c.get("type", "comment") != "comment":
            continue
        if not c.get("text") or not c.get("author"):
            continue  # deleted / dead
        out.append({"post_id": c["id"], "created_at": c.get("created_at", ""), "text": c["text"]})
    return out


def process_thread(month: str, item: dict, matchers) -> tuple[int, list[dict]]:
    posts = top_level_posts(item)
    rows = []
    post_date = f"{month}-01"
    for p in posts:
        for hit in match_post(matchers, p["text"], post_date):
            rows.append({"month": month, "post_id": p["post_id"], **hit})
    return len(posts), rows


def monthly_table(threads: pd.DataFrame, matches: pd.DataFrame, entity_ids: list[str]) -> pd.DataFrame:
    """Per month x entity: mentions, share of all posts, share excl. employer posts."""
    rows = []
    for _, t in threads.iterrows():
        m = matches[matches["month"] == t["month"]] if not matches.empty else matches
        n = int(t["n_posts"])
        for eid in entity_ids:
            me = m[m["entity"] == eid] if not m.empty else m
            mentions = int(me["post_id"].nunique()) if not me.empty else 0
            non_emp = int(me.loc[~me["is_employer"].astype(bool), "post_id"].nunique()) if not me.empty else 0
            emp = mentions - non_emp
            rows.append({
                "month": t["month"], "entity": eid, "total_posts": n,
                "mentions": mentions, "mentions_ex_employer": non_emp, "employer_posts": emp,
                "share": mentions / n if n else float("nan"),
                "share_ex_employer": non_emp / n if n else float("nan"),
            })
    return pd.DataFrame(rows)


def run(full: bool = False) -> pd.DataFrame:
    ents = entities()
    ctx = hn_context_settings()
    matchers = build_matchers(ents, ctx)
    rhash = rules_hash(ents, ctx)
    session = make_session()

    found = discover_threads(session)
    log.info("HN: found %d monthly threads (%s..%s)", len(found), found["month"].min(), found["month"].max())

    cached = read_csv(THREADS)
    old_matches = pd.read_parquet(MATCHES) if MATCHES.exists() else pd.DataFrame()
    if full or cached.empty or "rules_hash" not in cached or (cached["rules_hash"] != rhash).any():
        log.info("HN: rules changed or full refresh -> reprocessing all months")
        todo = set(found["month"])
        cached = pd.DataFrame(columns=["month", "story_id", "title", "n_posts", "rules_hash"])
        old_matches = pd.DataFrame()
    else:
        recent = set(sorted(found["month"])[-REFRESH_RECENT:])
        todo = (set(found["month"]) - set(cached["month"])) | recent

    thread_rows, match_rows = [], []
    for _, t in found[found["month"].isin(todo)].iterrows():
        r = session.get(f"{API}/items/{t['story_id']}", timeout=120)
        r.raise_for_status()
        n_posts, rows = process_thread(t["month"], r.json(), matchers)
        log.info("HN %s: %d posts, %d mentions", t["month"], n_posts, len(rows))
        thread_rows.append({"month": t["month"], "story_id": t["story_id"], "title": t["title"],
                            "n_posts": n_posts, "rules_hash": rhash})
        match_rows.extend(rows)
        time.sleep(0.5)

    threads = pd.concat([cached[~cached["month"].isin(todo)], pd.DataFrame(thread_rows)], ignore_index=True)
    threads = threads.sort_values("month").reset_index(drop=True)
    new_matches = pd.DataFrame(match_rows, columns=["month", "post_id", "entity", "is_employer", "snippet"])
    if not old_matches.empty:
        old_matches = old_matches[~old_matches["month"].isin(todo)]
    matches = pd.concat([f for f in (old_matches, new_matches) if not f.empty], ignore_index=True) \
        if (not old_matches.empty or not new_matches.empty) else new_matches
    matches = matches.sort_values(["month", "post_id", "entity"]).reset_index(drop=True)

    THREADS.parent.mkdir(parents=True, exist_ok=True)
    threads.to_csv(THREADS, index=False)
    matches.to_parquet(MATCHES, index=False, compression="zstd")
    eids = [e.id for e in ents if e.hn and e.hn.get("aliases")]
    monthly = monthly_table(threads, matches, eids)
    monthly.to_csv(MONTHLY, index=False)
    return monthly
