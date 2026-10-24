// Znacht app: one page, four screens and a review, no build step. Preact + htm, vendored.
// The screens follow the household's journeys (docs/ux-journey-review.md): glance at tonight,
// plan the gaps, review and approve one proposal, shop the week you are in, adjust the house.
import { html, render, useState, useEffect, useCallback, useRef } from "/app/static/vendor/htm-preact-standalone.module.js?v=1";

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
const dayNum = (iso) => String(Number(iso.slice(8, 10)));
const WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const isoDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const parse = (iso) => new Date(iso.slice(0, 10) + "T12:00:00");
const weekday = (iso) => WD[(parse(iso).getDay() + 6) % 7];
const mondayOf = (iso) => { const d = parse(iso); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return isoDate(d); };
const addDays = (iso, n) => { const d = parse(iso); d.setDate(d.getDate() + n); return isoDate(d); };
function weekName(week, today) {
  const t = mondayOf(today);
  if (week === t) return "This week";
  if (week === addDays(t, 7)) return "Next week";
  if (week === addDays(t, -7)) return "Last week";
  return `Week of ${parse(week).toLocaleDateString("en-GB", { day: "numeric", month: "long" })}`;
}
const STATUS_WORD = { needs_approval: "proposal", needs_input: "needs input", applied: "sent", reverted: "undone" };
const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;

// routes: #week, #groceries, #groceries/12, #review/12, #household, #connections
const useRoute = () => {
  const read = () => {
    const [name, arg] = (location.hash || "#week").slice(1).split("/");
    return { name: name || "week", id: arg ? Number(arg) : null };
  };
  const [route, setRoute] = useState(read);
  useEffect(() => { const f = () => { setRoute(read()); window.scrollTo(0, 0); }; addEventListener("hashchange", f); return () => removeEventListener("hashchange", f); }, []);
  return route;
};
const go = (hash) => { if (location.hash !== hash) location.hash = hash; };

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
    back: html`<path d="M15 5l-7 7 7 7" />`,
    robot: html`<path d="M7 4h10l1 5H6z" /><rect x="5" y="9" width="14" height="11" rx="2" /><path d="M12 13v3" />`,
    spark: html`<path d="M12 3l1.8 4.6L18 9l-4.2 1.4L12 15l-1.8-4.6L6 9l4.2-1.4z" />`,
  };
  return html`<svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${paths[name]}</svg>`;
};

const Nav = ({ route }) => {
  const section = route.name === "review" ? "week" : route.name;
  return html`
  <nav class="nav">
    ${[["week", "week", "Week"], ["groceries", "groceries", "Groceries"], ["household", "household", "Household"], ["connections", "connections", "Connect"]].map(
      ([name, icon, label]) => html`<a href=${"#" + name} class=${section === name ? "on" : ""} aria-current=${section === name ? "page" : null}><${Icon} name=${icon} />${label}</a>`
    )}
  </nav>`;
};

const Back = ({ href, label }) => html`<a class="back" href=${href}><${Icon} name="back" />${label}</a>`;
const Badge = ({ g }) => html`<span class=${"badge g-" + g.coverage}>${g.coverage === "none" ? "no groceries yet" : g.label}</span>`;

// ---------- the day sheet: one dinner, its alternatives, lock ------------------------------
// Used by the Week timeline and the Review. `runId` is the run the swap acts on; a swap
// always makes a new run (a proposal) and hands its id to onSwapped.
function DaySheet({ date, title, runId, locked, children, onClose, onSwapped, onLocked, toast, badge }) {
  const [alts, setAlts] = useState(null);
  const [working, setWorking] = useState(false);
  useEffect(() => {
    setAlts(null);
    if (!runId) return;
    api("GET", `/api/runs/${runId}/alternatives?day=${date}`).then(setAlts).catch((e) => { setAlts([]); toast(e.message); });
  }, [runId, date]);
  useEffect(() => {
    const esc = (e) => { if (e.key === "Escape") onClose(); };
    addEventListener("keydown", esc); return () => removeEventListener("keydown", esc);
  }, [onClose]);

  const swap = async (recipe_id) => {
    setWorking(true);
    try { const v = await api("POST", `/api/runs/${runId}/swap`, { date, recipe_id }); onSwapped(v.run_id); }
    catch (e) { toast(e.message); } finally { setWorking(false); }
  };
  const toggleLock = async () => {
    setWorking(true);
    try { await api("POST", `/api/runs/${runId}/lock`, { date, locked: !locked }); toast(locked ? "Unlocked: plan again may change it." : "Locked: plan again keeps it."); onLocked(); }
    catch (e) { toast(e.message); } finally { setWorking(false); }
  };
  return html`
    <div class="sheet-back" onClick=${(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div class="sheet" role="dialog" aria-modal="true" aria-label=${`${weekday(date)} ${dayNum(date)}`}>
        <div class="handle"></div>
        <div class="sheet-head">
          <div class="sheet-title"><small>${weekday(date)} ${dayNum(date)}</small><b>${title || "Nothing yet"}</b></div>
          <button type="button" class="btn icon" aria-label="Close" onClick=${onClose}><${Icon} name="close" /></button>
        </div>
        ${badge ? html`<div>${badge}</div>` : null}
        ${children}
        ${runId ? (alts == null ? html`<p class="muted">Finding alternatives…</p>` : alts.length === 0 ? html`<p class="muted">Nothing else in this plan's pool fits here.</p>` : html`
          <div class="row between"><h2>Swap for</h2><button type="button" class="link" onClick=${() => swap(alts[Math.floor(Math.random() * alts.length)].recipe_id)} disabled=${working}>Surprise me</button></div>
          ${alts.map((a, j) => html`
            <button type="button" class=${"alt" + (j === 0 ? " best" : "")} onClick=${() => swap(a.recipe_id)} disabled=${working}>
              <span>${a.title}</span>
              <span class="meta">${a.minutes ? `${a.minutes} min · ` : ""}${a.tags.map((t) => t.replace("_", " ")).join(", ")}${a.keeps_rules ? "" : html` · <span class="warn-text">bends a weekly rule</span>`}</span>
            </button>`)}
          <p class="muted small">A swap is a proposal: My Week changes only when you approve it.</p>`) : null}
        ${runId ? html`<div class="row"><button type="button" class=${"btn" + (locked ? " on" : "")} onClick=${toggleLock} disabled=${working}><${Icon} name="lock" />${locked ? "Locked · unlock" : "Lock this dinner"}</button></div>` : null}
      </div>
    </div>`;
}

// ---------- Week: tonight first, then a rolling timeline (ADR-0011) -----------------------
const DAYS = 14;
const SOURCE = (card) => (card.source === "manual" ? "yours in My Week" : `sent by Znacht`);

function DayRow({ d, today, onOpen }) {
  const card = d.dinner || d.proposal;
  const also = d.also || [];
  const cls = `day st-${d.state}${d.date === today ? " today" : ""}${d.dinner && d.dinner.source === "manual" ? " manual" : ""}`;
  const tappable = d.state !== "empty";
  const open = () => tappable && onOpen(d);
  const label = `${d.weekday} ${dayNum(d.date)}: ${card ? card.title : "nothing planned"}${d.state === "proposed" ? ", proposed" : ""}`;
  return html`
    <div class=${cls} role=${tappable ? "button" : null} tabindex=${tappable ? 0 : null} onClick=${open} onKeyDown=${(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } }} aria-label=${label}>
      <div class="date"><small>${d.weekday.toUpperCase()}</small><b>${dayNum(d.date)}</b></div>
      <div class="body">
        ${d.state === "empty" ? html`<span class="title muted">${also.length ? "No dinner yet" : "Nothing yet"}</span>${also.length ? html`<span class="meta">in My Week: ${also.map((a) => a.title).join(", ")}</span>` : null}` :
          d.state === "proposed" ? html`<span class="title">${card.title}</span><span class="meta">proposal · not in My Week yet</span>` :
          html`<span class="title">${card.title}</span>
               <span class="meta">${d.dinner.minutes ? `${d.dinner.minutes} min · ` : ""}${SOURCE(d.dinner)}</span>
               ${also.length ? html`<span class="meta">also ${also.map((a) => a.title).join(", ")}</span>` : null}
               ${d.proposal ? html`<span class="meta proposal">proposal: ${d.proposal.title}</span>` : null}
               ${d.state !== "past" ? html`<span><${Badge} g=${d.groceries} /></span>` : null}`}
      </div>
      ${d.locked ? html`<span class="lock" title="Locked"><${Icon} name="lock" /></span>` : null}
    </div>`;
}

function Tonight({ tl, onOpen }) {
  const d = tl.days.find((x) => x.date === tl.today);
  if (!d) return null;
  const next = tl.days.find((x) => x.date === addDays(tl.today, 1));
  const card = d.dinner || d.proposal;
  const nextCard = next && (next.dinner || next.proposal);
  return html`
    <button type="button" class=${"tonight span st-" + d.state} onClick=${() => card && onOpen(d)} disabled=${!card} aria-label=${`Tonight: ${card ? card.title : "nothing planned"}`}>
      <span class="eyebrow">Tonight · ${d.weekday} ${dayNum(d.date)}</span>
      <span class="dish">${card ? card.title : "Nothing planned"}</span>
      <span class="meta">
        ${d.dinner ? html`${d.dinner.minutes ? `${d.dinner.minutes} min · ` : ""}${SOURCE(d.dinner)} <${Badge} g=${d.groceries} />` :
          d.proposal ? "proposal · not in My Week yet" : "Cook from the pantry, or plan the gaps below."}
      </span>
      ${next ? html`<span class="tomorrow">Tomorrow: <b>${nextCard ? nextCard.title : "nothing yet"}</b>${next.state === "proposed" ? " (proposal)" : ""}</span>` : null}
    </button>`;
}

function Week({ tl, status, reload, busy, toast }) {
  const [open, setOpen] = useState(null);
  const [hideErr, setHideErr] = useState(null);
  const day = open ? tl.days.find((d) => d.date === open) || null : null;
  const card = day ? (day.dinner || day.proposal) : null;

  const planGaps = async (w) => {
    const kept = w.locked_dates.length;
    try {
      await api("POST", "/api/plan_week", { week: w.week, locked_dates: w.locked_dates });
      toast(`Planning the gaps for ${w.label.toLowerCase()}${kept ? `, keeping your ${plural(kept, "dinner")}` : ""}…`);
      await reload();
    } catch (e) { toast(e.message); }
  };

  const upcoming = tl.days.filter((d) => d.state !== "past");
  const planned = upcoming.filter((d) => d.dinner).length;
  const empty = upcoming.filter((d) => d.state === "empty").length;
  const weeks = tl.weeks.map((w) => ({ ...w, days: tl.days.filter((d) => d.week === w.week) }));
  const firstGap = weeks.find((w) => w.days.some((d) => d.state === "empty") && !w.awaiting_run_id);
  const err = status && status.last_error && !busy && hideErr !== status.last_error ? status.last_error : null;
  const errLine = err ? err.split("\n")[0].slice(0, 160) : null;

  return html`
    <div class="screen">
      <div class="top span">
        <span class="brand">Znacht</span>
        <span class="pills">
          <span class=${"pill" + (planned === upcoming.length ? " ok" : "")}>${planned}/${upcoming.length} planned</span>
          ${empty ? html`<span class="pill warn">${empty} empty</span>` : null}
        </span>
      </div>
      ${busy ? html`<div class="banner span" role="status"><span class="spinner" aria-hidden="true"></span><span><b>Znacht is ${busy}…</b><br /><span class="muted small">This takes up to a minute. The proposal appears here when it is ready.</span></span></div>` : null}
      ${err ? html`<div class="banner bad span" role="alert"><span><b>The last plan did not finish.</b><br /><span class="small">${errLine}</span></span><button type="button" class="btn icon" aria-label="Dismiss" onClick=${() => setHideErr(err)}><${Icon} name="close" /></button></div>` : null}
      <${Tonight} tl=${tl} onOpen=${(x) => setOpen(x.date)} />
      ${weeks.map((w) => {
        const proposedHere = w.days.filter((d) => d.proposal && d.state !== "past").length;
        const gaps = w.days.some((d) => d.state === "empty");
        return html`
        <section class="wk span" aria-label=${w.label}>
          <div class="wk-head"><h2>${w.label}</h2><span class="sum">${w.summary}</span></div>
          ${w.my_week_ok ? null : html`<div class="card dashed"><span class="warn-text">My Week could not be read just now; showing what Znacht last sent.</span></div>`}
          ${w.awaiting_run_id ? html`
            <div class="proposal-banner">
              <div><b>${w.awaiting_status === "needs_input" ? "A plan needs your input" : `Znacht proposes ${plural(proposedHere, "dinner")}`}</b>
                <span class="muted small">${w.awaiting_status === "needs_input" ? "It could not keep every rule. Have a look." : "Nothing changes in My Week or Migros until you approve."}</span></div>
              <a class="btn primary" href=${`#review/${w.awaiting_run_id}`}>${w.awaiting_status === "needs_input" ? "Have a look" : "Review"}</a>
            </div>` : null}
          ${w.days.map((d) => html`<${DayRow} key=${d.date} d=${d} today=${tl.today} onOpen=${(x) => setOpen(x.date)} />`)}
          ${gaps ? html`<button type="button" class=${"btn wide" + (w === firstGap ? " primary" : "")} onClick=${() => planGaps(w)} disabled=${!!busy}>
            ${w.awaiting_run_id ? "Plan the gaps again" : "Plan the gaps"}${w.locked_dates.length ? html` <span class="sub">keeps your ${plural(w.locked_dates.length, "dinner")}</span>` : null}</button>` : null}
        </section>`;
      })}
      <p class="span muted small">Dinners come from Cookidoo My Week. Znacht only proposes; nothing changes there until you approve, and every approval shows what it removes first.</p>
      ${day ? html`
        <${DaySheet} date=${day.date} title=${card && card.title} runId=${day.run_id} locked=${day.locked} toast=${toast}
          badge=${day.dinner && day.state !== "past" ? html`<${Badge} g=${day.groceries} />` : null}
          onClose=${() => setOpen(null)}
          onSwapped=${async () => { setOpen(null); toast("Swapped. It is a proposal until you approve it."); await reload(); }}
          onLocked=${reload}>
          ${day.dinner ? html`<p class="muted small">${day.dinner.source === "manual" ? "You put this in My Week. Znacht keeps it when it plans the gaps." : "Znacht put this in My Week."}${day.dinner.note ? ` ${day.dinner.note}` : ""}</p>` : null}
          ${day.proposal ? html`<div class="swap"><b>Proposal</b> ${day.proposal.title}<div class="meta">${day.dinner ? "replaces the dinner above when approved" : "not in My Week until approved"}</div></div>` : null}
          ${card && card.url ? html`<a href=${card.url} target="_blank" rel="noopener" class="small">Open the recipe</a>` : null}
          ${(day.also || []).length ? html`<div class="stack"><h2>Also in My Week that day</h2><div class="chips">${day.also.map((a) => html`<span class="chip quiet">${a.title}${a.breakfast ? " · breakfast" : ""}</span>`)}</div></div>` : null}
          ${day.proposal ? html`<a class="btn primary" href=${`#review/${day.proposal.source}`}>Review the proposal</a>` : null}
          ${!day.run_id && day.dinner ? html`<p class="muted small">To change it, edit My Week in Cookidoo or plan this week again.</p>` : null}
        </${DaySheet}>` : null}
    </div>`;
}

// ---------- Review: one run, its dinners, its money, one Approve ---------------------------
function useRunView(runId, tick) {
  const [view, setView] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    if (!runId) { setView(null); return; }
    let live = true;
    api("GET", `/api/runs/${runId}/view`).then((v) => { if (live) { setView(v); setErr(null); } }).catch((e) => live && setErr(e.message));
    return () => { live = false; };
  }, [runId, tick]);
  return [view && view.run_id === runId ? view : null, err];
}

function Basket({ m }) {
  const total = Number(m.online_subtotal), min = Number(m.minimum_order);
  const pct = min > 0 ? Math.min(100, Math.round((total / min) * 100)) : 100;
  return html`
    <div class="card span">
      <div class="row between small"><span class="muted">Online basket</span><b>${chf(total)} <span class="muted" style="font-weight:400">of ${chf(min)} minimum</span></b></div>
      <div class="bar" role="progressbar" aria-valuenow=${pct} aria-valuemin="0" aria-valuemax="100" aria-label="Online basket towards the minimum"><div style=${`width:${pct}%;background:${m.meets_minimum ? "var(--ok)" : "var(--accent)"}`}></div></div>
      <span class=${(m.meets_minimum ? "ok-text" : "warn-text") + " small"} style="font-weight:600">${m.meets_minimum ? `Minimum met${Number(m.deposit) > 0 ? ` · plus ${chf(m.deposit)} box deposit for frozen items` : ""}` : `${chf(m.shortfall)} short: move something from the store run, or add what you need`}</span>
    </div>`;
}

function Review({ runId, tick, reload, busy, toast, runs }) {
  const [view, err] = useRunView(runId, tick);
  const [open, setOpen] = useState(null);
  const [working, setWorking] = useState(false);
  if (err) return html`<div class="screen"><${Back} href="#week" label="Week" /><div class="empty span"><b>Can't open this plan</b><span>${err}</span></div></div>`;
  if (!view) return html`<div class="screen"><${Back} href="#week" label="Week" /><div class="empty span">Loading the plan…</div></div>`;

  const newer = (runs || []).find((r) => r.week === view.week && r.id > view.run_id);
  const d = open ? view.dinners.find((x) => x.date === open) : null;
  const m = view.money;
  const proposal = view.status === "needs_approval" || view.status === "needs_input";

  const approve = async () => {
    if (!confirm(`Send ${plural(view.dinners.length, "dinner")} to My Week and the groceries to your Migros lists?${view.plan_removes.length ? `\n\nThis removes ${plural(view.plan_removes.length, "dinner")} already in My Week.` : ""}\n\nNothing is ordered or paid.`)) return;
    setWorking(true);
    try { await api("POST", `/api/apply?run_id=${view.run_id}`); toast("Sent to My Week and Migros. Finish the order when you're ready."); await reload(); }
    catch (e) { toast(e.message); } finally { setWorking(false); }
  };
  const revert = async () => {
    if (!confirm("Undo this plan? Its dinners leave My Week and its items leave both Migros lists.")) return;
    setWorking(true);
    try { await api("POST", `/api/runs/${view.run_id}/revert`); toast("Undone."); await reload(); }
    catch (e) { toast(e.message); } finally { setWorking(false); }
  };
  const replan = async () => {
    setWorking(true);
    try { await api("POST", `/api/runs/${view.run_id}/replan`); toast("Planning again, keeping the locked dinners…"); go("#week"); await reload(); }
    catch (e) { toast(e.message); } finally { setWorking(false); }
  };

  return html`
    <div class="screen with-bar">
      <div class="span"><${Back} href="#week" label="Week" /></div>
      <div class="top span">
        <div class="stack"><span class="brand">${weekName(view.week, isoDate(new Date()))}</span><span class="muted small">${view.week_label}${view.slot ? ` · delivery ${view.slot}` : ""}</span></div>
        <span class=${"pill" + (view.status === "applied" ? " ok" : view.status === "needs_input" ? " warn" : "")}>${STATUS_WORD[view.status] || view.status}</span>
      </div>
      ${newer && proposal ? html`<div class="banner span"><span>There is a newer plan for this week.</span><a class="btn" href=${`#review/${newer.id}`}>Open it</a></div>` : null}
      ${view.chef_note && view.theme !== "rule-based" ? html`<div class="span stack"><b>${view.theme}</b><p class="small">${view.chef_note}</p></div>` : null}
      ${view.violations.length ? html`<div class="card dashed span"><h2>Needs your input</h2>${view.violations.map((v) => html`<div class="warn-text small">${v}</div>`)}<p class="muted small">Swap a dinner below, change a rule on Household, or plan again.</p></div>` : null}
      ${view.plan_removes.length && proposal ? html`
        <div class="card dashed span">
          <h2>Approving removes from My Week</h2>
          ${view.plan_removes.map((r) => html`<div class="warn-text small">${r}</div>`)}
        </div>` : null}
      <div class="card span">
        <div class="row between"><h2>${plural(view.dinners.length, "dinner")}</h2>${proposal ? html`<span class="muted small">tap one to swap or lock it</span>` : null}</div>
        ${view.dinners.map((x) => html`
          <button type="button" class="dish-row" onClick=${() => setOpen(x.date)} disabled=${!proposal} aria-label=${`${x.weekday} ${dayNum(x.date)}: ${x.title}`}>
            <span class="date"><small>${x.weekday.slice(0, 3).toUpperCase()}</small><b>${dayNum(x.date)}</b></span>
            <span class="body"><span class="title">${x.title}</span>
              <span class="meta">${[x.minutes ? `${x.minutes} min` : null, x.cost_per_person ? `${chf(x.cost_per_person)} p.p.` : null, x.in_store_day ? "before the delivery: store run" : null].filter(Boolean).join(" · ")}</span></span>
            ${x.locked ? html`<span class="lock" title="Locked"><${Icon} name="lock" /></span>` : null}
          </button>`)}
      </div>
      <${Basket} m=${m} />
      <a class="card span link-card" href=${`#groceries/${view.run_id}`}>
        <span><b>Groceries</b><br /><span class="muted small">${view.online.length} online · ${view.in_store.length + view.free_text.length} on the store run (${chf(m.in_store_total)})${Number(m.savings) > 0 ? ` · saves ${chf(m.savings)}` : ""}</span></span>
        <span aria-hidden="true" class="chev">›</span>
      </a>
      ${view.swaps.length ? html`<div class="card span"><h2>Product swaps and flags</h2>${view.swaps.map((s) => html`<div class=${"swap " + s.kind}><b>${s.need}</b> → ${s.chosen}${s.delta ? html` <span class=${s.kind === "switch" ? "ok-text" : "warn-text"}>(${Number(s.delta) < 0 ? "−" : "+"}${Math.abs(Number(s.delta)).toFixed(2)})</span>` : null}<div class="meta">${s.reason}</div></div>`)}</div>` : null}
      ${view.pantry_check.length ? html`<div class="card span"><h2>Check the pantry</h2><p class="small">The recipes assume you have these; nothing is bought.</p><div class="chips">${view.pantry_check.map((p) => html`<span class="chip quiet">${p}</span>`)}</div></div>` : null}
      <div class="actionbar">
        ${view.status === "needs_approval" ? html`<button type="button" class="btn primary" onClick=${approve} disabled=${working || !!busy}>${working ? "Sending…" : "Approve and send"}</button>` : null}
        ${view.status === "needs_input" ? html`<button type="button" class="btn primary" onClick=${replan} disabled=${working || !!busy}>Plan again</button>` : null}
        ${view.status === "applied" ? html`
          ${view.checkout_url ? html`<a class="btn primary" href=${view.checkout_url} target="_blank" rel="noopener">Finish the order in Migros</a>` : html`<a class="btn primary" href=${`#groceries/${view.run_id}`}>Shopping list</a>`}
          <button type="button" class="btn ghost" onClick=${revert} disabled=${working || !!busy}>Undo</button>` : null}
        ${view.status === "reverted" ? html`<span class="muted small">This plan was undone. Plan the gaps on Week to start again.</span>` : null}
      </div>
      ${d ? html`
        <${DaySheet} date=${d.date} title=${d.title} runId=${view.run_id} locked=${d.locked} toast=${toast}
          onClose=${() => setOpen(null)}
          onSwapped=${(id) => { setOpen(null); toast("Swapped. Review the new plan."); location.replace(`#review/${id}`); reload(); }}
          onLocked=${reload}>
          ${d.note ? html`<p class="muted small">${d.note}</p>` : null}
          ${d.url ? html`<a href=${d.url} target="_blank" rel="noopener" class="small">Open the recipe</a>` : null}
        </${DaySheet}>` : null}
    </div>`;
}

// ---------- Groceries: the list for the week you are shopping ------------------------------
function Groceries({ runId, tick, reload, busy, toast, runs, today }) {
  const [tab, setTab] = useState("online");
  const [text, setText] = useState("");
  const [view, err] = useRunView(runId, tick);
  if (!runId) return html`<div class="screen"><div class="empty span"><span class="brand">Groceries</span><span>No plan yet. Plan the gaps on the Week screen and the lists appear here.</span><a class="btn" href="#week">Go to Week</a></div></div>`;
  if (err) return html`<div class="screen"><div class="empty span"><b>Can't open these groceries</b><span>${err}</span><a class="btn" href="#groceries">Back</a></div></div>`;
  if (!view) return html`<div class="screen"><div class="empty span">Loading the lists…</div></div>`;

  const applied = view.status === "applied";
  const todo = view.todo || { online: [], in_store: [] };
  const done = new Set([...(todo.online || []), ...(todo.in_store || [])].filter((i) => i.done).map((i) => i.uid));
  // the runs worth switching between, from this week on: per week the list that was sent
  // (what you shop with) and a newer proposal if there is one
  const thisWeek = mondayOf(today);
  const choices = [];
  for (const r of runs || []) {
    if (r.week < thisWeek) continue;
    const same = choices.filter((c) => c.week === r.week);
    if (r.status === "applied" ? !same.some((c) => c.status === "applied") : same.length === 0) choices.push(r);
  }
  if (!choices.some((c) => c.id === view.run_id)) choices.push({ id: view.run_id, week: view.week, status: view.status });
  choices.sort((a, b) => (a.week < b.week ? -1 : a.week > b.week ? 1 : b.id - a.id));

  const move = async (need, to) => {
    try {
      const v = await api("POST", `/api/runs/${view.run_id}/move`, { need, to });
      toast(`Moved ${need} ${to === "online" ? "online" : "to the store run"}. ${applied ? "That makes a new proposal; approve it to update the lists." : ""}`);
      location.replace(`#groceries/${v.run_id}`); reload();
    } catch (e) { toast(e.message); }
  };
  const tick_ = async (kind, uid, isDone) => {
    try { await api("POST", `/api/lists/${kind}/done?run_id=${view.run_id}`, { uid, done: !isDone }); reload(); } catch (e) { toast(e.message); }
  };
  const add = async () => {
    if (!text.trim()) return;
    try { await api("POST", `/api/lists/in_store/items?run_id=${view.run_id}`, { summary: text.trim() }); setText(""); toast("Added to the store run."); setTab("store"); reload(); } catch (e) { toast(e.message); }
  };

  const Line = ({ it, kind }) => {
    const uid = `${kind}:${it.product_id}`; const isDone = done.has(uid);
    return html`
      <div class=${"line" + (isDone ? " done" : "")}>
        ${applied ? html`<button type="button" class=${"check" + (isDone ? " on" : "")} aria-pressed=${isDone} aria-label=${`${it.name}: ${isDone ? "bought" : "not bought"}`} onClick=${() => tick_(kind, uid, isDone)}><${Icon} name="check" /></button>` : null}
        <div class="body">
          <span class="name">${it.packs > 1 ? html`<span class="muted">${it.packs}× </span>` : null}${it.name}</span>
          <span class=${"note" + (it.deliverable === false || it.flagged ? " flag" : "")}>${it.need} · ${it.pack}${it.deliverable === false ? " · not deliverable" : ""}${it.switched ? " · swapped" : ""}${it.flagged ? " · healthier option costs more" : ""}</span>
        </div>
        <span class="price">${chf(it.price)}</span>
        ${kind === "online" ? html`<button type="button" class="mv" aria-label=${`Move ${it.need} to the store run`} onClick=${() => move(it.need, "store")} disabled=${!!busy}><${Icon} name="move" />store</button>` :
          it.movable ? html`<button type="button" class="mv" aria-label=${`Move ${it.need} online`} onClick=${() => move(it.need, "online")} disabled=${!!busy}><${Icon} name="move" />online</button>` : null}
      </div>`;
  };
  const sinkDone = (kind) => (a, b) => Number(done.has(`${kind}:${a.product_id}`)) - Number(done.has(`${kind}:${b.product_id}`));
  const aisles = [];
  for (const it of view.in_store) { let g = aisles.find((a) => a.name === it.aisle); if (!g) aisles.push((g = { name: it.aisle, lines: [] })); g.lines.push(it); }
  const extras = (todo.in_store || []).filter((i) => i.uid.startsWith("text:"));
  const left = (lines, kind) => lines.filter((it) => !done.has(`${kind}:${it.product_id}`)).length;
  const storeLeft = left(view.in_store, "in_store") + extras.filter((i) => !i.done).length;

  return html`
    <div class="screen">
      <div class="top span"><span class="brand">Groceries</span>${view.slot ? html`<span class="pill quiet">Delivery ${view.slot}</span>` : null}</div>
      ${choices.length > 1 ? html`<div class="chips span" role="tablist" aria-label="Which week">${choices.map((c) => html`
        <a role="tab" aria-selected=${c.id === view.run_id} class=${"chip big" + (c.id === view.run_id ? " on" : "")} href=${`#groceries/${c.id}`}>${weekName(c.week, today)} · ${STATUS_WORD[c.status] || c.status}</a>`)}</div>` : null}
      ${applied ? html`
        <div class="banner ok span"><span><b>On your Migros lists.</b><br /><span class="small">Znacht never orders or pays: finish the order in Migros.</span></span>${view.checkout_url ? html`<a class="btn" href=${view.checkout_url} target="_blank" rel="noopener">Open Migros</a>` : null}</div>` :
        view.status === "reverted" ? html`<div class="banner span"><span>This plan was undone; nothing of it is on your lists.</span></div>` : html`
        <div class="banner span"><span><b>Proposal, not sent yet.</b><br /><span class="small muted">Nothing is on your Migros lists until you approve.</span></span><a class="btn primary" href=${`#review/${view.run_id}`}>Review</a></div>`}
      <${Basket} m=${view.money} />
      <div class="tabs span" role="tablist">
        <button type="button" role="tab" aria-selected=${tab === "online"} class=${"tab" + (tab === "online" ? " on" : "")} onClick=${() => setTab("online")}>Online · ${applied ? left(view.online, "online") : view.online.length}</button>
        <button type="button" role="tab" aria-selected=${tab === "store"} class=${"tab" + (tab === "store" ? " on" : "")} onClick=${() => setTab("store")}>Store run · ${applied ? storeLeft : view.in_store.length + extras.length}</button>
      </div>
      <div class="list span">
        ${tab === "online" ? [...view.online].sort(sinkDone("online")).map((it) => html`<${Line} key=${it.product_id + it.needed_on} it=${it} kind="online" />`) : html`
          ${aisles.map((a) => html`<h2 class="aisle">${a.name}</h2>${[...a.lines].sort(sinkDone("in_store")).map((it) => html`<${Line} key=${it.product_id + it.needed_on} it=${it} kind="in_store" />`)}`)}
          ${extras.length ? html`<h2 class="aisle">Also</h2>${extras.map((i) => html`
            <div class=${"line" + (i.done ? " done" : "")}>
              <button type="button" class=${"check" + (i.done ? " on" : "")} aria-pressed=${i.done} aria-label=${`${i.summary}: ${i.done ? "bought" : "not bought"}`} onClick=${() => tick_("in_store", i.uid, i.done)}><${Icon} name="check" /></button>
              <div class="body"><span class="name">${i.summary}</span><span class="note">your own item</span></div>
            </div>`)}` : null}
          ${!view.in_store.length && !extras.length ? html`<p class="muted small">Nothing for the store run.</p>` : null}`}
        ${tab === "online" && !view.online.length ? html`<p class="muted small">Nothing online this week.</p>` : null}
      </div>
      <div class="card">
        <h2>Add to the store run</h2>
        <div class="row">
          <input id="free" class="input" placeholder="birthday candles, cat food…" aria-label="Add to the store run" value=${text} onInput=${(e) => setText(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && add()} />
          <button type="button" class="btn" onClick=${add} disabled=${!text.trim()}>Add</button>
        </div>
      </div>
      ${view.pantry_check.length ? html`<div class="card"><h2>Check the pantry</h2><p class="small">The recipes assume you have these; nothing is bought.</p><div class="chips">${view.pantry_check.map((p) => html`<span class="chip quiet">${p}</span>`)}</div></div>` : null}
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
  if (!household) return html`<div class="screen"><div class="empty span">Loading the household…</div></div>`;
  const colors = ["var(--accent)", "var(--ok)", "var(--lilac)", "#ffd166"];
  const tags = ["fish", "legumes", "red_meat", "poultry", "vegetarian"];
  const setRule = (tag, n) => patch({ rules: { min_per_week: { [tag]: Math.max(0, n) } } });
  const setMax = (tag, n) => patch({ rules: { max_per_week: { [tag]: n } } });
  const members = household.members;
  const updateMember = (i, changes) => patch({ members: members.map((m, j) => (j === i ? { ...m, ...changes } : m)) });
  const photo = async (file) => {
    if (!file) return;
    setBusyPhoto(true);
    try {
      const fd = new FormData(); fd.append("file", file);
      const res = await fetch("/api/pantry/photo", { method: "POST", headers: { Authorization: `Bearer ${token()}` }, body: fd });
      if (!res.ok) { let msg = res.statusText; try { msg = (await res.json()).detail || msg; } catch (e) { /* not json */ } throw new Error(msg); }
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
      <p class="span muted small">Changes save as you make them, into your household file, and shape the next plan.</p>
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
        <h2>Every week, at least</h2>
        ${tags.map((t) => { const n = household.rules.min_tags[t] || 0; const mx = household.rules.max_tags[t]; return html`<div class="stepper"><span style="flex:1 1 auto;font-weight:500">${t.replace("_", " ")}</span>
          <button type="button" class="check" aria-label=${"Fewer " + t} onClick=${() => setRule(t, n - 1)} disabled=${n <= 0}>−</button><span class="n">${n}×</span><button type="button" class="check" aria-label=${"More " + t} onClick=${() => setRule(t, n + 1)}>+</button>
          <button type="button" class=${"btn ghost maxbtn" + (mx != null ? " on" : "")} aria-pressed=${mx != null} onClick=${() => setMax(t, mx != null ? 0 : Math.max(n, 1))}>${mx != null ? `max ${mx}` : "no max"}</button></div>`; })}
        <div style="display:flex;flex-direction:column;gap:6px"><span class="muted" style="font-size:12px">Never in a recipe</span>
          <${Chips} items=${household.rules.banned_ingredients} placeholder="banned…" onAdd=${(x) => patch({ rules: { banned_ingredients: [...household.rules.banned_ingredients, x] } })} onRemove=${(x) => patch({ rules: { banned_ingredients: household.rules.banned_ingredients.filter((d) => d !== x) } })} /></div>
        <div class="stepper"><span style="flex:1 1 auto;font-weight:500">Weekday cooking time</span><button type="button" class="check" aria-label="Shorter weekday limit" onClick=${() => patch({ rules: { max_total_minutes_weekday: Math.max(15, (household.rules.max_total_minutes_weekday || 60) - 15) } })}>−</button><span class="n" style="width:auto">${household.rules.max_total_minutes_weekday || "—"} min</span><button type="button" class="check" aria-label="Longer weekday limit" onClick=${() => patch({ rules: { max_total_minutes_weekday: (household.rules.max_total_minutes_weekday || 45) + 15 } })}>+</button></div>
      </div>
      <div class="card">
        <h2>Health</h2>
        ${household.health.rules.length ? html`<${Chips} items=${household.health.rules} placeholder="add a rule in words…" onAdd=${(x) => patch({ health: { rules: [...household.health.rules, x] } })} onRemove=${(x) => patch({ health: { rules: household.health.rules.filter((r) => r !== x) } })} />` : html`<p class="muted" style="font-size:13px">No health rules yet. Type one in your own words, or read a lab report with <code>znacht extract lab</code> and confirm the draft.</p><${Chips} items=${[]} placeholder="e.g. limit added sugar" onAdd=${(x) => patch({ health: { rules: [x] } })} onRemove=${() => {}} />`}
      </div>
      <div class="card">
        <div class="top"><h2>Pantry</h2>
          ${planner === "anthropic" ? html`<label class="btn primary" style="flex:0 0 auto;padding:8px 14px;min-height:36px;font-size:12px;cursor:pointer">${busyPhoto ? "Reading photo…" : "Add from a photo"}<input type="file" accept="image/*" capture="environment" style="display:none" onChange=${(e) => { photo(e.target.files[0]); e.target.value = ""; }} disabled=${busyPhoto} /></label>` : null}</div>
        ${draft ? html`<div class="card dashed"><h2>From the photo: keep what is right</h2>
          ${draft.map((i, k) => html`<div class="line"><button type="button" class=${"check" + (i.keep ? " on" : "")} aria-pressed=${i.keep} aria-label=${`Keep ${i.name}`} onClick=${() => setDraft(draft.map((d, j) => (j === k ? { ...d, keep: !d.keep } : d)))}><${Icon} name="check" /></button><div class="body"><span class="name">${i.name}</span><span class="note">${i.quantity} · ${Math.round(i.confidence * 100)}% sure</span></div></div>`)}
          <div class="row"><button type="button" class="btn primary" onClick=${confirmDraft}>Save to pantry</button><button type="button" class="btn ghost" onClick=${() => setDraft(null)}>Discard</button></div></div>` : null}
        <${Chips} items=${household.pantry.map((p) => `${p.name} ${p.quantity}`)} placeholder="add: rice 1 kg" onAdd=${(x) => { const m = x.match(/^(.+?)\s+(\d[\d.,]*\s*\S*)$/); if (m) patch({ pantry: { [m[1].trim()]: m[2].trim() } }); else toast("Write it as name and amount, e.g. rice 1 kg"); }} onRemove=${(x) => { const name = household.pantry.find((p) => `${p.name} ${p.quantity}` === x); if (name) patch({ pantry: { [name.name]: "0" } }); }} />
        ${planner !== "anthropic" ? html`<p class="muted" style="font-size:12px">Reading the pantry from a photo needs the Claude planner.</p>` : null}
        <div style="font-size:13px">Made at home, never bought: <span class="muted">${household.make_at_home.join(", ") || "nothing yet (edit in the YAML)"}</span></div>
      </div>
      <div class="card">
        <h2>Delivery and store</h2>
        <div style="font-size:13px">Postcode <b>${household.delivery.postcode}</b>${household.store_lists ? html` · online list <b>${household.store_lists.online}</b> · store list <b>${household.store_lists.in_store}</b>` : null}</div>
      </div>
    </div>`;
}

// ---------- Connections -----------------------------------------------------------------
function Connections({ status, household }) {
  const adapters = (status && status.adapters) || {};
  const card = (icon, title, sub, on) => html`<div class="conn"><div class="ico"><${Icon} name=${icon} /></div><div style="flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:2px"><b style="font-size:15px">${title}</b><span class="muted" style="font-size:12px">${sub}</span></div><span class=${"dot" + (on ? "" : " off")} role="img" aria-label=${on ? "Connected" : "Not connected"}></span></div>`;
  const min = status && status.minimum_order;
  return html`
    <div class="screen">
      <div class="top span"><span class="brand">Connections</span></div>
      <p class="span">Where recipes come from, where the plan goes, where the food is bought. Each is a plug-in; the week does not care which.</p>
      <div style="display:flex;flex-direction:column;gap:8px"><h2>Cooking</h2>
        ${card("robot", "Thermomix · Cookidoo", adapters.recipes === "cookidoo" ? "recipes and My Week" : "not connected: recipes from the sample catalogue", adapters.recipes === "cookidoo")}
        ${card("week", "Home Assistant", "calendar, lists, tonight's dinner, this app", true)}
        <div class="card dashed"><b style="font-size:14px;color:var(--soft)">Mealie · Tandoor · Monsieur Cuisine · Cookit</b><span class="muted" style="font-size:12px">adapters anyone can add; the first two have real APIs</span></div>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px"><h2>Shopping</h2>
        ${card("groceries", "Migros", adapters.store === "migros" ? [household ? `delivery to ${household.delivery.postcode}` : null, min ? `minimum order ${chf(min)}` : null].filter(Boolean).join(" · ") : "not connected: sample products and prices", adapters.store === "migros")}
        <div class="card dashed"><b style="font-size:14px;color:var(--soft)">Coop · Farmy · Aldi · Lidl</b><span class="muted" style="font-size:12px">compare the same basket across shops</span></div>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px"><h2>Planner</h2>
        ${card("spark", adapters.planner === "anthropic" ? "Claude plans, the rules decide" : "Rule-based planner", "every plan is checked; every write needs your tap", true)}
      </div>
      <div class="card"><h2>Since the start</h2><span class="big">${chf((status && status.lifetime_savings) || 0)} saved</span><span class="muted" style="font-size:12px">by healthier-or-equal, cheaper product swaps, counted on approved weeks</span></div>
    </div>`;
}

// ---------- App shell -------------------------------------------------------------------
function App() {
  const route = useRoute();
  const [tl, setTl] = useState(null);
  const [status, setStatus] = useState(null);
  const [runs, setRuns] = useState(null);
  const [household, setHousehold] = useState(null);
  const [tick, setTick] = useState(0); // bumps to make the run views refetch
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const timer = useRef(null);
  const toast = useCallback((t) => { clearTimeout(timer.current); setMsg(t); timer.current = setTimeout(() => setMsg(null), 4000); }, []);

  const reload = useCallback(async () => {
    try {
      const [s, t, r] = await Promise.all([api("GET", "/api/status"), api("GET", `/api/timeline?days=${DAYS}`), api("GET", "/api/runs")]);
      setStatus(s); setTl(t); setRuns(r); setError(null); setTick((n) => n + 1);
    } catch (e) { setError(e.message); }
  }, []);
  useEffect(() => { api("GET", "/api/household").then(setHousehold).catch(() => {}); }, []);
  useEffect(() => { reload(); }, [reload]);

  // while the engine works, poll; when it stops, say what came of it
  const busy = (status && status.busy) || null;
  const wasBusy = useRef(null);
  useEffect(() => {
    if (busy) { wasBusy.current = { busy, run: status.run_id }; const t = setInterval(reload, 3000); return () => clearInterval(t); }
    if (wasBusy.current && status) {
      const before = wasBusy.current; wasBusy.current = null;
      if (before.busy === "planning" && status.run_id !== before.run && !status.last_error) toast(status.plan_status === "needs_input" ? "The plan needs your input." : "A new proposal is ready to review.");
    }
  }, [busy, reload]);
  // coming back to the tab (or the HA panel) after a while: refresh
  useEffect(() => {
    const f = () => { if (document.visibilityState === "visible") reload(); };
    document.addEventListener("visibilitychange", f); return () => document.removeEventListener("visibilitychange", f);
  }, [reload]);

  const patchHousehold = useCallback(async (p) => { try { setHousehold(await api("PATCH", "/api/household", p)); } catch (e) { toast(e.message); } }, []);

  let body;
  if (error && !tl) body = html`<div class="screen"><div class="empty span"><b>Can't reach the engine</b><span>${error}</span><button type="button" class="btn" onClick=${reload}>Try again</button></div></div>`;
  else if (!tl || !status) body = html`<div class="screen"><div class="empty span">Loading…</div></div>`;
  else if (route.name === "review" && route.id) body = html`<${Review} runId=${route.id} tick=${tick} reload=${reload} busy=${busy} toast=${toast} runs=${runs} />`;
  else if (route.name === "groceries") body = html`<${Groceries} runId=${route.id || status.shopping_run_id} tick=${tick} reload=${reload} busy=${busy} toast=${toast} runs=${runs} today=${tl.today} />`;
  else if (route.name === "household") body = html`<${Household} household=${household} patch=${patchHousehold} toast=${toast} planner=${status.adapters && status.adapters.planner} />`;
  else if (route.name === "connections") body = html`<${Connections} status=${status} household=${household} />`;
  else body = html`<${Week} tl=${tl} status=${status} reload=${reload} busy=${busy} toast=${toast} />`;

  return html`<div class="shell">
    ${error && tl ? html`<div class="offline" role="alert">Can't reach the engine just now. <button type="button" class="link" onClick=${reload}>Retry</button></div>` : null}
    ${body}<${Nav} route=${route} />${msg ? html`<div class="toast" role="status">${msg}</div>` : null}</div>`;
}

render(html`<${App} />`, document.getElementById("root"));
