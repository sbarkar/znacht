// Znacht app: one page, four screens, no build step. Preact + htm, vendored.
import { html, render, useState, useEffect, useCallback } from "/app/static/vendor/htm-preact-standalone.module.js";

// ---------- token and API --------------------------------------------------------------
const params = new URLSearchParams(location.search);
if (params.get("token")) {
  try { localStorage.setItem("znacht_token", params.get("token")); } catch (e) { /* storage may be blocked */ }
  history.replaceState(null, "", location.pathname + location.hash);
}
function token() { try { return localStorage.getItem("znacht_token") || ""; } catch (e) { return ""; } }

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token()}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) { /* not json */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.status === 204 ? null : res.json();
}

// ---------- small helpers --------------------------------------------------------------
const chf = (v) => (v == null ? "" : `CHF ${Number(v).toFixed(2)}`);
const shortDay = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-GB", { weekday: "short" }).toUpperCase();
const dayNum = (iso) => String(Number(iso.slice(8, 10)));
const useHash = () => {
  const [hash, setHash] = useState(location.hash || "#week");
  useEffect(() => { const f = () => setHash(location.hash || "#week"); addEventListener("hashchange", f); return () => removeEventListener("hashchange", f); }, []);
  return hash;
};

const Icon = ({ name }) => {
  const paths = {
    week: html`<rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" />`,
    groceries: html`<path d="M6 6h15l-1.5 9h-12z" /><path d="M6 6L5 3H2" /><circle cx="9" cy="20" r="1.5" /><circle cx="18" cy="20" r="1.5" />`,
    household: html`<circle cx="9" cy="8" r="3.5" /><circle cx="17" cy="9" r="2.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0M14 20a4 4 0 0 1 7.5-2" />`,
    connections: html`<circle cx="5" cy="12" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="19" cy="18" r="2" /><path d="M7 11l10-4M7 13l10 4" />`,
    lock: html`<rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" />`,
    move: html`<path d="M7 7h11M14 3l4 4-4 4M17 17H6M10 13l-4 4 4 4" />`,
    check: html`<path d="M5 12l5 5L20 7" />`,
    close: html`<path d="M6 6l12 12M18 6L6 18" />`,
    robot: html`<path d="M7 4h10l1 5H6z" /><rect x="5" y="9" width="14" height="11" rx="2" /><path d="M12 13v3" />`,
    spark: html`<path d="M12 3l1.8 4.6L18 9l-4.2 1.4L12 15l-1.8-4.6L6 9l4.2-1.4z" />`,
  };
  return html`<svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${paths[name]}</svg>`;
};

const Nav = ({ hash }) => html`
  <nav class="nav">
    ${[["#week", "week", "Week"], ["#groceries", "groceries", "Groceries"], ["#household", "household", "Household"], ["#connections", "connections", "Connect"]].map(
      ([href, icon, label]) => html`<a href=${href} class=${hash === href ? "on" : ""} aria-label=${label}><${Icon} name=${icon} />${label}</a>`
    )}
  </nav>`;

// ---------- Week ------------------------------------------------------------------------
function Week({ view, reload, busy, toast }) {
  const [open, setOpen] = useState(null);
  const [alts, setAlts] = useState(null);
  const [working, setWorking] = useState(false);
  const dinner = open != null ? view.dinners[open] : null;

  useEffect(() => {
    if (dinner == null) { setAlts(null); return; }
    setAlts(null);
    api("GET", `/api/runs/${view.run_id}/alternatives?day=${dinner.date}`).then(setAlts).catch((e) => toast(e.message));
  }, [open, view.run_id]);

  const swap = async (recipe_id) => {
    setWorking(true);
    try { await api("POST", `/api/runs/${view.run_id}/swap`, { date: dinner.date, recipe_id }); toast("Swapped. Groceries recalculated."); setOpen(null); await reload(); }
    catch (e) { toast(e.message); } finally { setWorking(false); }
  };
  const toggleLock = async () => {
    try { await api("POST", `/api/runs/${view.run_id}/lock`, { date: dinner.date, locked: !dinner.locked }); await reload(); } catch (e) { toast(e.message); }
  };
  const replan = async () => {
    try { await api("POST", `/api/runs/${view.run_id}/replan`); toast("Planning again, keeping what you locked…"); } catch (e) { toast(e.message); }
  };

  return html`
    <div class="screen">
      <div class="top span">
        <span class="brand">Znacht</span>
        <span class="pill quiet">${view.week_label}</span>
      </div>
      <div class="span">
        <h1>${view.theme}</h1>
        <p style="margin-top:6px">${view.chef_note}</p>
      </div>
      <div class="pills span">
        ${view.violations.length ? html`<span class="pill warn">Needs your input</span>` : html`<span class="pill ok">Rules met</span>`}
        <span class="pill">${chf(view.money.online_total)} online</span>
        <span class="pill">${view.in_store.length} in store</span>
        ${view.slot ? html`<span class="pill quiet">Delivery ${view.slot}</span>` : null}
        ${busy ? html`<span class="pill quiet">${busy}…</span>` : null}
      </div>
      ${view.plan_removes.length && view.status === "needs_approval" ? html`
        <div class="card dashed span">
          <h2>Already in My Week, will be removed on approve</h2>
          ${view.plan_removes.map((r) => html`<div class="warn-text">${r}</div>`)}
        </div>` : null}
      ${view.violations.length ? html`<div class="card span"><h2>Needs your input</h2>${view.violations.map((v) => html`<div class="warn-text">${v}</div>`)}</div>` : null}
      <div style="display:flex;flex-direction:column;gap:10px" class="span">
        ${view.dinners.map((d, i) => html`
          <button type="button" class=${"day" + (open === i ? " active" : "")} onClick=${() => setOpen(i)}>
            <div class="date"><small>${shortDay(d.date)}</small><b>${dayNum(d.date)}</b></div>
            <div class="body">
              <span class="title">${d.title}</span>
              <span class="meta">${d.minutes ? `${d.minutes} min · ` : ""}${d.cost_per_person ? `${chf(d.cost_per_person)} pp · ` : ""}${d.tags.map((t) => t.replace("_", " ")).join(", ")}</span>
            </div>
            ${d.in_store_day ? html`<span class="tag">STORE</span>` : null}
            ${d.locked ? html`<span class="lock"><${Icon} name="lock" /></span>` : null}
          </button>`)}
      </div>
      <div class="row span">
        <button type="button" class="btn ghost" onClick=${replan} disabled=${!!busy}>Plan again (keeps locked)</button>
        ${view.status === "needs_approval" ? html`<a class="btn ghost" href="#groceries" style="text-decoration:none">Review groceries →</a>` : null}
      </div>
      ${dinner ? html`
        <div class="sheet-back" onClick=${(e) => { if (e.target === e.currentTarget) setOpen(null); }}>
          <div class="sheet" role="dialog" aria-label=${"Swap " + dinner.title}>
            <div class="handle"></div>
            <div class="sheet-head"><b>${shortDay(dinner.date)} ${dayNum(dinner.date)} · ${dinner.title}</b><span class="muted" style="font-size:12px">alternatives keep the rules</span></div>
            ${dinner.note ? html`<p class="muted" style="font-size:13px">${dinner.note}</p>` : null}
            ${dinner.url ? html`<a href=${dinner.url} target="_blank" rel="noopener" style="font-size:13px">Open recipe</a>` : null}
            ${alts == null ? html`<p class="muted">Finding alternatives…</p>` : alts.length === 0 ? html`<p class="muted">Nothing else in this week's pool fits here. Plan again for a fresh pool.</p>` : alts.map((a, j) => html`
              <button type="button" class=${"alt" + (j === 0 ? " best" : "")} onClick=${() => swap(a.recipe_id)} disabled=${working}>
                <span>${a.title}</span>
                <span class="meta">${a.minutes ? `${a.minutes} min · ` : ""}${a.tags.map((t) => t.replace("_", " ")).join(", ")}${a.keeps_rules ? "" : " · bends a weekly count"}</span>
              </button>`)}
            <div class="row">
              <button type="button" class="btn primary" onClick=${() => alts && alts.length && swap(alts[Math.floor(Math.random() * alts.length)].recipe_id)} disabled=${working || !alts || !alts.length}>Surprise me</button>
              <button type="button" class="btn" onClick=${toggleLock}>${dinner.locked ? "Unlock" : "Lock"}</button>
              <button type="button" class="btn icon" aria-label="Close" onClick=${() => setOpen(null)}><${Icon} name="close" /></button>
            </div>
          </div>
        </div>` : null}
    </div>`;
}

// ---------- Groceries -------------------------------------------------------------------
function Groceries({ view, reload, busy, toast }) {
  const [tab, setTab] = useState("online");
  const [text, setText] = useState("");
  const m = view.money;
  const total = Number(m.online_subtotal), min = Number(m.minimum_order);
  const pct = min > 0 ? Math.min(100, Math.round((total / min) * 100)) : 100;
  const todo = view.todo || { online: [], in_store: [] };
  const done = new Set([...(todo.online || []), ...(todo.in_store || [])].filter((i) => i.done).map((i) => i.uid));

  const move = async (need, to) => {
    try { await api("POST", `/api/runs/${view.run_id}/move`, { need, to }); toast(`Moved ${need} ${to === "online" ? "online" : "to the store run"}.`); await reload(); } catch (e) { toast(e.message); }
  };
  const tick = async (kind, uid, isDone) => {
    try { await api("POST", `/api/lists/${kind}/done`, { uid, done: !isDone }); await reload(); } catch (e) { toast(e.message); }
  };
  const add = async () => {
    if (!text.trim()) return;
    try { await api("POST", `/api/lists/in_store/items`, { summary: text.trim() }); setText(""); toast("Added to the store run."); await reload(); } catch (e) { toast(e.message); }
  };
  const approve = async () => {
    if (!confirm(`Write this plan to My Week and both store lists?${view.plan_removes.length ? `\n\nThis removes ${view.plan_removes.length} dinner(s) already in My Week.` : ""}`)) return;
    try { await api("POST", `/api/apply?run_id=${view.run_id}`); toast("Applied. Znacht never pays: finish the order yourself."); await reload(); } catch (e) { toast(e.message); }
  };
  const revert = async () => {
    if (!confirm("Undo this apply on My Week and both lists?")) return;
    try { await api("POST", `/api/runs/${view.run_id}/revert`); toast("Reverted."); await reload(); } catch (e) { toast(e.message); }
  };

  const lines = tab === "online" ? view.online : view.in_store;
  const kind = tab === "online" ? "online" : "in_store";
  return html`
    <div class="screen">
      <div class="top span"><span class="brand">Groceries</span>${view.slot ? html`<span class="pill quiet">Delivery ${view.slot}</span>` : null}</div>
      <div class="card span">
        <div style="display:flex;justify-content:space-between;font-size:13px"><span class="muted">Online basket</span><b>${chf(total)} <span class="muted" style="font-weight:400">/ ${chf(min)} minimum</span></b></div>
        <div class="bar"><div style=${`width:${pct}%;background:${m.meets_minimum ? "var(--ok)" : "var(--accent)"}`}></div></div>
        <span class=${m.meets_minimum ? "ok-text" : "warn-text"} style="font-size:12px;font-weight:600">${m.meets_minimum ? `Minimum met${Number(m.deposit) > 0 ? ` · ${chf(m.deposit)} box deposit for frozen items` : ""}` : `${chf(m.shortfall)} short: move something from the store run or add what you need`}</span>
      </div>
      <div class="tabs span">
        <button type="button" class=${"tab" + (tab === "online" ? " on" : "")} onClick=${() => setTab("online")}>Online · ${view.online.length}</button>
        <button type="button" class=${"tab" + (tab === "store" ? " on" : "")} onClick=${() => setTab("store")}>Store run · ${view.in_store.length + view.free_text.length}</button>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px" class="span">
        ${lines.map((it) => {
          const uid = `${kind}:${it.product_id}`; const isDone = done.has(uid);
          return html`
            <div class=${"line" + (isDone ? " done" : "")}>
              <button type="button" class=${"check" + (isDone ? " on" : "")} aria-label=${isDone ? "Mark not bought" : "Mark bought"} onClick=${() => tick(kind, uid, isDone)}><${Icon} name="check" /></button>
              <div class="qty">${it.packs}×</div>
              <div class="body">
                <span class="name">${it.name}</span>
                <span class=${"note" + (it.deliverable === false || it.flagged ? " flag" : "")}>${it.need} · ${it.pack}${it.deliverable === false ? " · not deliverable" : ""}${it.switched ? " · swapped" : ""}${it.flagged ? " · healthier option costs more" : ""}</span>
              </div>
              <span class="price">${chf(it.price)}</span>
              ${tab === "online" ? html`<button type="button" class="check" aria-label="Move to store run" onClick=${() => move(it.need, "store")} disabled=${!!busy}><${Icon} name="move" /></button>` :
                it.movable ? html`<button type="button" class="check" aria-label="Move to online basket" onClick=${() => move(it.need, "online")} disabled=${!!busy}><${Icon} name="move" /></button>` : null}
            </div>`;
        })}
        ${tab === "store" ? (todo.in_store || []).filter((i) => i.uid.startsWith("text:")).map((i) => html`
          <div class=${"line" + (i.done ? " done" : "")}>
            <button type="button" class=${"check" + (i.done ? " on" : "")} aria-label="Mark bought" onClick=${() => tick("in_store", i.uid, i.done)}><${Icon} name="check" /></button>
            <div class="body"><span class="name">${i.summary}</span><span class="note">not in the catalogue: add it in the app</span></div>
          </div>`) : null}
      </div>
      ${view.swaps.length ? html`<div class="card span"><h2>Swaps and flags this week</h2>${view.swaps.map((s) => html`<div class=${"swap " + s.kind}><b>${s.need}</b> → ${s.chosen}${s.delta ? html` <span class=${s.kind === "switch" ? "ok-text" : "warn-text"}>(${Number(s.delta) < 0 ? "−" : "+"}${Math.abs(Number(s.delta)).toFixed(2)})</span>` : null}<div class="meta">${s.reason}</div></div>`)}</div>` : null}
      ${view.pantry_check.length ? html`<div class="card"><h2>Check the pantry</h2><p style="font-size:13px">The recipes assume you have these; nothing is bought.</p><div class="chips">${view.pantry_check.map((p) => html`<span class="chip quiet">${p}</span>`)}</div></div>` : null}
      <div class="card">
        <h2>Add anything</h2>
        <div class="row">
          <label for="free" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)">Add anything</label>
          <input id="free" class="input" placeholder="birthday candles, cat food…" value=${text} onInput=${(e) => setText(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && add()} />
          <button type="button" class="btn" onClick=${add}>Add</button>
        </div>
      </div>
      <div class="row span" style="padding-top:6px">
        ${view.status === "needs_approval" ? html`<button type="button" class="btn primary" onClick=${approve} disabled=${!!busy}>Approve: send plan and lists</button>` : null}
        ${view.status === "applied" ? html`<span class="pill ok">Applied</span>${view.checkout_url ? html`<a class="btn" href=${view.checkout_url} target="_blank" rel="noopener" style="text-decoration:none">Open the basket</a>` : null}<button type="button" class="btn ghost" onClick=${revert}>Undo</button>` : null}
        ${view.status === "reverted" ? html`<span class="pill quiet">Reverted</span>` : null}
      </div>
    </div>`;
}

// ---------- Household (read-only for now; editing lands next) -------------------------
function Household({ household, toast }) {
  if (!household) return html`<div class="screen"><div class="empty">Loading the household…</div></div>`;
  const colors = ["var(--accent)", "var(--ok)", "var(--lilac)", "#ffd166"];
  return html`
    <div class="screen">
      <div class="top span"><span class="brand">Household</span><span class="pill quiet">${household.servings} servings</span></div>
      <div class="row span" style="align-items:stretch">
        ${household.members.map((m, i) => html`<div class="member"><div class="avatar" style=${`background:${colors[i % colors.length]}`}>${m.name.slice(0, 1).toUpperCase()}</div><b style="font-size:13px">${m.name}</b><span class="muted" style="font-size:11px">${[m.age_group, ...(m.dislikes.map((d) => "no " + d)), ...(m.allergies.map((a) => "allergy: " + a)), m.needs_mild_food ? "mild food" : null].filter(Boolean).join(" · ")}</span></div>`)}
      </div>
      <div class="card">
        <h2>Every week</h2>
        ${Object.entries(household.rules.min_tags).map(([k, v]) => html`<div class="stepper"><span style="flex:1 1 auto;font-weight:500">${k.replace("_", " ")}</span><span class="n">${v}×</span>${household.rules.max_tags[k] != null ? html`<span class="muted" style="font-size:12px">max ${household.rules.max_tags[k]}</span>` : null}</div>`)}
        <div class="chips">${household.rules.banned_ingredients.map((b) => html`<span class="chip">no ${b}</span>`)}${household.needs_mild_food ? html`<span class="chip">toddler mild</span>` : null}${household.rules.max_total_minutes_weekday ? html`<span class="chip">weekdays ≤ ${household.rules.max_total_minutes_weekday} min</span>` : null}</div>
      </div>
      <div class="card">
        <h2>Health</h2>
        ${household.health.rules.length ? household.health.rules.map((r) => html`<div>${r}</div>`) : html`<p class="muted" style="font-size:13px">No health rules yet. Upload a lab report with <code>znacht extract lab</code> and confirm the draft.</p>`}
      </div>
      <div class="card">
        <h2>Pantry</h2>
        <div class="chips">${household.pantry.map((p) => html`<span class="chip">${p.name} ${p.quantity}</span>`)}</div>
        ${household.make_at_home.length ? html`<div style="font-size:13px">Make at home: <span class="muted">${household.make_at_home.join(", ")}</span></div>` : null}
      </div>
      <div class="card">
        <h2>Delivery and store</h2>
        <div style="font-size:13px">Postcode <b>${household.delivery.postcode}</b>${household.store_lists ? html` · online list <b>${household.store_lists.online}</b> · store list <b>${household.store_lists.in_store}</b>` : null}</div>
        <p class="muted" style="font-size:12px">Editing lands in the next step; until then the household YAML is the place.</p>
      </div>
    </div>`;
}

// ---------- Connections -----------------------------------------------------------------
function Connections({ status, household }) {
  const adapters = (status && status.adapters) || {};
  const card = (icon, title, sub, on) => html`<div class="conn"><div class="ico"><${Icon} name=${icon} /></div><div style="flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:2px"><b style="font-size:15px">${title}</b><span class="muted" style="font-size:12px">${sub}</span></div><span class=${"dot" + (on ? "" : " off")} role="img" aria-label=${on ? "Connected" : "Not connected"}></span></div>`;
  return html`
    <div class="screen">
      <div class="top span"><span class="brand">Connections</span></div>
      <p class="span">Where recipes come from, where the plan goes, where the food is bought. Each is a plug-in; the week does not care which.</p>
      <div style="display:flex;flex-direction:column;gap:8px"><h2>Cooking</h2>
        ${card("robot", "Thermomix · Cookidoo", adapters.recipes === "cookidoo" ? "recipes and My Week" : "recipes from the fixture catalogue", adapters.recipes === "cookidoo")}
        ${card("week", "Home Assistant", "calendar, lists, tonight's dinner, this app", true)}
        <div class="card dashed"><b style="font-size:14px;color:var(--soft)">Mealie · Tandoor · Monsieur Cuisine · Cookit</b><span class="muted" style="font-size:12px">adapters anyone can add; the first two have real APIs</span></div>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px"><h2>Shopping</h2>
        ${card("groceries", "Migros", household ? `delivery to ${household.delivery.postcode} · min. ${chf(status && status.minimum_order)}` : "", adapters.store === "migros")}
        <div class="card dashed"><b style="font-size:14px;color:var(--soft)">Coop · Farmy · Aldi · Lidl</b><span class="muted" style="font-size:12px">compare the same basket across shops</span></div>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px"><h2>Planner</h2>
        ${card("spark", adapters.planner === "anthropic" ? "Claude plans, the rules decide" : "Rule-based planner", "every plan is checked; every write needs your tap", true)}
      </div>
      <div class="card"><h2>Since the start</h2><span class="big">${chf(status && status.lifetime_savings)} saved</span><span class="muted" style="font-size:12px">counted on approved weeks</span></div>
    </div>`;
}

// ---------- App shell -------------------------------------------------------------------
function App() {
  const hash = useHash();
  const [view, setView] = useState(null);
  const [status, setStatus] = useState(null);
  const [household, setHousehold] = useState(null);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const toast = useCallback((t) => { setMsg(t); setTimeout(() => setMsg(null), 3500); }, []);

  const reload = useCallback(async () => {
    try {
      const [v, s] = await Promise.all([api("GET", "/api/view"), api("GET", "/api/status")]);
      setView(v); setStatus(s); setError(null);
    } catch (e) { setError(e.message); }
  }, []);
  useEffect(() => { reload(); api("GET", "/api/household").then(setHousehold).catch(() => {}); }, []);
  useEffect(() => {
    const busy = (status && status.busy) || (view && view.busy);
    if (!busy) return;
    const t = setInterval(reload, 4000);
    return () => clearInterval(t);
  }, [status && status.busy, view && view.busy]);

  const busy = (status && status.busy) || null;
  const planNow = async () => { try { await api("POST", "/api/plan_week"); toast("Planning next week…"); await reload(); } catch (e) { toast(e.message); } };

  let body;
  if (error) body = html`<div class="screen"><div class="empty span"><b>Can't reach the engine</b><span>${error}</span><button type="button" class="btn" onClick=${reload}>Try again</button></div></div>`;
  else if (!view) body = html`<div class="screen"><div class="empty span">Loading…</div></div>`;
  else if (view.run_id == null && hash !== "#household" && hash !== "#connections") body = html`<div class="screen"><div class="empty span"><span class="brand">Znacht</span><span>No week planned yet.</span><button type="button" class="btn primary" onClick=${planNow} disabled=${!!busy}>${busy ? "Planning…" : "Plan next week"}</button></div></div>`;
  else if (hash === "#groceries") body = html`<${Groceries} view=${view} reload=${reload} busy=${busy} toast=${toast} />`;
  else if (hash === "#household") body = html`<${Household} household=${household} toast=${toast} />`;
  else if (hash === "#connections") body = html`<${Connections} status=${status} household=${household} />`;
  else body = html`<${Week} view=${view} reload=${reload} busy=${busy} toast=${toast} />`;

  return html`<div class="shell">${body}<${Nav} hash=${hash} />${msg ? html`<div class="toast" role="status">${msg}</div>` : null}</div>`;
}

render(html`<${App} />`, document.getElementById("root"));
