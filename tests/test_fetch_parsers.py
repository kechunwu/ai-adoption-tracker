import datetime as dt

from tracker.fetch.github import count_from_link
from tracker.fetch.hn import parse_thread_title, threads_from_search, top_level_posts, process_thread, monthly_table
from tracker.fetch.npm import date_chunks, parse_range_response
from tracker.fetch.pypi import parse_overall
from tracker.config import entities, hn_context_settings
from tracker.hn_match import build_matchers


def test_npm_parse(load_fixture):
    df = parse_range_response(load_fixture("npm_range.json"))
    assert list(df.columns) == ["date", "package", "downloads"]
    assert df["downloads"].tolist() == [100, 120, 0]
    assert set(df["package"]) == {"@anthropic-ai/sdk"}


def test_npm_chunks_cover_range_without_gaps():
    start, end = dt.date(2016, 1, 1), dt.date(2026, 11, 3)
    chunks = list(date_chunks(start, end))
    assert chunks[0][0] == start and chunks[-1][1] == end
    for (a, b), (c, _) in zip(chunks, chunks[1:]):
        assert c == b + dt.timedelta(days=1)
    assert all((b - a).days < 540 for a, b in chunks)  # API limit: 18 months


def test_pypi_keeps_without_mirrors(load_fixture):
    df = parse_overall(load_fixture("pypistats_overall.json"))
    assert df["downloads"].tolist() == [1000, 1200]


def test_github_link_count():
    link = '<https://api.github.com/repositories/1/contributors?per_page=1&page=2>; rel="next", ' \
           '<https://api.github.com/repositories/1/contributors?per_page=1&page=1234>; rel="last"'
    assert count_from_link(link, 1) == 1234
    assert count_from_link(None, 1) == 1
    assert count_from_link(None, 0) == 0


def test_hn_title_parsing():
    assert parse_thread_title("Ask HN: Who is hiring? (March 2024)") == "2024-03"
    assert parse_thread_title("Ask HN: Who is hiring? (Sept 2019)") == "2019-09"
    assert parse_thread_title("Ask HN: Who wants to be hired? (March 2024)") is None


def test_hn_thread_discovery_filters(load_fixture):
    df = threads_from_search(load_fixture("hn_search.json")["hits"])
    assert df["month"].tolist() == ["2016-01", "2024-03"]  # 2015 dropped, non-hiring threads dropped


def test_hn_top_level_only_and_deleted_skipped(load_fixture):
    posts = top_level_posts(load_fixture("hn_item.json"))
    assert [p["post_id"] for p in posts] == [1, 2, 4, 5]


def test_hn_process_thread_end_to_end(load_fixture):
    matchers = build_matchers(entities(), hn_context_settings())
    n, rows = process_thread("2024-03", load_fixture("hn_item.json"), matchers)
    assert n == 4
    got = {(r["post_id"], r["entity"]): r["is_employer"] for r in rows}
    # post 1: Snowflake, Kafka (CFLT), Claude w/ AI context, GPT-4 -> OpenAI. Reply's MongoDB is NOT top-level.
    assert got[(1, "SNOW")] is False
    assert got[(1, "CFLT")] is False
    assert (1, "anthropic") in got and (1, "openai") in got
    assert (1, "MDB") not in got
    # post 2 is BY Snowflake -> employer flag
    assert got[(2, "SNOW")] is True
    # post 4: snowflake schema + "Email Claude" -> nothing
    assert not any(pid == 4 for pid, _ in got)
    # post 5: Datadog + Elasticsearch/Kibana; Elastic Beanstalk / Confluence don't count extra
    assert (5, "DDOG") in got and (5, "ESTC") in got and (5, "CFLT") not in got

    import pandas as pd
    threads = pd.DataFrame([{"month": "2024-03", "n_posts": n}])
    monthly = monthly_table(threads, pd.DataFrame(rows), ["SNOW", "MDB"]).set_index("entity")
    assert monthly.loc["SNOW", "mentions"] == 2
    assert monthly.loc["SNOW", "mentions_ex_employer"] == 1
    assert monthly.loc["SNOW", "share_ex_employer"] == 0.25
    assert monthly.loc["MDB", "mentions"] == 0
