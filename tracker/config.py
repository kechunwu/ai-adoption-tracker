"""Load config/tracked.yaml and expose convenient lookups."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "tracked.yaml"
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"


@dataclass(frozen=True)
class Entity:
    id: str
    name: str
    kind: str  # ai_tool | public | private
    npm: tuple[str, ...] = ()
    pypi: tuple[str, ...] = ()
    github: tuple[str, ...] = ()
    hn: dict = field(default_factory=dict)
    ticker: str | None = None
    cik: int | None = None
    sec_name_contains: str | None = None
    fiscal_year_end: str | None = None
    private_reference: bool = False

    @property
    def is_public(self) -> bool:
        return self.kind == "public"


@lru_cache(maxsize=None)
def load_raw(path: str | None = None) -> dict:
    with open(path or CONFIG_PATH) as f:
        return yaml.safe_load(f)


def entities(path: str | None = None) -> list[Entity]:
    out = []
    for e in load_raw(path)["entities"]:
        out.append(
            Entity(
                id=e["id"],
                name=e["name"],
                kind=e["kind"],
                npm=tuple(e.get("npm", [])),
                pypi=tuple(e.get("pypi", [])),
                github=tuple(e.get("github", [])),
                hn=e.get("hn", {}) or {},
                ticker=e.get("ticker"),
                cik=e.get("cik"),
                sec_name_contains=e.get("sec_name_contains"),
                fiscal_year_end=e.get("fiscal_year_end"),
                private_reference=bool(e.get("private_reference", False)),
            )
        )
    return out


def entity_by_id(eid: str) -> Entity:
    for e in entities():
        if e.id == eid:
            return e
    raise KeyError(eid)


def public_companies() -> list[Entity]:
    return [e for e in entities() if e.is_public]


def package_map() -> dict[tuple[str, str], str]:
    """(registry, package) -> entity id."""
    m = {}
    for e in entities():
        for p in e.npm:
            m[("npm", p)] = e.id
        for p in e.pypi:
            m[("pypi", p)] = e.id
    return m


def analysis_settings() -> dict:
    return load_raw()["analysis"]


def hn_context_settings() -> dict:
    return load_raw()["hn_ai_context"]


def hn_noise_settings() -> dict:
    return load_raw().get("hn_noise_context", {"lookback": 0, "phrases": []})
