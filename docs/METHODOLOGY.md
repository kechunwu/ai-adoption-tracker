# Methodology

## 1. Data sources (all free, official APIs, no HTML scraping)

| Source | Endpoint | What we keep | History |
|---|---|---|---|
| npm | `api.npmjs.org/downloads/range/{start}:{end}/{pkg}` | daily downloads | back to 2016-01, fetched in ≤365-day chunks (the API caps each request at 18 months) |
| PyPI | `pypistats.org/api/packages/{pkg}/overall?mirrors=false` | daily downloads excl. mirrors | pypistats keeps ~180 days; we backfill that and **append weekly**, so the series grows over time |
| Hacker News | `hn.algolia.com/api/v1` (`search_by_date` + `items/{id}`) | top-level comments of each monthly *Ask HN: Who is hiring?* thread | 2016-01 → today |
| GitHub | REST API with the Actions `GITHUB_TOKEN` | stars, forks, watchers, contributors, releases | weekly snapshots from the first run (no free star history) |
| SEC EDGAR | `data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | revenue facts from 10-K/10-Q | full XBRL history; ≤5 req/s with a declared User-Agent |

The package → company mapping, with the reason each proxy was chosen, lives in one file:
[`config/tracked.yaml`](../config/tracked.yaml).

## 2. Hacker News hiring-post share

**Thread discovery.** Stories by the `whoishiring` account whose title matches
`Ask HN: Who is hiring? (Month YYYY)`. "Who wants to be hired" and "Freelancer" threads are excluded.

**Posts.** Only *top-level* comments count (by thread rules, one job post each). Replies, deleted and dead
comments are dropped. HTML is unescaped and tags stripped.

**Matching** (`tracker/hn_match.py`, unit-tested in `tests/test_hn_match.py`):

1. *Word boundaries, case-insensitive, with alias lists*: `\bmongo(db)?\b` matches MongoDB but not
   "mongoose"; `\bconfluent\b` never matches "Confluence"; `kafka|confluent` both map to Confluent.
2. *Exclusion phrases*: a mention is dropped if it sits inside "snowflake schema", "Snowflake ID(s)",
   "special snowflake", "Gemini exchange", etc. Another real mention in the same post still counts.
3. *Context gates for ambiguous names* (Claude, Gemini, Mistral): the mention must be dated after the
   product's public launch **and** either appear in a product form ("Claude Code", "Gemini API", "Mistral 7B")
   or have an AI-context word within 100 characters (LLM, GPT, OpenAI, "language model", prompt, RAG,
   inference, ...). Generic words such as "model" and "agent" were *removed* from the context list after a
   test fixture ("We model our warehouse … email Claude at …") showed they produced false positives.
4. *Aliases deliberately not used*: bare "Elastic" (AWS Elastic Beanstalk/IP/Load Balancing), bare "GPT"
   (GUID Partition Table; we require a version like GPT-4), "transformers", "AI SDK".
5. *Employer vs. user*: a post **by** the company ("Snowflake | Senior Engineer | …") is hiring, not adoption.
   If the employer alias appears in the header's first `|`-separated field the match is flagged
   `is_employer`. The adoption share **excludes** those posts; they are counted separately.

**Metric.** `share = posts mentioning the tool (excl. its own posts) / all top-level posts that month`.
Normalising by total posts removes the swings in overall HN hiring volume. For quarterly analysis we pool
mentions and posts across the months of the fiscal quarter.

**Auditability.** Every match stores a ±60-character snippet (`data/raw/hn_matches.parquet`), viewable in the
app. If the matching rules change, a rules hash changes and all months are re-processed.

## 3. Downloads

Daily counts → weekly sums (weeks ending Sunday, complete weeks only) → 4-week moving average → YoY
= 4-week average vs the same 4 weeks 52 weeks earlier. Known noise: CI pipelines and Docker builds re-download
packages; mirrors (excluded on PyPI); holiday weeks; new major versions that change install patterns;
package renames (we include legacy names, e.g. `@google/generative-ai` and `google-generativeai`).

## 4. Reported revenue (SEC XBRL)

`tracker/sec_revenue.py`, unit-tested in `tests/test_sec_revenue.py`:

- Tags in priority order: `RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`,
  `RevenueFromContractWithCustomerIncludingAssessedTax`, `SalesRevenueNet`.
- Forms: 10-K, 10-Q and amendments only. For each (start, end) period: highest-priority tag, then the most
  recently **filed** value (restatements and later comparatives win).
- Quarters = facts with 80–100-day durations. **Q4 = full year − nine-month YTD** with the same start date
  (fallback: FY − Q1 − Q2 − Q3). A test checks the four quarters sum to the 10-K annual figure.
- **Non-calendar fiscal years**: Snowflake and MongoDB end 31 January, Elastic 30 April. Fiscal years are
  labelled by the calendar year they end in (company convention). YoY compares the same fiscal quarter one
  year apart, and signals are aggregated over each company's exact fiscal-quarter dates, so no calendar
  approximation enters the study.
- The CIK → company link is asserted against `entityName` on every pull.

## 5. Lead/lag study design (fixed before any data was pulled)

The settings live in `config/tracked.yaml` under `analysis:` and were committed before the first data pull
(see git history). Nothing below was tuned on the results.

- **Unit**: company × fiscal quarter. **Variables**: log YoY growth of revenue and of each signal.
- **Lags**: k = 0, 1, 2, 3, 4 quarters; `corr(signal[t−k], revenue[t])`. *All* are reported.
- **Specifications**: primary = YoY growth levels; robustness = quarter-on-quarter change in YoY growth
  ("acceleration"), which strips slow shared trends.
- **Minimum** 8 overlapping quarters, otherwise the cell is reported as untestable.
- **Uncertainty**:
  - *Effective sample size*: `n_eff = n / (1 + 2 Σ ρ_x(j) ρ_y(j))` (Bartlett; Pyper & Peterman 1998).
    YoY series are highly autocorrelated, so n_eff is often far below n.
  - *95% CI*: Fisher z-transform with n_eff.
  - *p (headline)*: t-test of r with n_eff degrees of freedom.
  - *p_perm (secondary)*: block permutation (4-quarter blocks of the signal shuffled).
  - **Why n_eff and not the permutation test**: before pulling data we ran a null calibration
    (`scripts/null_calibration.py`, results in [`null_calibration.md`](null_calibration.md)). On pairs of
    *independent* persistent series of our length, the naive test flagged 10–58% as "significant", the
    block permutation test 4–27%, and the n_eff t-test 1–6% (≈ the nominal 5%). So the n_eff p is the
    headline.
- **Multiple comparisons**: `p_lag_adj` = Bonferroni over the lags tried per company/signal (pays for
  "picking the best lag"); `q_bh` = Benjamini-Hochberg across all company tests; and we always show how many
  "significant" results to expect from chance alone (5% of tests run).
- **Pooled panel**: stack the six companies after within-company demeaning (company fixed effects), and again
  after also removing calendar-quarter means (company + time fixed effects). The second version asks the
  cross-sectional question: *did the company whose signal grew faster than its peers also grow revenue
  faster than its peers?* That guards against one macro cycle (2021 boom, 2022–23 cost-cutting) driving
  everything. CIs use the summed per-company n_eff.

## 6. Limitations

- Small samples: ~15–30 quarterly YoY points per company, fewer for recent IPOs (CFLT 2021) and none for the
  PyPI signal until a year of history accrues. Power is low; nulls are "not detectable", not "absent".
- Proxies include free and open-source usage (community MongoDB, Apache Kafka, OpenSearch users of Elastic
  clients). Downloads are inflated by CI. HN skews to US tech startups.
- Corporate events: IBM agreed to acquire Confluent (announced December 2025). Once a company stops filing,
  its revenue series simply ends at its last 10-Q/10-K.
- Correlation ≠ causation; this is descriptive research, **not investment advice**.
