import pytest

from tracker.config import entities, hn_context_settings
from tracker.hn_match import build_matchers, clean_html, post_header


@pytest.fixture(scope="module")
def M():
    return {m.entity_id: m for m in build_matchers(entities(), hn_context_settings())}


def hit(M, eid, text, date="2024-06-01"):
    return M[eid].find(text, date)[0]


def test_clean_html():
    assert clean_html("A &amp; B<p>C &#x27;x&#x27; <a href=\"u\">link</a>") == "A & B\nC 'x' link"


def test_word_boundaries(M):
    assert hit(M, "MDB", "We use MongoDB and Postgres")
    assert hit(M, "MDB", "mongo shell")
    assert not hit(M, "MDB", "We use mongoose with node")
    assert not hit(M, "CFLT", "Docs live in Confluence")
    assert hit(M, "CFLT", "Event streaming on Apache Kafka")
    assert not hit(M, "CFLT", "A kafkaesque process")


def test_snowflake_false_positives(M):
    assert not hit(M, "SNOW", "We use a snowflake schema in Redshift")
    assert not hit(M, "SNOW", "IDs are Snowflake IDs from our generator")
    assert not hit(M, "SNOW", "You are not a special snowflake")
    assert hit(M, "SNOW", "Warehouse: Snowflake + dbt")
    # a real mention still counts even if an excluded phrase appears elsewhere
    assert hit(M, "SNOW", "snowflake schema design on Snowflake")


def test_claude_person_name_vs_model(M):
    assert not hit(M, "anthropic", "Questions? Email Claude at jobs@x.com", "2024-06-01")
    assert hit(M, "anthropic", "We build agents on top of Claude and other LLMs", "2024-06-01")
    assert hit(M, "anthropic", "Our team uses Claude Code daily", "2025-06-01")
    # before launch, even AI context does not count
    assert not hit(M, "anthropic", "Claude leads our ML team", "2019-06-01")
    assert hit(M, "anthropic", "We work with Anthropic", "2019-06-01")


def test_gemini_crypto(M):
    assert not hit(M, "google-genai", "We integrate with the Gemini exchange API for crypto")
    assert not hit(M, "google-genai", "Gemini LLM work", "2022-06-01")  # before launch
    assert hit(M, "google-genai", "We evaluate Gemini, GPT and Claude models", "2024-06-01")


def test_elastic_not_aws(M):
    assert not hit(M, "ESTC", "Deployed on AWS Elastic Beanstalk with Elastic Load Balancing")
    assert hit(M, "ESTC", "Search is Elasticsearch")
    assert hit(M, "ESTC", "ELK stack for logging")


def test_openai_requires_version_for_gpt(M):
    assert hit(M, "openai", "We fine-tune GPT-4o")
    assert hit(M, "openai", "ChatGPT plugins")
    assert not hit(M, "openai", "Disks use GPT partition tables")


def test_employer_detection(M):
    assert M["SNOW"].is_employer("Snowflake | SWE | San Mateo\nWe build...")
    assert not M["SNOW"].is_employer("Acme | Data Eng | Remote\nWe use Snowflake")
    assert post_header("Datadog (NYC) | SRE\nbody") == "Datadog (NYC)"


def test_customer_and_pedigree_context(M):
    assert not hit(M, "anthropic", "Our product is trusted by teams at Stripe, Anthropic, and OpenAI.")
    assert not hit(M, "mistralai", "Our customers include Mistral, Poolside and Meta.", "2025-01-01")
    assert not hit(M, "SNOW", "Founded by ex-Snowflake engineers.")
    assert not hit(M, "openai", "We are backed by YC and investors from OpenAI.")
    # a new sentence resets the context
    assert hit(M, "SNOW", "Trusted by 500 companies. Our stack: Snowflake, dbt.")
    assert hit(M, "anthropic", "Agents run on Anthropic Claude with OpenAI embeddings.")
    assert hit(M, "SNOW", "Stack: Postgres, Snowflake, Kafka")


def test_customers_word_alone_is_not_noise(M):
    assert hit(M, "SNOW", "We help customers migrate their warehouses to Snowflake")
