"""SEC XBRL companyfacts -> quarterly revenue for the public companies.

API: https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
SEC fair-access rules: declare a User-Agent with contact info (read from the
SEC_USER_AGENT env var / repo secret) and stay under 10 requests/second.
"""
from __future__ import annotations

import logging

import pandas as pd

from tracker.config import PROCESSED, RAW, public_companies
from tracker.http import RateLimiter, env, make_session
from tracker.sec_revenue import add_yoy, extract_revenue_facts, quarterly_revenue

log = logging.getLogger(__name__)

URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
FACTS_OUT = RAW / "sec_revenue_facts.csv"
QUARTERLY_OUT = PROCESSED / "revenue_quarterly.csv"


def run() -> pd.DataFrame:
    ua = env("SEC_USER_AGENT")
    if not ua:
        raise RuntimeError("SEC_USER_AGENT is not set (e.g. 'Your Name your@email.com').")
    session = make_session(user_agent=ua, extra_headers={"Accept-Encoding": "gzip, deflate"})
    limiter = RateLimiter(per_second=5)  # well under SEC's 10/s
    facts_all, q_all = [], []
    for c in public_companies():
        limiter.wait()
        r = session.get(URL.format(cik=c.cik), timeout=60)
        r.raise_for_status()
        js = r.json()
        name = js.get("entityName", "")
        if c.sec_name_contains and c.sec_name_contains.lower() not in name.lower():
            raise RuntimeError(f"CIK {c.cik} resolved to '{name}', expected {c.name}")
        facts = extract_revenue_facts(js)
        facts.insert(0, "ticker", c.ticker)
        facts_all.append(facts)
        q = add_yoy(quarterly_revenue(facts, c.fiscal_year_end))
        q.insert(0, "ticker", c.ticker)
        q_all.append(q)
        log.info("SEC %s (%s): %d facts -> %d quarters (%s..%s)", c.ticker, name, len(facts), len(q),
                 q["period_end"].min(), q["period_end"].max())
    FACTS_OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(facts_all, ignore_index=True).to_csv(FACTS_OUT, index=False)
    out = pd.concat(q_all, ignore_index=True)
    QUARTERLY_OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(QUARTERLY_OUT, index=False)
    return out
