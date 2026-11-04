"""Optional weekly "what moved" summary written by Claude Haiku.

Runs only if ANTHROPIC_API_KEY is set; otherwise it is skipped silently and the
app shows the table without prose. The model only sees the computed movers
table (no free-form web data) and is told to describe, not recommend.
"""
from __future__ import annotations

import datetime as dt
import logging
import os

import pandas as pd

from tracker.config import PROCESSED

log = logging.getLogger(__name__)

MODEL = "claude-haiku-5-5"
OUT = PROCESSED / "summary.md"

SYSTEM = (
    "You write a short, neutral weekly note for a public dashboard that tracks developer "
    "adoption of AI and data-infrastructure tools (package downloads and HN hiring-post "
    "mentions). Describe only what the numbers in the table show. Never give investment "
    "advice, price targets, or buy/sell opinions, and do not speculate about stock prices. "
    "Mention that weekly download counts are noisy (CI bots, holidays) when a move is small "
    "or a single week. Plain text, 3-5 bullet points, under 130 words total."
)


def movers_markdown(moved: pd.DataFrame, top: int = 12) -> str:
    cols = ["name", "registry", "package", "downloads", "wow", "vs_prior4", "yoy_4wk"]
    t = moved[cols].head(top).copy()
    for c in ("wow", "vs_prior4", "yoy_4wk"):
        t[c] = t[c].map(lambda v: "" if pd.isna(v) else f"{v:+.1%}")
    t["downloads"] = t["downloads"].map(lambda v: f"{int(v):,}")
    header = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return header + "\n".join("| " + " | ".join(str(x) for x in r) + " |" for r in t.itertuples(index=False))


def generate(moved: pd.DataFrame) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or moved is None or moved.empty:
        log.info("summary: skipped (no ANTHROPIC_API_KEY or no data)")
        return None
    import anthropic

    week = moved["week"].max()
    client = anthropic.Anthropic(api_key=key)
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            output_config={"effort": "low"},
            system=SYSTEM,
            messages=[{"role": "user", "content":
                       f"Week ending {week}. Columns: wow = vs prior week, vs_prior4 = vs average of "
                       f"prior 4 weeks, yoy_4wk = 4-week average vs same period last year.\n\n"
                       f"{movers_markdown(moved)}"}],
        )
    except anthropic.APIError as exc:
        log.warning("summary: API error, skipping: %s", exc)
        return None
    if resp.stop_reason == "refusal":
        log.warning("summary: model declined; skipping")
        return None
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        return None
    stamp = dt.date.today().isoformat()
    body = f"<!-- generated {stamp} by {MODEL} from what_moved.csv -->\n**Week ending {week}**\n\n{text}\n"
    OUT.write_text(body)
    return body
