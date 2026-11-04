"""Build the static GitHub Pages site from the committed data files.

    python -m site_builder.build_site            # writes _site/
    python -m http.server -d _site 8000          # preview locally

Every number on the site is computed here from data/processed + data/raw, so the
site is rebuilt from scratch on each weekly run (no hand-edited figures).
"""
from __future__ import annotations

import datetime as dt
import html
import json
import shutil
from pathlib import Path

import markdown
import numpy as np
import pandas as pd
import plotly
import plotly.graph_objects as go
from jinja2 import Environment, FileSystemLoader, select_autoescape

from tracker.analysis.findings import classify
from tracker.build import mark_missing, outage_days
from tracker.config import DATA, PROCESSED, RAW, ROOT, entities, known_breaks

OUT = ROOT / "_site"
HERE = Path(__file__).resolve().parent
PORTFOLIO = "https://kechunwu.github.io"
REPO = "https://github.com/kechunwu/ai-adoption-tracker"
BLOB = f"{REPO}/blob/main"

# Validated categorical palette (fixed order; color follows the entity, never rank)
PAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
REG_COLOR = {"npm": PAL[0], "pypi": PAL[1]}
VENDORS = {"openai": "OpenAI", "anthropic": "Anthropic", "google-genai": "Google Gen AI", "mistralai": "Mistral"}
VENDOR_COLOR = {"openai": PAL[0], "anthropic": PAL[1], "google-genai": PAL[2], "mistralai": PAL[3]}
INK, INK2, GRID, NEUTRAL = "#0b0b0b", "#52514e", "#e6e5e0", "#8a8984"
SIG = {"hn": "HN hiring-post share", "npm": "npm downloads", "pypi": "PyPI downloads",
       "npm_rel": "npm vs baseline", "pypi_rel": "PyPI vs baseline"}
POST_HOC = {"npm_rel", "pypi_rel"}
NAV = [("index.html", "Overview"), ("trends.html", "Tool trends"), ("ai-sdk.html", "AI SDK share"),
       ("lead-lag.html", "Lead/lag study"), ("methodology.html", "Methodology")]
PUBLIC_NAMES = {e.ticker: e.name for e in entities() if e.ticker}


# ------------------------------------------------------------------ utils --
def csv(path: Path, dates=()) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    for d in dates:
        if d in df:
            df[d] = pd.to_datetime(df[d])
    return df


def layout(fig: go.Figure, title=None, yfmt=None, height=360, legend=True) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", font=dict(size=14, color=INK)) if title else None,
        height=height, margin=dict(l=8, r=8, t=44 if title else 16, b=8),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="-apple-system, Segoe UI, Inter, Roboto, Arial, sans-serif", color=INK2, size=12),
        hovermode="x unified", showlegend=legend,
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0, title=None, font=dict(size=11)),
        hoverlabel=dict(bgcolor="white", font_size=12),
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, ticks="outside", tickcolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickformat=yfmt)
    return fig


def mark_breaks(fig: go.Figure, registries) -> go.Figure:
    """Dashed vertical line at known registry-wide counting breaks."""
    for b in known_breaks():
        if b["registry"] in registries:
            fig.add_vline(x=pd.Timestamp(b["date"]).timestamp() * 1000, line=dict(color=NEUTRAL, width=1, dash="dash"))
            fig.add_annotation(x=pd.Timestamp(b["date"]), y=1, yref="paper", text=f"{b['registry']} counting change",
                               showarrow=False, xanchor="right", yanchor="top", font=dict(size=10, color=NEUTRAL))
    return fig


def fig_json(fig: go.Figure | None):
    if fig is None:
        return None
    return json.loads(json.dumps(fig.to_plotly_json(), cls=plotly.utils.PlotlyJSONEncoder))


def pct(v, digits=1, signed=True):
    if v is None or pd.isna(v):
        return "–"
    return f"{v:+.{digits}%}" if signed else f"{v:.{digits}%}"


def num(v):
    if v is None or pd.isna(v):
        return "–"
    v = float(v)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(v) >= div:
            return f"{v / div:.1f}{suf}"
    return f"{v:.0f}"


def td(v, kind="pct", digits=1, cls_sign=True):
    """Table cell with a numeric sort key."""
    if v is None or pd.isna(v):
        return '<td class="muted" data-sort="NaN">–</td>'
    if kind == "pct":
        txt = pct(v, digits)
        cls = (" pos" if v > 0 else " neg" if v < 0 else "") if cls_sign else ""
    elif kind == "share":
        txt, cls = pct(v, digits, signed=False), ""
    elif kind == "num":
        txt, cls = num(v), ""
    elif kind == "r":
        txt, cls = f"{v:+.2f}", ""
    elif kind == "p":
        txt, cls = (f"{v:.3f}" if v >= 0.001 else "<0.001"), ""
    else:
        txt, cls = str(v), ""
    return f'<td class="{cls.strip()}" data-sort="{float(v)}">{txt}</td>'


def table(headers, rows, tid=None, sortable=True, left_cols=1) -> str:
    ths = "".join(f'<th class="{"l" if i < left_cols else ""}">{h}</th>' for i, h in enumerate(headers))
    cls = "data sortable" if sortable else "data"
    idattr = f' id="{tid}"' if tid else ""
    return f'<table class="{cls}"{idattr}><thead><tr>{ths}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def tdl(text):
    return f'<td class="l">{text}</td>'


# ------------------------------------------------------------------ data --
class Data:
    def __init__(self):
        self.moved = csv(PROCESSED / "what_moved.csv")
        self.weekly = csv(PROCESSED / "downloads_weekly.csv", ["week"])
        self.ew = csv(PROCESSED / "entity_weekly.csv", ["week"])
        self.hn = csv(PROCESSED / "hn_share.csv")
        if not self.hn.empty:
            self.hn["month_dt"] = pd.to_datetime(self.hn["month"] + "-01")
        self.gh = csv(RAW / "github_snapshots.csv", ["snapshot_date"])
        self.rev = csv(PROCESSED / "revenue_quarterly.csv", ["period_end"])
        self.facts = csv(RAW / "sec_revenue_facts.csv")
        self.panel = csv(PROCESSED / "quarterly_panel.csv", ["period_end"])
        self.company = csv(PROCESSED / "leadlag_company.csv")
        self.pooled = csv(PROCESSED / "leadlag_pooled.csv")
        s = PROCESSED / "leadlag_summary.json"
        self.summ = json.loads(s.read_text()) if s.exists() else {}
        m = RAW / "hn_matches.parquet"
        self.matches = pd.read_parquet(m) if m.exists() else pd.DataFrame()
        self.threads = csv(RAW / "hn_threads.csv")
        self.pypi = csv(RAW / "pypi_daily.csv")
        npm = csv(RAW / "npm_daily.csv", ["date"])
        self.outages = outage_days(mark_missing(npm)) if not npm.empty else []
        log = DATA / "run_log.json"
        self.run_log = json.loads(log.read_text()) if log.exists() else {}
        sm = PROCESSED / "summary.md"
        self.summary_md = sm.read_text() if sm.exists() else None

    def asof(self) -> dict:
        week = self.moved["week"].max() if not self.moved.empty else None
        label = pd.Timestamp(week).strftime("%b %-d, %Y") if week else "n/a"
        parts = []
        if week:
            parts.append(f"downloads through the week ending {week}")
        if not self.threads.empty:
            parts.append(f"HN hiring threads through {pd.Timestamp(self.threads['month'].max() + '-01'):%b %Y}")
        if not self.facts.empty:
            parts.append(f"SEC filings through {self.facts['filed'].max()}")
        if self.run_log.get("finished"):
            parts.append(f"pipeline run {self.run_log['finished'].replace('T', ' ')[:16]} UTC")
        return {"label": label, "detail": "; ".join(parts)}


# --------------------------------------------------------------- overview --
def page_index(d: Data) -> dict:
    ents = [e for e in entities() if e.kind != "control"]
    n_pk = len({p for e in ents for p in e.npm}) + len({p for e in ents for p in e.pypi})
    s = d.summ
    kpis = [
        {"label": "Tools & companies tracked", "value": len(ents), "sub": f"{n_pk} npm + PyPI packages"},
        {"label": "HN hiring threads parsed", "value": f"{len(d.threads)}",
         "sub": f"{int(d.threads['n_posts'].sum()):,} job posts since 2016" if not d.threads.empty else ""},
        {"label": "Revenue quarters (SEC)", "value": f"{len(d.rev)}", "sub": "6 public companies, from 10-K/10-Q XBRL"},
        {"label": "Lead/lag tests with p < 0.05", "value": f"{s.get('company_tests_p_lt_05', 0)} / {s.get('company_tests_run', 0)}",
         "sub": f"≈{s.get('expected_false_positives_at_05', 0)} expected by chance"},
    ]
    names = {e.id: e.name for e in entities()}
    rows = []
    m = d.moved
    for r in m.itertuples():
        rows.append("<tr>" + tdl(html.escape(names.get(r.entity, r.entity))) + tdl(r.registry) + tdl(f"<code>{html.escape(r.package)}</code>")
                    + td(r.downloads, "num") + td(r.wow) + td(r.vs_prior4) + td(r.yoy_4wk, digits=0)
                    + td(getattr(r, "yoy_vs_baseline", np.nan), digits=0)
                    + td(getattr(r, "hn_share", np.nan), "share", 2) + "</tr>")
    moved_table = table(["Tool", "Reg.", "Package", "Last wk", "WoW", "vs 4 wks", "YoY", "YoY vs base", "HN share"],
                        rows, tid="moved", left_cols=3)
    note = None
    if not m.empty:
        npm_blank = m[(m["registry"] == "npm") & m["wow"].isna()]
        if len(npm_blank) > 0.5 * (m["registry"] == "npm").sum():
            note = ("npm week-over-week columns are blank this week: npm's API reported zeros for every package on several days of the "
                    "preceding weeks (a registry-side outage), so there is no clean prior week to compare against. The 4-week average and "
                    "YoY use same-weekday fills for those days.")
    summary = None
    if d.summary_md:
        body = d.summary_md.split("-->", 1)[-1]
        summary = markdown.markdown(body)
    return {"kpis": kpis, "moved_table": moved_table, "summary": summary, "moved_note": note,
            "week": m["week"].max() if not m.empty else "n/a", "n_outage": len(d.outages)}


# ----------------------------------------------------------------- trends --
def trends_bundles(d: Data, out: Path) -> list:
    groups = {"ai_tool": "AI tools", "public": "Public data-infra companies", "private": "Private references"}
    listing = {g: [] for g in groups}
    out.mkdir(parents=True, exist_ok=True)
    for e in entities():
        if e.kind not in groups:
            continue
        label = f"{e.name} ({e.ticker})" if e.ticker else e.name
        listing[e.kind].append({"id": e.id, "label": label})
        figs = {}
        sub = d.ew[(d.ew["entity"] == e.id)] if not d.ew.empty else d.ew
        if not sub.empty:
            f = go.Figure()
            for reg, g in sub.groupby("registry"):
                g = g.sort_values("week")
                f.add_scatter(x=g["week"], y=g["downloads"].round(0), name=f"{reg} weekly", mode="lines",
                              line=dict(width=1, color=REG_COLOR[reg]), opacity=0.35, hovertemplate="%{y:,.0f}")
                f.add_scatter(x=g["week"], y=g["ma4"].round(0), name=f"{reg} 4-wk avg", mode="lines",
                              line=dict(width=2, color=REG_COLOR[reg]), hovertemplate="%{y:,.0f}")
            mark_breaks(f, set(sub["registry"]))
            figs["downloads"] = fig_json(layout(f, "Weekly downloads (thin: week, bold: 4-week average)", "~s"))
            f = go.Figure()
            for reg, g in sub.groupby("registry"):
                g = g.sort_values("week").dropna(subset=["yoy"])
                if g.empty:
                    continue
                f.add_scatter(x=g["week"], y=g["yoy"].round(4), name=f"{reg} YoY", mode="lines",
                              line=dict(width=2, color=REG_COLOR[reg]), hovertemplate="%{y:+.0%}")
                if "yoy_rel" in g and g["yoy_rel"].notna().any():
                    f.add_scatter(x=g["week"], y=g["yoy_rel"].round(4), name=f"{reg} vs baseline", mode="lines",
                                  line=dict(width=2, color=REG_COLOR[reg], dash="dot"), hovertemplate="%{y:+.0%}")
            if f.data:
                f.add_hline(y=0, line=dict(color=NEUTRAL, width=1))
                lay = layout(f, "YoY growth of 4-week average downloads (last 3 years; zoom out for all)", "+.0%")
                end = sub["week"].max()
                start = end - pd.DateOffset(years=3)
                recent = sub[sub["week"] >= start]
                vals = pd.concat([recent["yoy"], recent.get("yoy_rel", pd.Series(dtype=float))]).to_numpy(dtype=float)
                vals = vals[np.isfinite(vals)]
                if len(vals):  # early hyper-growth makes a linear axis unreadable: frame the recent years
                    lo, hi = max(-1.0, np.nanmin(vals)), np.nanmax(vals)
                    pad = (hi - lo) * 0.08 + 0.02
                    lay.update_xaxes(range=[start, end + pd.Timedelta(days=7)])
                    lay.update_yaxes(range=[lo - pad, hi + pad])
                figs["yoy"] = fig_json(lay)
        h = d.hn[d.hn["entity"] == e.id] if not d.hn.empty else d.hn
        hn_note, samples = "", ""
        if not h.empty:
            f = go.Figure()
            f.add_bar(x=h["month_dt"], y=h["share_ex_employer"].round(5), name="monthly", marker_color="#b7d3f6",
                      hovertemplate="%{y:.2%}")
            f.add_scatter(x=h["month_dt"], y=h["share_3m"].round(5), name="3-month average", mode="lines",
                          line=dict(width=2, color=PAL[0]), hovertemplate="%{y:.2%}")
            figs["hn"] = fig_json(layout(f, "Share of ‘Ask HN: Who is hiring?’ posts mentioning it (excl. its own posts)", ".1%"))
            last = h.sort_values("month").iloc[-1]
            hn_note = (f"{last['month']}: {int(last['mentions_ex_employer'])} of {int(last['total_posts'])} job posts "
                       f"({last['share_ex_employer']:.2%}). Posts by {html.escape(e.name)} itself that month: {int(last['employer_posts'])} (excluded).")
            if not d.matches.empty:
                mm = d.matches[(d.matches["entity"] == e.id) & (~d.matches["is_employer"].astype(bool))]
                mm = mm.sort_values(["month", "post_id"], ascending=False).head(12)
                rows = [f'<tr><td class="l">{r.month}</td><td class="l" style="white-space:normal">…{html.escape(r.snippet)}…</td>'
                        f'<td class="l"><a href="https://news.ycombinator.com/item?id={r.post_id}">post</a></td></tr>'
                        for r in mm.itertuples()]
                samples = table(["Month", "Snippet", "Link"], rows, sortable=False, left_cols=3)
        gh_table = ""
        if not d.gh.empty and e.github:
            g = d.gh[d.gh["repo"].isin(e.github)].sort_values("snapshot_date")
            if not g.empty:
                latest = g.groupby("repo").tail(1)
                rows = ["<tr>" + tdl(f'<a href="https://github.com/{r.repo}">{r.repo}</a>') + td(r.stars, "num") + td(r.forks, "num")
                        + td(r.contributors, "num") + td(r.releases, "num") + tdl(html.escape(str(r.latest_release or "–")))
                        + tdl(str(r.snapshot_date.date())) + "</tr>" for r in latest.itertuples()]
                gh_table = '<div class="tablewrap">' + table(["Repo", "Stars", "Forks", "Contributors", "Releases", "Latest release", "Snapshot"],
                                                             rows, left_cols=1) + "</div>"
                if g["snapshot_date"].nunique() >= 3:
                    f = go.Figure()
                    for i, (repo, rr) in enumerate(g.groupby("repo")):
                        f.add_scatter(x=rr["snapshot_date"], y=rr["stars"], name=repo, mode="lines+markers",
                                      line=dict(width=2, color=PAL[i % 8]), marker=dict(size=8))
                    figs["stars"] = fig_json(layout(f, "GitHub stars (weekly snapshots)", "~s"))
        proxies = " · ".join([f"npm <code>{p}</code>" for p in e.npm] + [f"PyPI <code>{p}</code>" for p in e.pypi]) or "No package proxy."
        proxies += f' · <a href="{BLOB}/config/tracked.yaml">why these proxies</a>'
        bundle = {"figs": figs, "proxies": proxies, "hn_note": hn_note, "hn_samples": samples, "gh_table": gh_table}
        (out / f"{e.id}.json").write_text(json.dumps(bundle, separators=(",", ":")))
    return [(groups[k], v) for k, v in listing.items() if v]


# ----------------------------------------------------------------- AI SDK --
def page_ai_sdk(d: Data) -> tuple[dict, dict]:
    figs, tables, notes = {}, {}, {}
    for reg in ("npm", "pypi"):
        sub = d.ew[(d.ew["registry"] == reg) & d.ew["entity"].isin(VENDORS)].dropna(subset=["ma4"])
        start = "2023-01-01" if reg == "npm" else "2000-01-01"
        sub = sub[sub["week"] >= start]
        if sub.empty:
            continue
        wide = sub.pivot_table(index="week", columns="entity", values="ma4").sort_index()
        wide = wide.dropna(how="all")
        share = wide.div(wide.sum(axis=1), axis=0)
        f = go.Figure()
        for e in [v for v in VENDORS if v in share]:
            f.add_scatter(x=share.index, y=share[e].round(4), name=VENDORS[e], mode="lines", stackgroup="one",
                          line=dict(width=0.5, color="#ffffff"), fillcolor=VENDOR_COLOR[e], hovertemplate="%{y:.1%}")
        lay = layout(f, f"Share of combined official-SDK downloads ({'npm' if reg == 'npm' else 'PyPI'}, 4-week average)", ".0%", 440)
        lay.update_yaxes(range=[0, 1])
        figs[f"share_{reg}"] = fig_json(lay)
        f = go.Figure()
        for e in [v for v in VENDORS if v in wide]:
            f.add_scatter(x=wide.index, y=wide[e].round(0), name=VENDORS[e], mode="lines",
                          line=dict(width=2, color=VENDOR_COLOR[e]), hovertemplate="%{y:,.0f}")
        mark_breaks(f, {reg})
        lay = layout(f, "Weekly downloads, 4-week average", "~s")
        lay.update_yaxes(type="log")
        lay.update_layout(updatemenus=[dict(type="buttons", direction="right", x=0, y=1.0, xanchor="left", yanchor="bottom",
                                            pad=dict(t=0, b=0), showactive=True, bgcolor="white", bordercolor=GRID,
                                            buttons=[dict(label="log", method="relayout", args=[{"yaxis.type": "log"}]),
                                                     dict(label="linear", method="relayout", args=[{"yaxis.type": "linear"}])])],
                          title=dict(y=0.97), margin=dict(t=70))
        figs[f"abs_{reg}"] = fig_json(lay)
        latest = share.iloc[-1]
        ago = share[share.index <= share.index[-1] - pd.Timedelta(weeks=52)]
        rows = []
        for e in [v for v in VENDORS if v in share]:
            prev = ago[e].iloc[-1] if not ago.empty else np.nan
            rows.append("<tr>" + tdl(VENDORS[e]) + td(latest[e], "share") + td(prev, "share")
                        + (f'<td data-sort="{(latest[e] - prev) * 100}">{(latest[e] - prev) * 100:+.1f} pp</td>' if pd.notna(prev) else '<td>–</td>')
                        + "</tr>")
        tables[reg] = table(["SDK", "Now", "1 year earlier", "Change"], rows, left_cols=1)
        notes[reg] = (f"Week ending {share.index[-1].date()}. " +
                      ("PyPI history is still short (pypistats keeps ~180 days), so the 1-year comparison appears once a year has accrued." if ago.empty else ""))
    h = d.hn[d.hn["entity"].isin(VENDORS) & (d.hn["month_dt"] >= "2022-01-01")] if not d.hn.empty else d.hn
    if not h.empty:
        f = go.Figure()
        for e in [v for v in VENDORS if v in set(h["entity"])]:
            g = h[h["entity"] == e]
            f.add_scatter(x=g["month_dt"], y=g["share_3m"].round(5), name=VENDORS[e], mode="lines",
                          line=dict(width=2, color=VENDOR_COLOR[e]), hovertemplate="%{y:.2%}")
        figs["hn_vendors"] = fig_json(layout(f, "Share of HN job posts mentioning each provider (3-month average)", ".1%"))
    return {"share_tables": tables, "share_notes": notes}, figs


# ---------------------------------------------------------------- lead/lag --
def _pooled_fig(p: pd.DataFrame, sig: str) -> go.Figure:
    f = go.Figure()
    for i, fe in enumerate(["company", "company+time"]):
        g = p[(p["signal"] == sig) & (p["spec"] == "yoy") & (p["fe"] == fe)].dropna(subset=["r"])
        if g.empty:
            continue
        off = -0.1 if i == 0 else 0.1
        f.add_scatter(x=g["lag"] + off, y=g["r"].round(3), mode="markers",
                      name={"company": "company FE", "company+time": "company + quarter FE"}[fe],
                      marker=dict(size=10, color=PAL[i], line=dict(color="#ffffff", width=2)),
                      error_y=dict(type="data", symmetric=False, array=(g["ci_hi"] - g["r"]).round(3),
                                   arrayminus=(g["r"] - g["ci_lo"]).round(3), color=PAL[i], thickness=2, width=4),
                      customdata=np.c_[g["n"], g["p"].round(4), g["p_lag_adj"].round(4)],
                      hovertemplate="lag %{x:.0f}: r = %{y:+.2f}<br>n = %{customdata[0]:.0f}, p = %{customdata[1]:.3f}, "
                                    "lag-adjusted p = %{customdata[2]:.3f}<extra></extra>")
    f.add_hline(y=0, line=dict(color=NEUTRAL, width=1))
    tag = " (post-hoc)" if sig in POST_HOC else ""
    lay = layout(f, f"{SIG[sig]}{tag} → revenue", ".1f", 340)
    lay.update_xaxes(title="lag k (quarters the signal leads)", tickvals=[0, 1, 2, 3, 4], range=[-0.5, 4.5])
    lay.update_yaxes(range=[-1, 1], title="correlation r")
    lay.update_layout(hovermode="closest", legend=dict(y=-0.3), height=370, margin=dict(b=20))
    return lay


def _heat_fig(c: pd.DataFrame, sig: str) -> go.Figure | None:
    c = c[(c["signal"] == sig) & (c["spec"] == "yoy")]
    if c["r"].notna().sum() == 0:
        return None
    hm = c.pivot(index="ticker", columns="lag", values="r")
    pp = c.pivot(index="ticker", columns="lag", values="p")
    nn = c.pivot(index="ticker", columns="lag", values="n")
    txt = [[("" if pd.isna(hm.iloc[i, j]) else f"{hm.iloc[i, j]:+.2f}" + ("*" if pp.iloc[i, j] < 0.05 else ""))
            if not pd.isna(hm.iloc[i, j]) else f"n={int(nn.iloc[i, j])}" for j in range(hm.shape[1])] for i in range(hm.shape[0])]
    f = go.Figure(go.Heatmap(
        z=hm.values.round(3), x=[f"lag {k}" for k in hm.columns], y=list(hm.index), zmin=-1, zmax=1,
        colorscale=[[0, "#e34948"], [0.5, "#f4f3ef"], [1, "#2a78d6"]], text=txt, texttemplate="%{text}",
        customdata=np.dstack([nn.values, pp.values.round(4)]), xgap=3, ygap=3,
        hovertemplate="%{y} %{x}: r = %{z:.2f}<br>n = %{customdata[0]:.0f}, p = %{customdata[1]:.3f}<extra></extra>",
        colorbar=dict(title="r", thickness=10)))
    tag = " (post-hoc)" if sig in POST_HOC else ""
    lay = layout(f, f"r by company and lag: {SIG[sig]}{tag} → revenue (YoY growth)", None, 330, legend=False)
    lay.update_layout(hovermode="closest")
    lay.update_yaxes(autorange="reversed")
    return lay


def _raw_fig(panel: pd.DataFrame, t: str) -> go.Figure:
    g = panel[panel["ticker"] == t].sort_values("period_end")
    f = go.Figure()
    f.add_scatter(x=g["period_end"], y=g["rev_yoy"].round(4), name="revenue", mode="lines+markers",
                  line=dict(width=3, color=INK), marker=dict(size=8))
    for i, s in enumerate(["hn", "npm", "npm_rel"]):
        col = f"{s}_yoy"
        if col in g and g[col].notna().any():
            f.add_scatter(x=g["period_end"], y=g[col].round(4), name=SIG[s] + (" (post-hoc)" if s in POST_HOC else ""),
                          mode="lines+markers", line=dict(width=2, color=PAL[i], dash="dot" if s in POST_HOC else None),
                          marker=dict(size=7))
    f.add_hline(y=0, line=dict(color=NEUTRAL, width=1))
    lay = layout(f, f"{PUBLIC_NAMES.get(t, t)} ({t}): log YoY growth by fiscal quarter", ".1f", 420)
    vals = np.concatenate([np.asarray(tr.y, dtype=float) for tr in f.data])
    vals = vals[np.isfinite(vals)]
    if len(vals):  # first-year package growth can be log 5+; frame the range where revenue lives
        lo, hi = max(np.nanmin(vals), -1.0), min(np.nanmax(vals), 2.5)
        lay.update_yaxes(range=[lo - 0.1, hi + 0.1])
        if np.nanmax(vals) > 2.5:
            lay.add_annotation(text="some early signal values above 2.5 are off-scale (zoom out to see)", xref="paper",
                               yref="paper", x=0, y=1.0, xanchor="left", yanchor="bottom", showarrow=False,
                               font=dict(size=11, color=NEUTRAL))
    return lay


def _fmt_cell(r) -> str:
    if pd.isna(r["r"]):
        return f'<td class="muted">n={int(r["n"])}</td>'
    star = "*" if r["p"] < 0.05 else ""
    return (f'<td data-sort="{r["r"]}" title="95% CI [{r["ci_lo"]:+.2f}, {r["ci_hi"]:+.2f}], p={r["p"]:.3f}, lag-adj p={r["p_lag_adj"]:.3f}, n={int(r["n"])}">'
            f'{r["r"]:+.2f}{star}<br><span class="note">[{r["ci_lo"]:+.2f}, {r["ci_hi"]:+.2f}]</span></td>')


def page_leadlag(d: Data) -> tuple[dict, dict]:
    figs = {}
    c, p, panel = d.company, d.pooled, d.panel
    sigs_avail = [s for s in SIG if not p.empty and p[(p["signal"] == s) & p["r"].notna()].shape[0] > 0]
    for s in sigs_avail:
        figs[f"pooled_{s}"] = fig_json(_pooled_fig(p, s))
    heat_sigs = []
    for s in SIG:
        f = _heat_fig(c, s) if not c.empty else None
        if f is not None:
            figs[f"heat_{s}"] = fig_json(f)
            heat_sigs.append((s, SIG[s] + (" (post-hoc)" if s in POST_HOC else "")))
    tickers = sorted(panel["ticker"].unique()) if not panel.empty else []
    for t in tickers:
        figs[f"raw_{t}"] = fig_json(_raw_fig(panel, t))

    # data table
    rows = []
    for e in [e for e in entities() if e.is_public]:
        r = d.rev[d.rev["ticker"] == e.ticker]
        pn = panel[panel["ticker"] == e.ticker]
        rows.append("<tr>" + tdl(f"{e.name} ({e.ticker})") + tdl(e.fiscal_year_end or "") +
                    tdl(f"{r['period_end'].min():%Y-%m} → {r['period_end'].max():%Y-%m}" if not r.empty else "–") +
                    f'<td>{len(r)}</td><td>{int(pn["rev_yoy"].notna().sum())}</td><td>{int(pn["hn_yoy"].notna().sum())}</td>'
                    f'<td>{int(pn["npm_yoy"].notna().sum())}</td>' +
                    tdl(", ".join(f"<code>{x}</code>" for x in e.npm) or "–") + "</tr>")
    data_table = table(["Company", "FY ends", "Revenue quarters", "# quarters", "# revenue YoY", "# HN YoY", "# npm YoY", "npm proxy"],
                       rows, sortable=False, left_cols=3)

    # verdict table: every lag for every signal x FE (primary spec)
    vrows = []
    for s in sigs_avail:
        verdict, _ = classify(p, s)
        vtag = {"null": "null", "supported": "supported", "mixed/weak": "mixed"}.get(verdict, "")
        for fe in ("company", "company+time"):
            g = p[(p["signal"] == s) & (p["spec"] == "yoy") & (p["fe"] == fe)].set_index("lag")
            cells = "".join(_fmt_cell(g.loc[k]) if k in g.index else "<td>–</td>" for k in range(5))
            lab = SIG[s] + (' <span class="tag">post-hoc</span>' if s in POST_HOC else "")
            vrows.append("<tr>" + tdl(lab) + tdl("company" if fe == "company" else "company + quarter") + cells +
                         tdl(f'<span class="tag {vtag}">{verdict}</span>' if fe == "company" else "") + "</tr>")
    verdict_table = table(["Signal", "Fixed effects", "lag 0", "lag 1", "lag 2", "lag 3", "lag 4", "Verdict"], vrows,
                          sortable=False, left_cols=2)

    # narrative pieces (all computed)
    tldr, s = [], d.summ
    for sig in [x for x in ("hn", "npm", "pypi", "npm_rel") if x in SIG]:
        v, desc = classify(p, sig) if not p.empty else ("untestable", "")
        if v == "untestable":
            if sig in ("hn", "npm", "pypi"):
                tldr.append(f"<strong>{SIG[sig]}:</strong> not testable yet ({desc}).")
            continue
        g = p[(p["signal"] == sig) & (p["spec"] == "yoy") & p["r"].notna()]
        n_sig = int((g["p"] < 0.05).sum())
        lead = g[g["lag"] >= 1]
        pos_lead = int(((lead["r"] > 0) & (lead["ci_lo"] > 0)).sum())
        lab = f"{SIG[sig]}{' (post-hoc)' if sig in POST_HOC else ''}"
        verdict_word = {"null": "<strong>No detectable lead.</strong>", "mixed/weak": "<strong>Weak / inconsistent evidence.</strong>",
                        "supported": "<strong>Evidence of a lead.</strong>"}[v]
        tldr.append(f"<strong>{lab}:</strong> {verdict_word} {n_sig} of {len(g)} pooled lag × fixed-effect cells have p &lt; 0.05; "
                    f"{pos_lead} of {len(lead)} leading cells (k ≥ 1) have a 95% CI entirely above zero. "
                    f"<span class='note'>({html.escape(desc)})</span>")
    tldr.append(f"<strong>Company by company:</strong> {s.get('company_tests_p_lt_05', 0)} of {s.get('company_tests_run', 0)} pre-registered tests have "
                f"p &lt; 0.05, against ≈{s.get('expected_false_positives_at_05', 0)} expected from chance alone; "
                f"{s.get('company_tests_q_lt_10', 0)} survive a false-discovery-rate correction.")
    tldr.append('<a href="#interpretation">What it means: the interpretation (section 4.5) →</a>')
    tldr.append("PyPI downloads cannot be tested yet (only ~180 days of history), and every result rests on 6 companies with "
                "short, smooth series. Treat the verdicts as “what this data can detect”, not as proof either way.")

    # company text: survivors of lag adjustment and FDR
    pre = c[(c["spec"] == "yoy") & c["r"].notna() & ~c["post_hoc"].astype(bool)] if not c.empty else c
    surv = pre[pre["p_lag_adj"] < 0.05] if not pre.empty else pre
    fdr = pre[pre["q_bh"] < 0.10] if not pre.empty else pre
    if pre.empty:
        company_text = "No company-level tests could be run yet."
    else:
        frac_pos = (pre["r"] > 0).mean()
        lead_pos = (pre[pre["lag"] >= 1]["r"] > 0).mean()
        surv_txt = ", ".join(f"{r.ticker} {SIG[r.signal]} lag {r.lag} (r = {r.r:+.2f})" for r in surv.itertuples()) or "none"
        company_text = (f"<strong>Survive the lag adjustment (Bonferroni over 5 lags, p &lt; 0.05):</strong> {surv_txt}. "
                        f"<strong>Survive false-discovery-rate control (q &lt; 0.10):</strong> {len(fdr)} of {len(pre)}. "
                        f"Positive correlations: {frac_pos:.0%} of all cells and {lead_pos:.0%} of leading cells (k ≥ 1); about 50% is expected "
                        f"if there is no relationship, but the cells are not independent (same company, adjacent lags), so this is descriptive only.")
    # robustness (acceleration)
    pr = p[(p["spec"] == "d_yoy") & p["r"].notna() & ~p["post_hoc"].astype(bool)] if not p.empty else p
    if pr.empty:
        robust_text = "Not enough data for the acceleration specification."
    else:
        best = pr.loc[pr["p"].idxmin()]
        robust_text = (f"Using the quarter-on-quarter <em>change</em> in YoY growth (acceleration) on both sides strips out slow shared trends. "
                       f"In the pooled panel, {int((pr['p'] < 0.05).sum())} of {len(pr)} cells have p &lt; 0.05 and "
                       f"{int((pr['p_lag_adj'] < 0.05).sum())} survive the lag adjustment. Strongest cell: {SIG[best['signal']]}, lag {int(best['lag'])}, "
                       f"{best['fe']} FE, r = {best['r']:+.2f} [{best['ci_lo']:+.2f}, {best['ci_hi']:+.2f}], p = {best['p']:.3f}.")

    # all-tests table
    rows = []
    if not c.empty:
        for r in c.sort_values(["post_hoc", "signal", "spec", "ticker", "lag"]).itertuples():
            rows.append("<tr>" + tdl(r.ticker) + tdl(SIG.get(r.signal, r.signal) + (" (post-hoc)" if r.post_hoc else "")) + tdl(r.spec) +
                        f"<td>{r.lag}</td><td>{int(r.n)}</td>" + td(r.n_eff, "num") + td(r.r, "r") + td(r.ci_lo, "r") + td(r.ci_hi, "r") +
                        td(r.p, "p") + td(r.p_lag_adj, "p") + td(r.q_bh, "p") + td(r.p_perm, "p") + "</tr>")
    all_table = table(["Ticker", "Signal", "Spec", "Lag", "n", "n_eff", "r", "CI low", "CI high", "p", "p (lag-adj)", "q (BH)", "p (perm)"],
                      rows, tid="alltests", left_cols=3)
    ip = ROOT / "docs" / "lead_lag_interpretation.md"
    interpretation = markdown.markdown(ip.read_text()) if ip.exists() else ""
    ctx = {"interpretation": interpretation, "pooled_sigs": [x for x in sigs_avail if x not in ("pypi_rel",)], "heat_sigs": heat_sigs, "tickers": tickers,
           "data_table": data_table, "verdict_table": verdict_table, "tldr": tldr, "company_text": company_text,
           "robust_text": robust_text, "all_table": all_table, "n_tests": len(c), "summ": s}
    return ctx, figs


# ------------------------------------------------------------ methodology --
def page_methodology(d: Data) -> dict:
    md = (ROOT / "docs" / "METHODOLOGY.md").read_text()
    md = md.replace("](../", f"]({BLOB}/").replace("](null_calibration.md)", "](#calibration)")
    body = markdown.markdown(md, extensions=["tables", "fenced_code"])
    cal_path = ROOT / "docs" / "null_calibration.md"
    cal = markdown.markdown(cal_path.read_text(), extensions=["tables"]) if cal_path.exists() else ""
    outs = ", ".join(d.outages) if d.outages else "none detected"
    return {"body": body, "calibration": cal, "outages": f"{len(d.outages)} days: {outs}."}


# ------------------------------------------------------------------ build --
def build(out: Path = OUT) -> Path:
    d = Data()
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    (out / "data").mkdir()
    for f in ("style.css", "app.js"):
        shutil.copy(HERE / "static" / f, out / "assets" / f)
    shutil.copy(Path(plotly.__file__).parent / "package_data" / "plotly.min.js", out / "assets" / "plotly.min.js")
    for name in ("leadlag_company.csv", "leadlag_pooled.csv", "quarterly_panel.csv", "revenue_quarterly.csv",
                 "what_moved.csv", "hn_share.csv", "entity_weekly.csv"):
        if (PROCESSED / name).exists():
            shutil.copy(PROCESSED / name, out / "data" / name)
    (out / ".nojekyll").write_text("")

    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape(["html"]))
    base = {"nav": NAV, "asof": d.asof(), "portfolio": PORTFOLIO, "repo": REPO,
            "build_id": dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M")}

    def render(tpl, fname, title, description, ctx=None, figs=None):
        html_ = env.get_template(tpl).render(**base, **(ctx or {}), page=fname, title=title, description=description,
                                             figs_json=json.dumps(figs or {}, separators=(",", ":")))
        (out / fname).write_text(html_)

    render("index.html", "index.html", "What moved this week",
           "Weekly tracker of developer adoption of AI and data-infrastructure tools from free public data.", page_index(d))
    groups = trends_bundles(d, out / "data" / "trends")
    pypi_start = d.pypi["date"].min() if not d.pypi.empty else "n/a"
    render("trends.html", "trends.html", "Tool trends", "Downloads, YoY growth and HN hiring share per tool.",
           {"entity_groups": groups, "pypi_start": pypi_start})
    ctx, figs = page_ai_sdk(d)
    render("ai_sdk.html", "ai-sdk.html", "AI SDK market share", "OpenAI vs Anthropic vs Google vs Mistral SDK downloads.", ctx, figs)
    ctx, figs = page_leadlag(d)
    render("leadlag.html", "lead-lag.html", "Lead/lag study",
           "Do developer-adoption signals lead revenue for data-infrastructure companies? A research note.", ctx, figs)
    render("methodology.html", "methodology.html", "Methodology", "Data sources, matching rules and statistics.", page_methodology(d))
    return out


if __name__ == "__main__":
    p = build()
    total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    print(f"built {p} ({total / 1e6:.1f} MB)")
