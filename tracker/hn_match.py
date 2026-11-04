"""Tool-mention matching for "Ask HN: Who is hiring?" job posts.

Pure functions only (no network) so every rule is unit-tested.

How false positives are handled (also documented in docs/METHODOLOGY.md):

1. Word boundaries, case-insensitive: ``\\bmongo(?:db)?\\b`` matches "MongoDB"
   and "mongo" but not "mongoose"; ``\\bconfluent\\b`` never matches
   "Confluence".
2. Exclusion phrases: a match is dropped if it lies inside an excluded phrase,
   e.g. "snowflake schema", "Snowflake IDs", "special snowflake",
   "Gemini exchange". Other mentions in the same post can still count.
3. Context gates for ambiguous names (Claude, Gemini, Mistral): the match only
   counts if the post is dated after the product's public launch AND either
   the word appears in a product form ("Claude Code", "Gemini API") or an
   AI-context word (LLM, model, prompt, agent, ...) occurs within N chars.
   This removes e.g. "email Claude at jobs@..." and the Gemini crypto exchange.
4. Deliberately omitted aliases: bare "Elastic" (AWS Elastic Beanstalk/IP/LB),
   bare "GPT" (GUID Partition Table), "transformers" (ambiguous),
   "AI SDK" (generic).
5. Customer / investor / pedigree context: "trusted by Snowflake, Anthropic",
   "customers include Mistral", "ex-Datadog engineers" describe the company as
   a customer or former employer, not as a tool in use. A mention is skipped if
   such a phrase occurs earlier in the same sentence (config `hn_noise_context`).
6. Employer vs. user: a post *by* the company (header "Snowflake | Senior
   Engineer | ...") is hiring, not adoption. We flag a match as
   ``is_employer`` when the employer alias appears in the post header's first
   ``|``-separated field. The default adoption share excludes those posts.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass

MATCHER_VERSION = 4  # bump when the code (not the config) changes behaviour

_TAG_RE = re.compile(r"<[^>]+>")
_P_RE = re.compile(r"<p>|<br\s*/?>", re.I)


def clean_html(text: str | None) -> str:
    """HN/Algolia comment HTML -> plain text, paragraphs become newlines."""
    if not text:
        return ""
    t = _P_RE.sub("\n", text)
    t = _TAG_RE.sub(" ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return t.strip()


def post_header(text: str) -> str:
    """The first ``|``-separated field of the first line (the employer name)."""
    first_line = text.split("\n", 1)[0]
    if "|" in first_line:
        return first_line.split("|", 1)[0].strip()
    return first_line[:80].strip()


def _alt(patterns: list[str]) -> str:
    return "|".join(f"(?:{p})" for p in patterns)


@dataclass
class EntityMatcher:
    entity_id: str
    alias_re: re.Pattern
    gated_re: re.Pattern | None
    exclude_re: re.Pattern | None
    employer_re: re.Pattern | None
    not_before: str | None
    context_re: re.Pattern
    product_re: re.Pattern
    window: int
    noise_re: re.Pattern | None = None
    lookback: int = 0

    def _noise_before(self, text: str, start: int) -> bool:
        if not self.noise_re or not self.lookback:
            return False
        left = text[max(0, start - self.lookback):start]
        # only the current sentence / line / list item
        cut = max(left.rfind(". "), left.rfind("\n"), left.rfind("! "), left.rfind("? "), left.rfind(" * "))
        if cut >= 0:
            left = left[cut + 1:]
        return bool(self.noise_re.search(left))

    def _excluded(self, text: str) -> list[tuple[int, int]]:
        if not self.exclude_re:
            return []
        return [m.span() for m in self.exclude_re.finditer(text)]

    def _has_context(self, text: str, start: int, end: int) -> bool:
        # product form starting at this match ("Claude Code", "Gemini API")
        if self.product_re.match(text, start):
            return True
        left = text[max(0, start - self.window):start]
        right = text[end:end + self.window]
        return bool(self.context_re.search(left) or self.context_re.search(right))

    def find(self, text: str, post_date: str | None = None) -> tuple[bool, str]:
        """Return (matched, snippet) for the first counting mention."""
        excluded = self._excluded(text)
        for m in self.alias_re.finditer(text):
            s, e = m.span()
            if any(a <= s and e <= b for a, b in excluded):
                continue
            if self._noise_before(text, s):
                continue
            if self.gated_re and self.gated_re.fullmatch(m.group(0)):
                if self.not_before and post_date and post_date < self.not_before:
                    continue
                if not self._has_context(text, s, e):
                    continue
            snippet = text[max(0, s - 60): e + 60].replace("\n", " ")
            return True, snippet
        return False, ""

    def is_employer(self, text: str) -> bool:
        if not self.employer_re:
            return False
        return bool(self.employer_re.search(post_header(text)))


def build_matchers(entities, context_cfg: dict, noise_cfg: dict | None = None) -> list[EntityMatcher]:
    if noise_cfg is None:
        from tracker.config import hn_noise_settings
        noise_cfg = hn_noise_settings()
    noise_re = re.compile(rf"(?:^|\b|(?<=\W))(?:{_alt(noise_cfg['phrases'])})", re.I) if noise_cfg.get("phrases") else None
    ctx_re = re.compile(rf"\b(?:{_alt(context_cfg['words'])})\b", re.I)
    prod_re = re.compile(_alt(context_cfg["product_forms"]), re.I)
    out = []
    for e in entities:
        hn = e.hn or {}
        if not hn.get("aliases"):
            continue
        gated = hn.get("context_gated") or []
        out.append(
            EntityMatcher(
                entity_id=e.id,
                alias_re=re.compile(rf"\b(?:{_alt(hn['aliases'])})\b", re.I),
                gated_re=re.compile(_alt(gated), re.I) if gated else None,
                exclude_re=re.compile(rf"\b(?:{_alt(hn['exclude'])})", re.I) if hn.get("exclude") else None,
                employer_re=re.compile(rf"\b(?:{_alt(hn['employer_aliases'])})\b", re.I)
                if hn.get("employer_aliases") else None,
                not_before=hn.get("not_before"),
                context_re=ctx_re,
                product_re=prod_re,
                window=int(context_cfg.get("context_window", 100)),
                noise_re=noise_re,
                lookback=int(noise_cfg.get("lookback", 0)),
            )
        )
    return out


def rules_hash(entities, context_cfg: dict) -> str:
    from tracker.config import hn_noise_settings

    payload = {
        "v": MATCHER_VERSION,
        "noise": hn_noise_settings(),
        "hn": {e.id: e.hn for e in entities if e.hn},
        "ctx": context_cfg,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


def match_post(matchers: list[EntityMatcher], raw_html: str, post_date: str | None) -> list[dict]:
    text = clean_html(raw_html)
    hits = []
    for m in matchers:
        ok, snippet = m.find(text, post_date)
        if ok:
            hits.append({"entity": m.entity_id, "is_employer": m.is_employer(text), "snippet": snippet[:240]})
    return hits
