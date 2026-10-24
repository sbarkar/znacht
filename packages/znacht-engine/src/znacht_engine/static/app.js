// Znacht app: one page, four screens, no build step. Preact + htm, vendored.
import { html, render, useState, useEffect, useCallback } from "/app/static/vendor/htm-preact-standalone.module.js?v=1";

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

// ---------- Week: a rolling timeline. My Week is the truth, runs are proposals (ADR-0011) ----
const DAYS = 14;
const SOURCE = (card) => (card.source === "manual" ? "yours" : `Znacht run ${card.source}`);
const BADGE = (g) => (g.coverage === "none" ? "no groceries" : g.label);

function DayRow({ d, today, onOpen, onApprove }) {
  const card = d.dinner || d.proposal;
  const cls = `day st-${d.state}${d.date === today ? " today" : ""}${d.dinner && d.dinner.source === "manual" ? " manual" : ""}`;
  const tappable = d.state !== "empty";
  const open = () => tappable && onOpen(d);
  return html`
    <div class=${cls} role=${tappable ? "button" : null} tabindex=${tappable ? 0 : null} onClick=${open} onKeyDown=${(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } }} aria-label=${`${d.weekday} ${dayNum(d.date)}: ${card ? card.title : "nothing planned"}`}>
      <div class="date"><small>${d.weekday.toUpperCase()}</small><b>${dayNum(d.date)}</b></div>
      <div class="body">
        ${d.state === "empty" ? html`<span class="title muted">Nothing yet</span>` :
          d.state === "proposed" ? html`<span class="title">${card.title}</span><span class="meta">proposed by run ${d.proposal.source} · not in My Week yet</span>` :
          html`<span class="title">${card.title}</span>
               <span class="meta">${SOURCE(d.dinner)}${d.dinner.minutes ? ` · ${d.dinner.minutes} min` : ""}</span>
               ${d.proposal ? html`<span class="meta proposal">run ${d.proposal.source} proposes ${d.proposal.title}</span>` : null}`}
      </div>
      ${d.state !== "empty" && d.state !== "past" ? html`<span class=${"badge g-" + d.groceries.coverage}>${BADGE(d.groceries)}</span>` : null}
      ${d.locked ? html`<span class="lock" title="Locked"><${Icon} name="lock" /></span>` : null}
      ${d.proposal && d.state !== "past" ? html`<button type="button" class="approve" onClick=${(e) => { e.stopPropagation(); onApprove(d.proposal.source); }}>Approve</button>` : null}
    </div>`;
}

function Timeline({ tl, reload, busy, toast, selectRun }) {
  const [open, setOpen] = useState(null);
  const [alts, setAlts] = useState(null);
  const [working, setWorking] = useState(false);
  const day = open ? tl.days.find((d) => d.date === open) || null : null;
  const card = day ? (day.dinner || day.proposal) : null;

  useEffect(() => {
    setAlts(null);
    if (!day || !day.run_id) return;
    api("GET", `/api/runs/${day.run_id}/alternatives?day=${day.date}`).then(setAlts).catch((e) => toast(e.message));
  }, [open, day && day.run_id]);

  const swap = async (recipe_id) => {
    setWorking(true);
    try { await api("POST", `/api/runs/${day.run_id}/swap`, { date: day.date, recipe_id }); toast("Swapped as a proposal. Approve it to change My Week."); setOpen(null); await reload(); }
    catch (e) { toast(e.message); } finally { setWorking(false); }
  };
  const toggleLock = async () => {
    try { await api("POST", `/api/runs/${day.run_id}/lock`, { date: day.date, locked: !day.locked }); await reload(); } catch (e) { toast(e.message); }
  };
  const approve = (runId) => { selectRun(runId); setOpen(null); location.hash = "#groceries"; };
  const planGaps = async (w) => {
    const kept = w.locked_dates.length;
    try {
      await api("POST", "/api/plan_week", { week: w.week, locked_dates: w.locked_dates });
      toast(`Planning the gaps for ${w.label.toLowerCase()}${kept ? `, keeping ${kept} dinner${kept === 1 ? "" : "s"} in My Week` : ""}…`);
      await reload();
    } catch (e) { toast(e.message); }
  };

  const upcoming = tl.days.filter((d) => d.state !== "past");
  const planned = upcoming.filter((d) => d.dinner).length;
  const empty = upcoming.filter((d) => d.state === "empty").length;
  const proposed = upcoming.filter((d) => d.state === "proposed").length;
  const weeks = tl.weeks.map((w) => ({ ...w, days: tl.days.filter((d) => d.week === w.week) }));

  return html`
    <div class="screen">
      <div class="top span">
        <span class="brand">Znacht</span>
        <span class="pill quiet">next ${tl.horizon} days</span>
      </div>
      <div class="pills span">
        <span class=${"pill" + (planned === upcoming.length ? " ok" : "")}>${planned} of ${upcoming.length} days planned</span>
        ${empty ? html`<span class="pill warn">${empty} empty</span>` : html`<span class="pill ok">no gaps</span>`}
        ${proposed ? html`<span class="pill">${proposed} proposed</span>` : null}
        ${busy ? html`<span class="pill quiet">${busy}…</span>` : null}
      </div>
      ${weeks.map((w) => html`
        <section class="wk span" aria-label=${w.label}>
          <div class="wk-head"><h2>${w.label}</h2><span class="sum">${w.summary}</span></div>
          ${w.my_week_ok ? null : html`<div class="card dashed"><span class="warn-text">My Week could not be read just now; showing what Znacht last sent.</span></div>`}
          ${w.days.map((d) => html`<${DayRow} key=${d.date} d=${d} today=${tl.today} onOpen=${(x) => setOpen(x.date)} onApprove=${approve} />`)}
          <div class="row">
            ${w.days.some((d) => d.state === "empty") ? html`<button type="button" class="btn primary" onClick=${() => planGaps(w)} disabled=${!!busy}>Plan the gaps${w.locked_dates.length ? ` · keeps ${w.locked_dates.length} in My Week` : ""}</button>` : null}
            ${w.awaiting_run_id ? html`<button type="button" class="btn" onClick=${() => approve(w.awaiting_run_id)}>${w.awaiting_status === "needs_input" ? `Run ${w.awaiting_run_id} needs input` : `Review run ${w.awaiting_run_id}`}</button>` : null}
          </div>
        </section>`)}
      <p class="span muted" style="font-size:12px">Dinners come from Cookidoo My Week. Znacht only proposes; nothing changes there until you approve, and every approval shows what it removes first.</p>
      ${day ? html`
        <div class="sheet-back" onClick=${(e) => { if (e.target === e.currentTarget) setOpen(null); }}>
          <div class="sheet" role="dialog" aria-label=${`${day.weekday} ${dayNum(day.date)}`}>
            <div class="handle"></div>
            <div class="sheet-head"><b>${day.weekday} ${dayNum(day.date)} · ${card ? card.title : "nothing yet"}</b><span class=${"badge g-" + day.groceries.coverage}>${BADGE(day.groceries)}</span></div>
            ${day.dinner ? html`<p class="muted" style="font-size:13px">${day.dinner.source === "manual" ? "This dinner is yours in My Week. Znacht keeps it when it plans the gaps; change it in Cookidoo or swap it below once a run proposes for this day." : `Sent to My Week by Znacht run ${day.dinner.source}.`}${day.dinner.note ? ` ${day.dinner.note}` : ""}</p>` : null}
            ${day.proposal ? html`<div class="swap"><b>Run ${day.proposal.source} proposes</b> ${day.proposal.title}<div class="meta">${day.dinner ? "replaces the dinner above when approved" : "not in My Week until approved"}</div></div>` : null}
            ${card && card.url ? html`<a href=${card.url} target="_blank" rel="noopener" style="font-size:13px">Open recipe</a>` : null}
            ${day.run_id ? (alts == null ? html`<p class="muted">Finding alternatives…</p>` : alts.length === 0 ? html`<p class="muted">Nothing else in this run's pool fits here.</p>` : html`<h2>Swap for</h2>${alts.map((a, j) => html`
              <button type="button" class=${"alt" + (j === 0 ? " best" : "")} onClick=${() => swap(a.recipe_id)} disabled=${working}>
                <span>${a.title}</span>
                <span class="meta">${a.minutes ? `${a.minutes} min · ` : ""}${a.tags.map((t) => t.replace("_", " ")).join(", ")}${a.keeps_rules ? "" : " · bends a weekly count"}</span>
              </button>`)}`) : null}
            <div class="row">
              ${day.proposal || day.state === "proposed" ? html`<button type="button" class="btn primary" onClick=${() => approve((day.proposal || day.dinner).source)}>Review and approve</button>` : null}
              ${day.run_id && alts && alts.length ? html`<button type="button" class="btn" onClick=${() => swap(alts[Math.floor(Math.random() * alts.length)].recipe_id)} disabled=${working}>Surprise me</button>` : null}
              ${day.run_id ? html`<button type="button" class="btn" onClick=${toggleLock}>${day.locked ? "Unlock" : "Lock"}</button>` : null}
              <button type="button" class="btn icon" aria-label="Close" onClick=${() => setOpen(null)}><${Icon} name="close" /></button>
            </div>
          </div>
        </div>` : null}
    </div>`;
}

// ---------- Groceries -------------------------------------------------------------------
function Groceries({ view, reload, busy, toast, pinned, selectRun }) {
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
      <div class="top span"><span class="brand">Groceries</span><span class="pills">${view.slot ? html`<span class="pill quiet">Delivery ${view.slot}</span>` : null}<span class="pill quiet">run ${view.run_id} · ${view.week_label}</span></span></div>
      ${pinned ? html`<div class="row span"><button type="button" class="btn ghost" style="min-height:36px;padding:6px 12px;font-size:12px" onClick=${() => selectRun(null)}>Back to the latest run</button></div>` : null}
      ${view.plan_removes.length && view.status === "needs_approval" ? html`
        <div class="card dashed span">
          <h2>Already in My Week, removed on approve</h2>
          ${view.plan_removes.map((r) => html`<div class="warn-text">${r}</div>`)}
        </div>` : null}
      ${view.violations.length ? html`<div class="card span"><h2>Needs your input</h2>${view.violations.map((v) => html`<div class="warn-text">${v}</div>`)}</div>` : null}
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

// ---------- Household --------------------------------------------------------------------
function Chips({ items, onRemove, onAdd, placeholder }) {
  const [v, setV] = useState("");
  const add = () => { if (v.trim()) { onAdd(v.trim().toLowerCase()); setV(""); } };
  return html`<div class="chips">
    ${items.map((it) => html`<span class="chip">${it} <button type="button" class="chip-x" aria-label=${"Remove " + it} onClick=${() => onRemove(it)}>×</button></span>`)}
    <input class="chip-input" placeholder=${placeholder} value=${v} onInput=${(e) => setV(e.target.value)} onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} onBlur=${add} aria-label=${placeholder} />
  </div>`;
}

function Household({ household, patch, toast, planner }) {
  const [draft, setDraft] = useState(null);
  const [busyPhoto, setBusyPhoto] = useState(false);
  if (!household) return html`<div class="screen"><div class="empty">Loading the household…</div></div>`;
  const colors = ["var(--accent)", "var(--ok)", "var(--lilac)", "#ffd166"];
  const tags = ["fish", "legumes", "red_meat", "poultry", "vegetarian"];
  const setRule = (tag, n) => patch({ rules: { min_per_week: { [tag]: n } } });
  const setMax = (tag, n) => patch({ rules: { max_per_week: { [tag]: n } } });
  const members = household.members;
  const updateMember = (i, changes) => patch({ members: members.map((m, j) => (j === i ? { ...m, ...changes } : m)) });
  const photo = async (file) => {
    if (!file) return;
    setBusyPhoto(true);
    try {
      const fd = new FormData(); fd.append("file", file);
      const res = await fetch("/api/pantry/photo", { method: "POST", headers: { Authorization: `Bearer ${token()}` }, body: fd });
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      const d = await res.json();
      setDraft(d.items.map((i) => ({ ...i, keep: i.confidence >= 0.5 })));
      if (d.unsure.length) toast(`Not sure about: ${d.unsure.join(", ")}`);
    } catch (e) { toast(e.message); } finally { setBusyPhoto(false); }
  };
  const confirmDraft = async () => {
    const items = Object.fromEntries(draft.filter((i) => i.keep).map((i) => [i.name, i.quantity]));
    await patch({ pantry: items }); setDraft(null); toast("Pantry updated.");
  };
  return html`
    <div class="screen">
      <div class="top span"><span class="brand">Household</span><span class="pill quiet">${household.servings} servings</span></div>
      <div class="row span" style="align-items:stretch">
        ${members.map((m, i) => html`<div class="member"><div class="avatar" style=${`background:${colors[i % colors.length]}`}>${m.name.slice(0, 1).toUpperCase()}</div><b style="font-size:13px">${m.name}</b>
          <select class="select" value=${m.age_group} onChange=${(e) => updateMember(i, { age_group: e.target.value })} aria-label=${m.name + " age group"}><option value="adult">adult</option><option value="child">child</option><option value="toddler">toddler</option></select>
          <span class="muted" style="font-size:11px">${m.needs_mild_food ? "mild food" : "any spice"}</span></div>`)}
      </div>
      <div class="card">
        <h2>Dislikes and allergies</h2>
        ${members.map((m, i) => html`<div style="display:flex;flex-direction:column;gap:6px"><b style="font-size:13px">${m.name}</b>
          <${Chips} items=${m.dislikes} placeholder="dislikes…" onAdd=${(x) => updateMember(i, { dislikes: [...m.dislikes, x] })} onRemove=${(x) => updateMember(i, { dislikes: m.dislikes.filter((d) => d !== x) })} />
          <${Chips} items=${m.allergies} placeholder="allergies…" onAdd=${(x) => updateMember(i, { allergies: [...m.allergies, x] })} onRemove=${(x) => updateMember(i, { allergies: m.allergies.filter((d) => d !== x) })} /></div>`)}
      </div>
      <div class="card">
        <h2>Every week</h2>
        ${tags.map((t) => { const n = household.rules.min_tags[t] || 0; const mx = household.rules.max_tags[t]; return html`<div class="stepper"><span style="flex:1 1 auto;font-weight:500">${t.replace("_", " ")}</span>
          <button type="button" class="check" aria-label=${"Fewer " + t} onClick=${() => setRule(t, n - 1)}>−</button><span class="n">${n}×</span><button type="button" class="check" aria-label=${"More " + t} onClick=${() => setRule(t, n + 1)}>+</button>
          <button type="button" class=${"btn ghost" + (mx != null ? " on" : "")} style="padding:6px 10px;min-height:36px;font-size:12px" onClick=${() => setMax(t, mx != null ? 0 : Math.max(n, 1))}>${mx != null ? `max ${mx}` : "no max"}</button></div>`; })}
        <div style="display:flex;flex-direction:column;gap:6px"><span class="muted" style="font-size:12px">Never in a recipe</span>
          <${Chips} items=${household.rules.banned_ingredients} placeholder="banned…" onAdd=${(x) => patch({ rules: { banned_ingredients: [...household.rules.banned_ingredients, x] } })} onRemove=${(x) => patch({ rules: { banned_ingredients: household.rules.banned_ingredients.filter((d) => d !== x) } })} /></div>
        <div class="stepper"><span style="flex:1 1 auto;font-weight:500">Weekday limit</span><button type="button" class="check" aria-label="Shorter weekday limit" onClick=${() => patch({ rules: { max_total_minutes_weekday: Math.max(15, (household.rules.max_total_minutes_weekday || 60) - 15) } })}>−</button><span class="n" style="width:auto">${household.rules.max_total_minutes_weekday || "—"} min</span><button type="button" class="check" aria-label="Longer weekday limit" onClick=${() => patch({ rules: { max_total_minutes_weekday: (household.rules.max_total_minutes_weekday || 45) + 15 } })}>+</button></div>
      </div>
      <div class="card">
        <h2>Health</h2>
        ${household.health.rules.length ? html`<${Chips} items=${household.health.rules} placeholder="add a rule in words…" onAdd=${(x) => patch({ health: { rules: [...household.health.rules, x] } })} onRemove=${(x) => patch({ health: { rules: household.health.rules.filter((r) => r !== x) } })} />` : html`<p class="muted" style="font-size:13px">No health rules yet. Upload a lab report with <code>znacht extract lab</code>, confirm the draft, or type a rule.</p><${Chips} items=${[]} placeholder="e.g. limit added sugar" onAdd=${(x) => patch({ health: { rules: [x] } })} onRemove=${() => {}} />`}
      </div>
      <div class="card">
        <div class="top"><h2>Pantry</h2>
          <label class="btn primary" style="flex:0 0 auto;padding:8px 14px;min-height:36px;font-size:12px;cursor:pointer">${busyPhoto ? "Reading photo…" : "Photo"}<input type="file" accept="image/*" capture="environment" style="display:none" onChange=${(e) => photo(e.target.files[0])} disabled=${busyPhoto || planner !== "anthropic"} /></label></div>
        ${planner !== "anthropic" ? html`<p class="muted" style="font-size:12px">Photo reading needs the Claude planner.</p>` : null}
        ${draft ? html`<div class="card dashed"><h2>From the photo: keep what is right</h2>
          ${draft.map((i, k) => html`<div class="line"><button type="button" class=${"check" + (i.keep ? " on" : "")} aria-label="Keep" onClick=${() => setDraft(draft.map((d, j) => (j === k ? { ...d, keep: !d.keep } : d)))}><${Icon} name="check" /></button><div class="body"><span class="name">${i.name}</span><span class="note">${i.quantity} · ${Math.round(i.confidence * 100)}% sure</span></div></div>`)}
          <div class="row"><button type="button" class="btn primary" onClick=${confirmDraft}>Save to pantry</button><button type="button" class="btn ghost" onClick=${() => setDraft(null)}>Discard</button></div></div>` : null}
        <${Chips} items=${household.pantry.map((p) => `${p.name} ${p.quantity}`)} placeholder="add: rice 1 kg" onAdd=${(x) => { const m = x.match(/^(.+?)\s+(\d[\d.,]*\s*\S*)$/); if (m) patch({ pantry: { [m[1].trim()]: m[2].trim() } }); else toast("Write it as 'name quantity', e.g. rice 1 kg"); }} onRemove=${(x) => { const name = household.pantry.find((p) => `${p.name} ${p.quantity}` === x); if (name) patch({ pantry: { [name.name]: "0" } }); }} />
        <div style="font-size:13px">Make at home: <span class="muted">${household.make_at_home.join(", ") || "nothing yet (edit in the YAML)"}</span></div>
      </div>
      <div class="card">
        <h2>Delivery and store</h2>
        <div style="font-size:13px">Postcode <b>${household.delivery.postcode}</b>${household.store_lists ? html` · online list <b>${household.store_lists.online}</b> · store list <b>${household.store_lists.in_store}</b>` : null}</div>
        <p class="muted" style="font-size:12px">Changes here are written into your household YAML, comments kept, and used by the next plan.</p>
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
  const [tl, setTl] = useState(null);
  const [runId, setRunId] = useState(null); // a run picked from the timeline's Approve pill
  const [status, setStatus] = useState(null);
  const [household, setHousehold] = useState(null);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const toast = useCallback((t) => { setMsg(t); setTimeout(() => setMsg(null), 3500); }, []);

  const reload = useCallback(async () => {
    try {
      const [v, s, t] = await Promise.all([
        api("GET", runId ? `/api/runs/${runId}/view` : "/api/view"),
        api("GET", "/api/status"),
        api("GET", `/api/timeline?days=${DAYS}`),
      ]);
      setView(v); setStatus(s); setTl(t); setError(null);
    } catch (e) { setError(e.message); }
  }, [runId]);
  useEffect(() => { api("GET", "/api/household").then(setHousehold).catch(() => {}); }, []);
  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {
    const busy = (status && status.busy) || (view && view.busy);
    if (!busy) return;
    const t = setInterval(reload, 4000);
    return () => clearInterval(t);
  }, [status && status.busy, view && view.busy, reload]);

  const busy = (status && status.busy) || null;
  const patchHousehold = useCallback(async (p) => { try { setHousehold(await api("PATCH", "/api/household", p)); } catch (e) { toast(e.message); } }, []);

  let body;
  if (error) body = html`<div class="screen"><div class="empty span"><b>Can't reach the engine</b><span>${error}</span><button type="button" class="btn" onClick=${reload}>Try again</button></div></div>`;
  else if (!view || !tl) body = html`<div class="screen"><div class="empty span">Loading…</div></div>`;
  else if (hash === "#groceries" && view.run_id == null) body = html`<div class="screen"><div class="empty span"><span class="brand">Groceries</span><span>No run yet. Plan the gaps on the Week screen and the lists appear here.</span><a class="btn" href="#week" style="text-decoration:none">Week</a></div></div>`;
  else if (hash === "#groceries") body = html`<${Groceries} view=${view} reload=${reload} busy=${busy} toast=${toast} pinned=${runId != null} selectRun=${setRunId} />`;
  else if (hash === "#household") body = html`<${Household} household=${household} patch=${patchHousehold} toast=${toast} planner=${status && status.adapters && status.adapters.planner} />`;
  else if (hash === "#connections") body = html`<${Connections} status=${status} household=${household} />`;
  else body = html`<${Timeline} tl=${tl} reload=${reload} busy=${busy} toast=${toast} selectRun=${setRunId} />`;

  return html`<div class="shell">${body}<${Nav} hash=${hash} />${msg ? html`<div class="toast" role="status">${msg}</div>` : null}</div>`;
}

render(html`<${App} />`, document.getElementById("root"));
