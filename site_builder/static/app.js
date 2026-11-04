// Render Plotly figures embedded as JSON, wire up toggles and sortable tables.
const CONFIG = { displaylogo: false, responsive: true, modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"] };

// Figures are built with light-mode text and grid colors; swap them for the page's own in dark mode.
const DARK = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
function darkLayout(layout) {
  if (!DARK) return layout;
  const css = getComputedStyle(document.documentElement);
  const ink = css.getPropertyValue("--ink").trim(), ink2 = css.getPropertyValue("--ink-2").trim();
  const grid = css.getPropertyValue("--border").trim();
  const l = JSON.parse(JSON.stringify(layout));
  l.font = Object.assign({}, l.font, { color: ink2 });
  if (l.title && l.title.font) l.title.font.color = ink;
  Object.keys(l).filter(k => /^[xy]axis\d*$/.test(k)).forEach(k => { l[k].gridcolor = grid; l[k].linecolor = grid; l[k].zerolinecolor = grid; });
  (l.annotations || []).forEach(a => { a.font = Object.assign({}, a.font, { color: ink2 }); });
  if (l.hoverlabel) l.hoverlabel.bgcolor = css.getPropertyValue("--surface").trim();
  return l;
}

function draw(el, fig) {
  if (!fig) { el.innerHTML = '<p class="note">No data for this selection yet.</p>'; return; }
  Plotly.react(el, fig.data, darkLayout(fig.layout), CONFIG);
}

function renderAll(root = document) {
  root.querySelectorAll("[data-fig]").forEach(el => {
    const fig = (window.FIGS || {})[el.dataset.fig];
    if (fig !== undefined) draw(el, fig);
  });
}

// Segmented toggles: <div class="seg" data-group="reg"><button data-value="npm">...</button></div>
// Elements with data-show-group="reg" data-show-value="npm" are shown when selected.
function initSegs() {
  document.querySelectorAll(".seg[data-group]").forEach(seg => {
    const group = seg.dataset.group;
    const pick = v => {
      seg.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.value === v));
      document.querySelectorAll(`[data-show-group="${group}"]`).forEach(el => {
        const on = el.dataset.showValue === v;
        el.style.display = on ? "" : "none";
        if (on) el.querySelectorAll("[data-fig]").forEach(c => Plotly.Plots.resize(c));
      });
    };
    seg.querySelectorAll("button").forEach(b => b.addEventListener("click", () => pick(b.dataset.value)));
    pick(seg.querySelector("button.on")?.dataset.value || seg.querySelector("button").dataset.value);
  });
}

// Sortable tables: click a header to sort by data-sort (numeric) or text.
function initTables() {
  document.querySelectorAll("table.data.sortable").forEach(t => {
    t.querySelectorAll("th").forEach((th, i) => th.addEventListener("click", () => {
      const rows = [...t.tBodies[0].rows];
      const asc = th.dataset.dir !== "asc";
      t.querySelectorAll("th").forEach(h => delete h.dataset.dir);
      th.dataset.dir = asc ? "asc" : "desc";
      const key = r => { const c = r.cells[i]; const v = c.dataset.sort; return v !== undefined ? parseFloat(v) : c.textContent.trim().toLowerCase(); };
      rows.sort((a, b) => { const x = key(a), y = key(b);
        if (typeof x === "number" && typeof y === "number") { if (isNaN(x)) return 1; if (isNaN(y)) return -1; return asc ? x - y : y - x; }
        return asc ? String(x).localeCompare(String(y)) : String(y).localeCompare(String(x)); });
      rows.forEach(r => t.tBodies[0].appendChild(r));
    }));
  });
  document.querySelectorAll("input[data-filter-table]").forEach(inp => {
    const t = document.getElementById(inp.dataset.filterTable);
    const apply = () => {
      const q = inp.value.toLowerCase().trim();
      const rows = [...t.tBodies[0].rows];
      rows.forEach(r => r.style.display = r.textContent.toLowerCase().includes(q) ? "" : "none");
      // Hide a column when every visible row is blank ("–"), e.g. npm week-over-week or PyPI YoY.
      const shown = rows.filter(r => r.style.display !== "none");
      const n = t.tHead ? t.tHead.rows[0].cells.length : 0;
      for (let i = 0; i < n; i++) {
        const blank = shown.length > 0 && shown.every(r => r.cells[i] && /^[–-]?$/.test(r.cells[i].textContent.trim()));
        [t.tHead.rows[0], ...rows].forEach(r => { if (r.cells[i]) r.cells[i].style.display = blank ? "none" : ""; });
      }
    };
    inp.addEventListener("input", apply);
    document.querySelectorAll(`button[data-filter-for="${inp.id}"]`).forEach(b => b.addEventListener("click", () => {
      inp.value = b.dataset.value;
      document.querySelectorAll(`button[data-filter-for="${inp.id}"]`).forEach(x => x.classList.toggle("on", x === b));
      apply();
    }));
  });
}

// Tool trends: lazy-load per-entity figure bundles.
async function initTrends() {
  const sel = document.getElementById("entity");
  if (!sel) return;
  const load = async id => {
    const res = await fetch(`data/trends/${id}.json`);
    const bundle = await res.json();
    document.getElementById("proxies").innerHTML = bundle.proxies;
    ["downloads", "yoy", "hn", "stars"].forEach(k => {
      const el = document.getElementById(`fig-${k}`);
      const box = document.getElementById(`box-${k}`);
      if (!el) return;
      const fig = bundle.figs[k];
      box.style.display = fig ? "" : "none";
      if (fig) draw(el, fig);
    });
    document.getElementById("hn-note").innerHTML = bundle.hn_note || "";
    document.getElementById("hn-samples").innerHTML = bundle.hn_samples || "";
    document.getElementById("gh-table").innerHTML = bundle.gh_table || "";
    history.replaceState(null, "", `#${id}`);
  };
  sel.addEventListener("change", () => load(sel.value));
  const fromHash = decodeURIComponent(location.hash.slice(1));
  if (fromHash && [...sel.options].some(o => o.value === fromHash)) sel.value = fromHash;
  load(sel.value);
}

// Lead/lag: company picker for the raw-series chart.
function initPickers() {
  document.querySelectorAll("select[data-fig-picker]").forEach(sel => {
    const el = document.getElementById(sel.dataset.figPicker);
    const go = () => draw(el, (window.FIGS || {})[sel.value]);
    sel.addEventListener("change", go); go();
  });
}

document.addEventListener("DOMContentLoaded", () => { renderAll(); initSegs(); initTables(); initTrends(); initPickers(); });
