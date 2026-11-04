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
5. *Customer, investor and pedigree lists*: "trusted by teams at Anthropic", "customers include Mistral",
   "founded by ex-Snowflake engineers", "backed by … OpenAI" describe the company as a customer, investor or
   former employer, not as a tool in use. A mention is skipped if such a phrase appears earlier in the *same
   sentence*. This rule was added after auditing a random sample of real matches (the first data pull), and all
   months were re-matched.
6. *Employer vs. user*: a post **by** the company ("Snowflake | Senior Engineer | …") is hiring, not adoption.
   If the employer alias appears in the header's first `|`-separated field the match is flagged
   `is_employer`. The adoption share **excludes** those posts; they are counted separately.

**Metric.** `share = posts mentioning the tool (excl. its own posts) / all top-level posts that month`.
Normalising by total posts removes the swings in overall HN hiring volume. For quarterly analysis we pool
mentions and posts across the months of the fiscal quarter.

**Auditability.** Every match stores a ±60-character snippet (`data/raw/hn_matches.parquet`), viewable in the
app. If the matching rules change, a rules hash changes and all months are re-processed.

## 3. Downloads

Daily counts → weekly totals (weeks ending Sunday) → 4-week average (rolling 28 days) → YoY = 4-week average
vs the same 4 weeks 52 weeks earlier. On the charts and tables, YoY is shown only when the year-earlier base is
at least 10,000 downloads a week; growth from a near-zero first-year base (e.g. +100,000%) is not meaningful.
(The lead/lag study keeps its pre-registered quarterly definition; see section 5.)

Data problems found in the first pull, and how they are handled:

- **npm outage days.** On 14 days (3 isolated days in 2020–23, then 11 in Sep–Oct 2026) npm's API reported
  exactly 0 for *every* package, which is a registry-side gap, not real usage. A day is treated as an outage when at
  least half of the "established" packages (median ≥ 1,000/day over the prior 28 days) report 0. A 0 for an
  established package on any other day is also treated as missing. Missing days are filled from the same weekday
  1 week before/after (falling back to 2 weeks), which preserves the strong weekday/weekend pattern. A week with
  more than 2 filled days is left blank, and week-over-week is only computed against the true prior calendar week.
  The list of outage days is printed at the bottom of this page. Each run re-fetches the last 5 weeks, so late
  back-fills by npm replace the filled values.
- **Pre-launch zeros.** npm returns 0 for dates before a package existed; those rows are dropped.
- **Registry-wide inflation (npm, 2026).** Download growth accelerated for *every* npm package at once in
  2026 (MongoDB's driver went from about +34% to +129% YoY, Datadog's tracer from +55% to +205%). That pattern
  points to CI, bot and AI-coding-agent installs rather than adoption. So each registry has a **control basket**
  of mature, ubiquitous packages (npm: react, lodash, express, typescript, axios; PyPI: requests, numpy, urllib3,
  setuptools), and the site also shows **YoY relative to the baseline**: (1 + YoY<sub>package</sub>) /
  (1 + YoY<sub>basket</sub>) − 1.
- **PyPI counting break (2026-08-25).** pypistats counts fell 35–55% for every package between 24 and 25
  August 2026, including requests and numpy. This is recorded in `config/tracked.yaml` as a known registry break
  and marked on PyPI charts. Raw YoY whose comparison window spans the break is left blank; baseline-relative
  YoY stays valid because the basket breaks too.
- **Other noise**: CI pipelines and Docker builds re-download packages; mirrors (excluded on PyPI); holiday
  weeks; package renames (legacy names included, e.g. `@google/generative-ai`, `google-generativeai`).

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

### Changes made after seeing the data (post-hoc), kept separate

- **npm/PyPI downloads relative to the registry baseline** (`npm_rel`, `pypi_rel`) were added after the
  registry-wide 2026 inflation showed up in the raw data. They are reported next to, not instead of, the
  pre-registered raw signals, are labelled *post-hoc* everywhere, and sit in their own multiple-testing family.
  The pre-registered company + calendar-quarter fixed-effects panel already removed anything common to all six
  companies in a quarter, including this inflation.
- The HN customer/investor/pedigree rule (section 2, rule 5) and the npm/PyPI data-quality fixes (section 3)
  change *measurement*, not the test design. They were motivated by inspecting raw data and match samples.
  For full transparency: a first lead/lag run on the uncorrected data had already been computed (its summary
  counts were seen: 0 of 55 company-level and 5 of 20 pooled pre-registered tests at p < 0.05) when these
  fixes were made. No fix was chosen by comparing lead/lag outcomes across alternatives.

## 6. Limitations

- Small samples: ~15–30 quarterly YoY points per company, fewer for recent IPOs (CFLT 2021) and none for the
  PyPI signal until a year of history accrues. Power is low; nulls are "not detectable", not "absent".
- Proxies include free and open-source usage (community MongoDB, Apache Kafka, OpenSearch users of Elastic
  clients). Downloads are inflated by CI. HN skews to US tech startups.
- Corporate events: IBM agreed to acquire Confluent (announced December 2025). Once a company stops filing,
  its revenue series simply ends at its last 10-Q/10-K.
- Correlation ≠ causation; this is descriptive research, **not investment advice**.
