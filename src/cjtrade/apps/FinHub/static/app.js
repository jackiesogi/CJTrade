/* FinHub console.
 *
 * Every request here goes to FinHub. Nothing on this page knows the engine's
 * port or the broker's, and that is the point: those two APIs stay on loopback
 * with no CORS header, and FinHub does the talking server-side. If you find
 * yourself adding a fetch() to another origin, that is the design being
 * undone -- add a route to main.py instead.
 */
'use strict';

const TOKEN_KEY = 'finhub_token';
const POLL_MS = 2000;

let pollTimer = null;
let equityChart = null;
let botChart = null;
let kbarsChart = null;
let selectedRunId = null;
let openBotId = null;
let lastStatus = null;

/* ── auth & transport ─────────────────────────────────────────────────────── */

function token() { return localStorage.getItem(TOKEN_KEY); }

function logout() {
    localStorage.removeItem(TOKEN_KEY);
    window.location.href = '/login';
}

async function api(path, options = {}) {
    const headers = Object.assign(
        { 'Authorization': `Bearer ${token()}` }, options.headers || {});
    if (options.body && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
    }
    const res = await fetch(path, Object.assign({}, options, { headers }));
    if (res.status === 401) { logout(); throw new Error('session expired'); }
    const text = await res.text();
    let body;
    try { body = text ? JSON.parse(text) : null; } catch (e) { body = text; }
    if (!res.ok) {
        const detail = (body && body.detail) || body || `HTTP ${res.status}`;
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return body;
}

async function apiText(path) {
    const res = await fetch(path, { headers: { 'Authorization': `Bearer ${token()}` } });
    if (res.status === 401) { logout(); throw new Error('session expired'); }
    return res.text();
}

/* ── formatting ───────────────────────────────────────────────────────────── */

const nf = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

function num(v, digits = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return '—';
    return Number(v).toLocaleString('en-US',
        { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function int(v) { return (v === null || v === undefined) ? '—' : nf.format(v); }
function pct(v) { return (v === null || v === undefined) ? '—' : `${Number(v).toFixed(2)}%`; }
function esc(s) {
    return String(s === null || s === undefined ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}
function shortTime(iso) {
    if (!iso) return '—';
    return String(iso).replace('T', ' ').slice(0, 19);
}
function duration(seconds) {
    if (seconds === null || seconds === undefined) return '—';
    const s = Math.floor(seconds);
    if (s < 60) return `${s}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

/* Taiwan convention: gains are red, losses are green. Inverted from most
 * Western platforms, and the shell's lspos already does it this way, so the UI
 * matching the shell matters more than matching other dashboards. */
function pnlClass(v) {
    if (v === null || v === undefined || Number(v) === 0) return 'text-slate-500';
    return Number(v) > 0 ? 'text-rose-600' : 'text-emerald-600';
}
function signed(v, digits = 2) {
    if (v === null || v === undefined) return '—';
    return (Number(v) > 0 ? '+' : '') + num(v, digits);
}

function toast(message, kind = 'info') {
    const colours = {
        info: 'bg-slate-900', ok: 'bg-emerald-600',
        warn: 'bg-amber-600', error: 'bg-red-600',
    };
    const el = document.createElement('div');
    el.className = `${colours[kind]} text-white text-xs font-bold px-4 py-3 ` +
                   `rounded-xl shadow-lg max-w-sm`;
    el.textContent = message;
    document.getElementById('toast').appendChild(el);
    setTimeout(() => el.remove(), kind === 'error' ? 8000 : 4000);
}

function emptyRow(tbody, colspan, message) {
    tbody.innerHTML = `<tr><td colspan="${colspan}" class="px-6 py-8 text-center text-slate-400 text-sm">${esc(message)}</td></tr>`;
}

/* ── navigation ───────────────────────────────────────────────────────────── */

const PAGES = ['dashboard', 'runs', 'bots', 'positions', 'orders', 'market',
               'trade', 'editor', 'audit'];

function showSection(page, push = true) {
    if (!PAGES.includes(page)) page = 'dashboard';
    PAGES.forEach(p => {
        const section = document.getElementById(`section-${p}`);
        const nav = document.getElementById(`nav-${p}`);
        if (section) section.classList.toggle('hidden', p !== page);
        if (nav) nav.classList.toggle('nav-active', p === page);
    });
    if (push) history.pushState({ page }, '', `/${page}`);
    if (window.innerWidth < 1024) closeSidebar();
    loadSection(page);
}

function loadSection(page) {
    if (page === 'runs') { loadRuns(); }
    else if (page === 'bots') { loadBots(); }
    else if (page === 'positions') { loadAccount(); }
    else if (page === 'orders') { loadOrders(); loadManualOrders(); }
    else if (page === 'market') { loadClock(); }
    else if (page === 'trade') { loadMarketStatus(); }
    else if (page === 'editor') { loadStrategies(); }
    else if (page === 'audit') { loadAudit(); }
}

function currentPage() {
    const first = window.location.pathname.replace(/^\//, '').split('/')[0];
    return PAGES.includes(first) ? first : 'dashboard';
}

function toggleSidebar() {
    const bar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    const open = bar.classList.toggle('active');
    bar.classList.toggle('-translate-x-full', !open);
    overlay.classList.toggle('hidden', !open);
    overlay.classList.toggle('active', open);
}
function closeSidebar() {
    const bar = document.getElementById('sidebar');
    if (!bar.classList.contains('active')) return;
    toggleSidebar();
}

/* ── dashboard ────────────────────────────────────────────────────────────── */

async function refreshAll() {
    await Promise.allSettled([loadStatus(), loadEquity(), loadRoundTrips(),
                              loadBrokerLamp()]);
}

function setLamp(id, state) {
    const colours = { up: 'bg-emerald-500', down: 'bg-slate-300',
                      warn: 'bg-amber-500' };
    const el = document.getElementById(id);
    if (el) el.className = `w-2 h-2 rounded-full ${colours[state] || colours.down}`;
}

async function loadBrokerLamp() {
    try {
        const body = await api('/api/v1/broker/health');
        if (!body.available) { setLamp('lampBroker', 'down'); return; }
        setLamp('lampBroker',
                body.data_readiness === 'all_set' ? 'up' : 'warn');
    } catch (e) { setLamp('lampBroker', 'down'); }
}

async function loadStatus() {
    let body;
    try { body = await api('/api/v1/engine/status'); }
    catch (e) { setLamp('lampEngine', 'down'); return; }

    if (!body.available) {
        setLamp('lampEngine', 'down');
        lastStatus = null;
        renderNoRun(body.supervisor);
        return;
    }
    setLamp('lampEngine', 'up');
    lastStatus = body.status;
    renderStatus(body.status, body.supervisor);
}

function renderNoRun() {
    document.getElementById('dashSubtitle').textContent = 'No run in flight';
    document.getElementById('progressLabel').textContent = '—';
    document.getElementById('progressBar').style.width = '0%';
    ['progMarketTime', 'progClock', 'progSession', 'progUptime',
     'kpiEquity', 'kpiPnl', 'kpiPnlPct', 'kpiTrips', 'kpiWinRate',
     'kpiRisk', 'kpiRiskNote'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = '—';
    });
    document.getElementById('sidebarRun').textContent = 'None';
    document.getElementById('sidebarProgress').style.width = '0%';
    document.getElementById('sidebarStopBtn').classList.add('hidden');
    document.getElementById('dashBotCards').innerHTML =
        '<p class="text-sm text-slate-400">Start a run to see its bots.</p>';
}

function renderStatus(s, sup) {
    const cfg = s.config || {};
    const prog = s.progress || {};
    const eq = s.equity || {};
    const risk = s.risk || {};

    document.getElementById('dashSubtitle').textContent =
        `${cfg.broker} · ${cfg.backend_mode} · ${(cfg.symbols || []).join(', ')} · ${cfg.duration_days}d`
        + (cfg.interval ? ` · ${cfg.interval}` : '');

    /* bars_total is null under a live clock, which is honest rather than
     * missing: a realtime run has no end. Show bars served instead of a
     * fraction that cannot exist. */
    const bar = document.getElementById('progressBar');
    const sideBar = document.getElementById('sidebarProgress');
    if (prog.fraction !== null && prog.fraction !== undefined) {
        const width = `${Math.min(100, prog.fraction * 100).toFixed(1)}%`;
        bar.style.width = width;
        sideBar.style.width = width;
        document.getElementById('progressLabel').textContent =
            `${int(prog.bars_served)} / ${int(prog.bars_total)} bars  (${(prog.fraction * 100).toFixed(1)}%)`;
    } else {
        bar.style.width = '100%';
        bar.classList.add('animate-pulse');
        sideBar.style.width = '100%';
        document.getElementById('progressLabel').textContent =
            `${int(prog.bars_served)} bars served · live clock, no end`;
    }

    document.getElementById('progMarketTime').textContent = shortTime(prog.market_time);
    document.getElementById('progClock').textContent = prog.clock || '—';
    document.getElementById('progSession').textContent =
        (s.session_id || '').slice(0, 8) || '—';
    document.getElementById('progUptime').textContent = duration(s.uptime_s);

    document.getElementById('kpiEquity').textContent = num(eq.current);
    document.getElementById('kpiEquityNote').textContent =
        `initial ${num(eq.initial)} · ${int(eq.samples)} samples`;
    const pnlEl = document.getElementById('kpiPnl');
    pnlEl.textContent = signed(eq.pnl);
    pnlEl.className = `text-2xl md:text-3xl font-black tabular-nums ${pnlClass(eq.pnl)}`;
    document.getElementById('kpiPnlPct').textContent =
        eq.pnl_pct === null || eq.pnl_pct === undefined ? '—' : `${signed(eq.pnl_pct, 2)}%`;

    const halted = risk.halted;
    document.getElementById('kpiRisk').textContent = halted ? 'HALTED' : 'OK';
    document.getElementById('kpiRisk').className =
        `text-2xl md:text-3xl font-black ${halted ? 'text-red-600' : 'text-purple-600'}`;
    document.getElementById('kpiRiskNote').textContent =
        halted ? (risk.halt_reason || 'kill switch tripped')
               : `exposure ${num(Object.values(risk.exposure || {}).reduce((a, b) => a + b, 0), 0)}`;

    document.getElementById('sidebarRun').innerHTML =
        `<b>${esc((cfg.symbols || []).join(','))}</b> · ${esc(cfg.backend_mode)}<br>` +
        `<span class="text-slate-400">${int(prog.bars_served)} bars</span>`;
    const stop = document.getElementById('sidebarStopBtn');
    stop.classList.toggle('hidden', !(sup && sup.busy));

    renderBotCards(s.bots || {}, 'dashBotCards');
}

async function loadEquity() {
    let body;
    try { body = await api('/api/v1/engine/equity?limit=1500'); }
    catch (e) { return; }
    const curve = (body.available && body.curve) ? body.curve : [];
    drawEquity(curve);
}

function drawEquity(curve) {
    const ctx = document.getElementById('equityChart');
    if (!ctx) return;
    const stamps = curve.map(p => p.time);
    /* Was a fixed slice(5, 16), which never showed the year on a run that
     * crossed one and spent the space on a date when every point was from the
     * same session. */
    const labels = marketTimeLabels(stamps) || curve.map((_, i) => i);
    const values = curve.map(p => p.value);
    if (equityChart) {
        equityChart.data.labels = labels;
        equityChart.data.datasets[0].data = values;
        equityChart.options.plugins.tooltip.callbacks.title =
            fullStampTooltip(stamps);
        equityChart.update('none');
        return;
    }
    equityChart = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets: [{
            label: 'Equity', data: values, borderColor: '#0f172a',
            backgroundColor: 'rgba(15,23,42,0.06)', borderWidth: 2,
            pointRadius: 0, fill: true, tension: 0.15,
        }]},
        options: {
            responsive: true, maintainAspectRatio: false,
            animation: false,
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { title: fullStampTooltip(stamps) } },
            },
            scales: {
                x: { ticks: { maxTicksLimit: 10, font: { size: 10 } }, grid: { display: false } },
                y: { ticks: { font: { size: 10 } }, grid: { color: '#f1f5f9' } },
            },
            interaction: { mode: 'index', intersect: false },
        },
    });
}

async function loadRoundTrips() {
    let body;
    try { body = await api('/api/v1/engine/roundtrips'); }
    catch (e) { return; }
    if (!body.available) {
        document.getElementById('kpiTrips').textContent = '—';
        document.getElementById('kpiWinRate').textContent = body.reason || '—';
        return;
    }
    document.getElementById('kpiTrips').textContent = int(body.closed);
    document.getElementById('kpiWinRate').textContent =
        body.win_rate_pct === null
            ? `${int(body.fills)} fills`
            : `win ${pct(body.win_rate_pct)} · realised ${signed(body.realised_pnl)}`;
}

/* ── bots ─────────────────────────────────────────────────────────────────── */

/* Which monitor keys get a tile. A strategy can expose anything it likes, so
 * the rest are rendered generically in the detail panel rather than dropped --
 * a monitor nobody can see is not a monitor. */
const HEADLINE_MONITORS = ['regime', 'volatility', 'signals_emitted',
                           'upper_touches', 'lower_touches', 'mid_crossings'];

/* The bots page lists every bot you have, running or not.
 *
 * It used to read /api/v1/engine/bots, which is the engine's live view and
 * empty between runs — so a strategy somebody had just written was invisible
 * until a run happened to be in flight. /api/v1/bots answers the question the
 * page is actually asking by putting the saved strategies and the live report
 * side by side. The dashboard still shows live bots only, through
 * renderBotCards below. */
async function loadBots() {
    let body;
    try { body = await api('/api/v1/bots'); }
    catch (e) { return; }
    const target = document.getElementById('botCards');
    const bots = body.bots || [];

    if (!bots.length) {
        target.innerHTML = '<p class="text-sm text-slate-400">'
            + 'No bots and no strategies. Write one on the '
            + '<a href="#" onclick="showSection(\'editor\')" class="underline font-semibold">Strategies</a> page.</p>';
        return;
    }

    const note = document.getElementById('botsEngineNote');
    if (note) {
        note.textContent = body.engine_available
            ? 'A run is in flight; live bots report once per bar.'
            : `No run in flight${body.reason ? ' — ' + body.reason : ''}. Saved strategies are listed as idle.`;
    }

    target.innerHTML = bots.map(b => b.live ? liveBotCard(b) : idleBotCard(b))
                           .join('');
    if (openBotId) loadBotHistory(openBotId);
}

/* A strategy that exists but is not running. Shown because the page is about
 * what bots you have, and because the three-state check dot is the only place
 * that says whether it would even start. */
function idleBotCard(b) {
    const dot = b.check_ok === 1
        ? '<span class="text-emerald-500" title="checked, runnable">●</span>'
        : b.check_ok === 0
        ? `<span class="text-red-500" title="${esc(b.check_error || 'has errors')}">●</span>`
        : '<span class="text-slate-300" title="not checked">●</span>';
    /* Three reasons a strategy will not join the next run, and they need
     * different fixes: switch it on, check it, or point the run at its
     * symbol. "Idle" alone would not say which. */
    const off = b.enabled === false;
    const verdict = off ? 'Switched off — it will not join a run'
        : b.check_ok === 1 ? 'Checked and runnable — joins the next run on its symbol'
        : b.check_ok === 0 ? (b.check_error || 'Has errors')
        : 'Not checked yet, so it will be left out of a run';
    const control = off
        ? `<button onclick="enableBotStrategy(${b.strategy_id}, event)"
             class="text-[10px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-100 px-2 py-1 rounded uppercase hover:bg-emerald-100">Enable</button>`
        : `<button onclick="disableBotStrategy(${b.strategy_id}, ${JSON.stringify(b.name)}, event)"
             class="text-[10px] font-bold text-slate-500 bg-slate-100 px-2 py-1 rounded uppercase hover:bg-slate-200">Disable</button>`;
    return `<div onclick="openStrategyFromBots(${b.strategy_id})"
         class="bg-white p-5 rounded-2xl border border-dashed border-slate-300 shadow-sm hover:border-slate-400 cursor-pointer transition ${off ? 'opacity-60' : ''}">
        <div class="flex justify-between items-start mb-3">
            <div class="min-w-0">
                <div class="flex items-center gap-2">${dot}
                    <span class="font-black text-base truncate">${esc(b.name)}</span></div>
                <p class="text-[10px] text-slate-400 font-bold uppercase ml-4">${esc(b.symbol)}</p>
            </div>
            <div class="flex flex-col items-end gap-1 shrink-0">
                <span class="text-[10px] font-bold ${off ? 'text-amber-600' : 'text-slate-400'} uppercase">${off ? 'Off' : 'Idle'}</span>
                ${control}
            </div>
        </div>
        <p class="text-[11px] text-slate-500 leading-snug">${esc(verdict)}</p>
        <p class="text-[10px] text-slate-400 mt-2 border-t border-slate-100 pt-2">
            Not running. Edited ${esc(shortTime(b.updated_at))}.</p>
    </div>`;
}

/* A bot the engine is reporting on. Same shape as the dashboard's card, with
 * the strategy's name when we know it and the bot id underneath — the id is
 * what the engine's log and the detail panel are keyed by. */
function liveBotCard(b) {
    const s = b.status || {};
    const mon = s.monitors || {};
    const inflight = Object.entries(s.inflight || {});
    const tiles = HEADLINE_MONITORS.filter(k => k in mon).map(k =>
        `<div><p class="text-[9px] font-bold text-slate-400 uppercase">${esc(k.replace(/_/g, ' '))}</p>
              <p class="text-sm font-bold tabular-nums">${esc(mon[k])}</p></div>`).join('');
    const stopped = s.stopped === true;
    const badge = stopped
        ? '<span class="text-[10px] font-bold text-amber-600 uppercase">Stopped</span>'
        : b.kind === 'engine'
        ? '<span class="text-[10px] font-bold text-slate-400 uppercase">Built in</span>'
        : '<span class="text-[10px] font-bold text-emerald-600 uppercase">Live</span>';
    /* Only a bot that came from one of your strategies can be switched off
     * from here: the engine's built-in bots are not rows in this database, so
     * there is nothing to set a flag on. */
    const control = (b.strategy_id && !stopped)
        ? `<button onclick="disableBotStrategy(${b.strategy_id}, ${JSON.stringify(b.name)}, event)"
             class="text-[10px] font-bold text-red-600 bg-red-50 border border-red-100 px-2 py-1 rounded uppercase hover:bg-red-100"
             title="Stops this bot now and cancels its resting orders. Does not sell what it holds.">Stop</button>`
        : '';
    const subtitle = b.kind === 'engine'
        ? `bar ${int(s.bar_index)}`
        : `${esc(b.bot_id)} · bar ${int(s.bar_index)}`;
    return `<div onclick="openBotDetail('${esc(b.bot_id)}')"
         class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm hover:border-slate-400 cursor-pointer transition">
        <div class="flex justify-between items-start mb-3">
            <div class="min-w-0">
                <span class="font-black text-base truncate">${esc(b.name)}</span>
                <p class="text-[10px] text-slate-400 font-bold uppercase">${subtitle}</p>
            </div>
            <div class="text-right shrink-0 flex flex-col items-end gap-1">
                <p class="text-lg font-black tabular-nums">${num(s.balance, 0)}</p>
                ${badge}
                ${control}
            </div>
        </div>
        <div class="grid grid-cols-3 gap-2 mb-3">${tiles}</div>
        ${stopped ? `<p class="text-[10px] font-bold text-amber-600 mb-2 normal-case">Stopped: ${esc(s.stopped_reason || 'by request')}. Its position was left alone.</p>` : ''}
        ${s.bars_dropped ? `<p class="text-[10px] font-bold text-amber-600 uppercase mb-2">${int(s.bars_dropped)} bar(s) dropped</p>` : ''}
        ${inflight.length ? `<p class="text-[10px] text-slate-500 mb-2">In flight: ${inflight.map(([k, v]) => `${esc(k)} ${esc(v)}`).join(', ')}</p>` : ''}
        ${mon.last_decision ? `<p class="text-[11px] text-slate-500 border-t border-slate-100 pt-2 leading-snug">${esc(mon.last_decision)}</p>` : ''}
    </div>`;
}

async function openStrategyFromBots(strategyId) {
    showSection('editor');
    await openStrategy(strategyId);
}

/* Switching a strategy off from the bots page, where you are most likely to
 * be when you notice it misbehaving. Same endpoint as the editor's toggle. */
async function disableBotStrategy(strategyId, name, event) {
    if (event) event.stopPropagation();   // do not also open the editor
    if (!confirm(`Switch "${name}" off?\n\n`
                 + 'Its bot stops immediately if a run is going, and its '
                 + 'resting orders are cancelled.\n\n'
                 + 'It does NOT sell what the strategy already holds — that '
                 + 'is a separate decision.')) {
        return;
    }
    await setStrategyEnabled(strategyId, false);
    loadBots();
    loadStrategies();
}

async function enableBotStrategy(strategyId, event) {
    if (event) event.stopPropagation();
    await setStrategyEnabled(strategyId, true);
    loadBots();
    loadStrategies();
}

/* The one call behind every on/off control. Reports what actually happened:
 * the flag always changes, and whether a live bot was stopped depends on
 * whether one was running. */
async function setStrategyEnabled(strategyId, enabled) {
    let result;
    try {
        result = await api(`/api/v1/strategies/${strategyId}/enabled`, {
            method: 'POST', body: JSON.stringify({enabled}),
        });
    } catch (e) {
        toast(e.message, 'error');
        return null;
    }
    if (result.error) {
        /* The urgent half failed. Said loudly, because somebody who pressed
         * this believes trading has stopped. */
        toast(result.error, 'error');
    } else if (result.stopped_now) {
        toast(`Switched off — bot ${result.bot_id} stopped, position left alone`);
    } else {
        toast(enabled ? 'Enabled — it joins the next run'
                      : 'Switched off — it was not running');
    }
    if (editorStrategy && editorStrategy.id === strategyId) {
        editorStrategy.enabled = result.enabled;
        setEnabledToggle(result.enabled);
    }
    return result;
}

function setEnabledToggle(enabled) {
    const box = document.getElementById('editorEnabled');
    const label = document.getElementById('editorEnabledLabel');
    box.disabled = false;
    box.checked = !!enabled;
    label.textContent = enabled ? 'Enabled' : 'Disabled';
    label.className = enabled ? '' : 'text-amber-600';
}

async function toggleEditorEnabled() {
    if (!editorStrategy) return;
    const wanted = document.getElementById('editorEnabled').checked;
    if (!wanted && !confirm(
            `Switch "${editorStrategy.name}" off?\n\n`
            + 'Its bot stops immediately if a run is going, and its resting '
            + 'orders are cancelled.\n\n'
            + 'It does NOT sell what the strategy already holds.')) {
        setEnabledToggle(true);
        return;
    }
    await setStrategyEnabled(editorStrategy.id, wanted);
    loadStrategies();
    loadBots();
}

async function restoreExamples() {
    try {
        const body = await api('/api/v1/strategies/seed-examples',
                               {method: 'POST'});
        const made = body.created || [];
        toast(made.length
            ? `Restored ${made.map(s => s.name).join(', ')}`
            : 'You already have all of them');
        if (made.length) { loadStrategies(); loadBots(); }
    } catch (e) {
        toast(e.message, 'error');
    }
}

function renderBotCards(bots, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const ids = Object.keys(bots);
    if (!ids.length) {
        container.innerHTML = '<p class="text-sm text-slate-400">No bots reported.</p>';
        return;
    }
    container.innerHTML = ids.map(id => {
        const s = bots[id];
        if (!s) {
            /* Null, not absent: the engine spawned this bot and it has never
             * reported. Showing it as silent beats it vanishing from the grid. */
            return `<div class="bg-white p-5 rounded-2xl border border-amber-200 shadow-sm">
                <div class="flex justify-between items-start">
                    <span class="font-black">${esc(id)}</span>
                    <span class="text-[10px] font-bold text-amber-600 uppercase">Silent</span>
                </div>
                <p class="text-xs text-slate-400 mt-2">Spawned but has not reported a bar yet.</p>
            </div>`;
        }
        const mon = s.monitors || {};
        const inflight = Object.entries(s.inflight || {});
        const tiles = HEADLINE_MONITORS.filter(k => k in mon).map(k =>
            `<div><p class="text-[9px] font-bold text-slate-400 uppercase">${esc(k.replace(/_/g, ' '))}</p>
                  <p class="text-sm font-bold tabular-nums">${esc(mon[k])}</p></div>`).join('');
        return `<div onclick="openBotDetail('${esc(id)}')"
             class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm hover:border-slate-400 cursor-pointer transition">
            <div class="flex justify-between items-start mb-3">
                <div>
                    <span class="font-black text-base">${esc(id)}</span>
                    <p class="text-[10px] text-slate-400 font-bold uppercase">bar ${int(s.bar_index)}</p>
                </div>
                <div class="text-right">
                    <p class="text-lg font-black tabular-nums">${num(s.balance, 0)}</p>
                    <p class="text-[10px] text-slate-400">cash</p>
                </div>
            </div>
            <div class="grid grid-cols-3 gap-2 mb-3">${tiles}</div>
            ${s.bars_dropped ? `<p class="text-[10px] font-bold text-amber-600 uppercase mb-2">${int(s.bars_dropped)} bar(s) dropped</p>` : ''}
            ${inflight.length ? `<p class="text-[10px] text-slate-500 mb-2">In flight: ${inflight.map(([k, v]) => `${esc(k)} ${esc(v)}`).join(', ')}</p>` : ''}
            ${mon.last_decision ? `<p class="text-[11px] text-slate-500 border-t border-slate-100 pt-2 leading-snug">${esc(mon.last_decision)}</p>` : ''}
        </div>`;
    }).join('');
}

function openBotDetail(botId) {
    openBotId = botId;
    showSection('bots', true);
    document.getElementById('botDetail').classList.remove('hidden');
    document.getElementById('botDetailName').textContent = botId;
    loadBotHistory(botId);
}

function closeBotDetail() {
    openBotId = null;
    document.getElementById('botDetail').classList.add('hidden');
}

async function loadBotHistory(botId) {
    let body;
    try { body = await api(`/api/v1/engine/bots/${encodeURIComponent(botId)}/history?limit=200`); }
    catch (e) { return; }
    if (!body.available) return;
    const rows = body.history || [];
    const latest = rows.length ? rows[rows.length - 1] : null;
    const mon = latest ? (latest.monitors || {}) : {};

    document.getElementById('botDetailWhy').textContent =
        mon.last_decision || `${rows.length} report(s) kept of ${body.capacity} slots`;

    /* Every monitor, not just the headline ones. A strategy author who adds a
     * field should see it here without touching this file. */
    document.getElementById('botDetailMonitors').innerHTML =
        Object.entries(mon).filter(([k]) => k !== 'last_decision').map(([k, v]) =>
            `<div class="bg-slate-50 rounded-xl p-3 border border-slate-100">
                <p class="text-[9px] font-bold text-slate-400 uppercase">${esc(k.replace(/_/g, ' '))}</p>
                <p class="text-sm font-bold tabular-nums break-words">${esc(v)}</p>
            </div>`).join('') ||
        '<p class="text-sm text-slate-400">This strategy exposes no monitors.</p>';

    drawBotChart(rows);

    const tbody = document.getElementById('botHistoryTable');
    if (!rows.length) { emptyRow(tbody, 4, 'No reports kept.'); return; }
    tbody.innerHTML = rows.slice().reverse().map(r => `<tr class="hover:bg-slate-50">
        <td class="px-3 py-2 tabular-nums">${int(r.bar_index)}</td>
        <td class="px-3 py-2 tabular-nums">${shortTime(r.market_time)}</td>
        <td class="px-3 py-2 text-right tabular-nums">${num(r.balance, 0)}</td>
        <td class="px-3 py-2 text-slate-500">${esc((r.monitors || {}).last_decision || '')}</td>
    </tr>`).join('');
}

/* Colours for whatever a strategy decided to plot. Assigned by position so the
 * same series keeps its colour across polls, and two of them are never the
 * same shade of grey. Price is not in here: it has its own. */
const PLOT_COLOURS = ['#2563eb', '#0f172a', '#7c3aed', '#059669', '#d97706',
                      '#db2777', '#0891b2'];

/* Axis labels for a run of market timestamps, at the coarsest granularity
 * that still tells them apart.
 *
 *   all in one day    HH:MM              a live run is 200 bars = 200 minutes
 *   within one year   MM-DD HH:MM
 *   across years      YY-MM-DD HH:MM
 *
 * Market time, not wall clock: a replay of September 2026 happened this
 * afternoon, and labelling it with this afternoon would make the chart a lie.
 *
 * Sliced from the ISO string rather than parsed into a Date. These stamps come
 * from Python's isoformat() and carry no offset, so handing them to `new Date`
 * invites the browser's timezone into a number that has nothing to do with it.
 * The format is fixed, so the slice is exact.
 *
 * Returns null when there are no usable stamps, which is the caller's signal
 * to fall back to bar numbers -- an empty axis would be worse than a crude one. */
function marketTimeLabels(stamps) {
    const usable = stamps.filter(s => typeof s === 'string' && s.length >= 16);
    if (!usable.length) return null;
    const granularity = new Set(usable.map(s => s.slice(0, 4))).size > 1 ? 'year'
        : new Set(usable.map(s => s.slice(0, 10))).size > 1 ? 'date'
        : 'time';
    return stamps.map(s => {
        if (typeof s !== 'string' || s.length < 16) return '';
        const time = s.slice(11, 16);
        if (granularity === 'time') return time;
        if (granularity === 'date') return `${s.slice(5, 10)} ${time}`;
        return `${s.slice(2, 10)} ${time}`;
    });
}

/* The full stamp for a tooltip, so shortening the axis loses nothing. */
function fullStampTooltip(stamps, extra) {
    return (items) => {
        const i = items[0].dataIndex;
        const stamp = stamps[i];
        const head = (typeof stamp === 'string')
            ? stamp.replace('T', ' ').slice(0, 19) : null;
        const tail = extra ? extra(i) : null;
        return [head, tail].filter(Boolean).join('  ·  ') || '';
    };
}

/* The span of a series, ignoring the nulls a warm-up leaves behind. */
function spanOf(values) {
    const numbers = values.filter(v => typeof v === 'number' && isFinite(v));
    if (!numbers.length) return null;
    return { lo: Math.min(...numbers), hi: Math.max(...numbers) };
}

/* Does this series belong on the price axis?
 *
 * By whether its range overlaps the price's, not by comparing midpoints. A
 * band, a moving average or a breakout level sits inside or beside the price;
 * an oscillator (RSI 0-100, a trend strength) does not come near it. Comparing
 * midpoints with a ratio got RSI right only by luck — at 50 against a 254
 * stock it just cleared the cutoff, and the same strategy on a 60 ETF would
 * have flattened the price into a line.
 *
 * The margin widens the price range by a tenth of its own height, so a band
 * that sits just outside the high and low still shares the axis instead of
 * being exiled for a rounding error. */
function sharesPriceAxis(series, price) {
    if (!series || !price) return true;
    const pad = Math.max((price.hi - price.lo) * 0.1, Math.abs(price.hi) * 0.01);
    return series.hi >= price.lo - pad && series.lo <= price.hi + pad;
}

function drawBotChart(rows) {
    const ctx = document.getElementById('botChart');
    if (!ctx) return;
    const stamps = rows.map(r => r.market_time);
    const labels = marketTimeLabels(stamps) || rows.map(r => int(r.bar_index));

    /* The price is always drawn. It comes from the bot, which is the process
     * that turned master's broadcast into the bar its strategy saw, so it is
     * the price the decisions were actually made against — not whatever the
     * broker would answer now. An indicator chart with no price to read the
     * indicators against is not a chart. */
    const closes = rows.map(r => (typeof r.close === 'number' && r.close > 0)
                                 ? r.close : null);
    const havePrice = closes.some(v => v !== null);

    /* Then whatever the strategy asked for, by name. Collected across the
     * whole window rather than from the last row, so a series that only
     * exists in one regime (the ADX strategy swaps its levels) does not
     * flicker in and out of the legend. */
    const plotKeys = [];
    rows.forEach(r => Object.keys(r.plots || {}).forEach(k => {
        if (!plotKeys.includes(k)) plotKeys.push(k);
    }));

    /* Older bots, and the engine's built-in BaseStrategy bots before they
     * grew plots(), report their bands as monitors instead. Picked up so
     * their chart is no worse than it was. */
    if (!plotKeys.length) {
        ['upper', 'middle', 'lower', 'high', 'low', 'avg_cost'].forEach(k => {
            if (rows.some(r => typeof (r.monitors || {})[k] === 'number')) {
                plotKeys.push(k);
            }
        });
    }

    const priceSpan = spanOf(closes);
    const datasets = [];
    let needsRightAxis = false;

    if (havePrice) {
        datasets.push({
            label: 'close', data: closes, yAxisID: 'y',
            borderColor: '#94a3b8', backgroundColor: 'rgba(148,163,184,0.12)',
            borderWidth: 2, pointRadius: 0, fill: true, tension: 0.1,
            order: 10,          // drawn behind the indicator lines
        });
    }

    plotKeys.forEach((key, i) => {
        const data = rows.map(r => {
            const v = (r.plots || {})[key];
            if (typeof v === 'number') return v;
            const m = (r.monitors || {})[key];
            return typeof m === 'number' ? m : null;
        });
        /* An oscillator on the price axis would flatten the price into a line.
         * Anything whose range does not reach the price gets the right-hand
         * axis, so a strategy author can plot one without knowing that. */
        const offScale = havePrice
            && !sharesPriceAxis(spanOf(data), priceSpan);
        if (offScale) needsRightAxis = true;
        datasets.push({
            label: key, data, yAxisID: offScale ? 'y2' : 'y',
            borderColor: PLOT_COLOURS[i % PLOT_COLOURS.length],
            borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0.1,
            borderDash: offScale ? [] : [4, 3],
            spanGaps: true,     // a warm-up gap is a gap, not a drop to zero
        });
    });

    if (!datasets.length) {
        /* Nothing to draw rather than a misleading line: before the first
         * report there is no price and no indicator. */
        datasets.push({ label: 'waiting for the first bar', data: [],
                        borderColor: '#cbd5e1' });
    }

    const scales = {
        x: { ticks: { maxTicksLimit: 12, font: { size: 9 } },
             grid: { display: false } },
        y: { position: 'left', ticks: { font: { size: 9 } },
             grid: { color: '#f1f5f9' } },
    };
    if (needsRightAxis) {
        scales.y2 = { position: 'right', ticks: { font: { size: 9 } },
                      grid: { display: false } };
    }

    if (botChart) { botChart.destroy(); }
    botChart = new Chart(ctx, {
        type: 'line', data: { labels, datasets },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: {
                legend: { labels: { font: { size: 10 }, boxWidth: 12 } },
                tooltip: { callbacks: {
                    title: fullStampTooltip(
                        stamps, i => `bar ${int(rows[i].bar_index)}`),
                } },
            },
            scales,
            interaction: { mode: 'index', intersect: false },
        },
    });
}

/* ── runs ─────────────────────────────────────────────────────────────────── */

const RUN_BADGE = {
    starting: 'bg-amber-50 text-amber-700 border-amber-200',
    running:  'bg-emerald-50 text-emerald-700 border-emerald-200',
    finished: 'bg-slate-100 text-slate-600 border-slate-200',
    stopped:  'bg-slate-100 text-slate-500 border-slate-200',
    failed:   'bg-red-50 text-red-700 border-red-200',
};

async function loadRuns() {
    const tbody = document.getElementById('runsTable');
    let runs;
    try { runs = await api('/api/v1/runs?limit=100'); }
    catch (e) { emptyRow(tbody, 9, e.message); return; }
    if (!runs.length) { emptyRow(tbody, 9, 'No runs yet. Press “New Run”.'); return; }
    tbody.innerHTML = runs.map(r => `<tr class="hover:bg-slate-50 cursor-pointer" onclick="selectRun(${r.id})">
        <td class="px-4 md:px-6 py-3 font-bold tabular-nums">${r.id}</td>
        <td class="px-4 md:px-6 py-3"><span class="text-[10px] font-black uppercase px-2 py-1 rounded-md border ${RUN_BADGE[r.status] || RUN_BADGE.finished}">${esc(r.status)}</span></td>
        <td class="px-4 md:px-6 py-3">${esc(r.mode)}</td>
        <td class="px-4 md:px-6 py-3 font-mono text-xs">${esc(r.symbols)}</td>
        <td class="hidden md:table-cell px-4 md:px-6 py-3 text-right tabular-nums">${int(r.days)}</td>
        <td class="hidden md:table-cell px-4 md:px-6 py-3 text-right tabular-nums">${int(r.bars_served)}</td>
        <td class="px-4 md:px-6 py-3 text-right tabular-nums font-bold ${pnlClass(r.pnl)}">${signed(r.pnl)}</td>
        <td class="hidden lg:table-cell px-4 md:px-6 py-3 text-xs text-slate-500 tabular-nums">${shortTime(r.started_at)}</td>
        <td class="px-4 md:px-6 py-3 text-right"><span class="text-[10px] font-black text-slate-500 uppercase">view →</span></td>
    </tr>${r.error ? `<tr class="bg-red-50/40"><td colspan="9" class="px-4 md:px-6 py-2 text-[11px] font-mono text-red-700 whitespace-pre-wrap">${esc(r.error)}</td></tr>` : ''}`).join('');
}

function selectRun(runId) {
    selectedRunId = runId;
    document.getElementById('logTitle').textContent = `Run ${runId} log`;
    loadRunLog();
}

async function loadRunLog() {
    if (selectedRunId === null) return;
    const pre = document.getElementById('runLog');
    try {
        pre.textContent = await apiText(`/api/v1/runs/${selectedRunId}/log?lines=500`);
        if (document.getElementById('logFollow').checked) {
            pre.scrollTop = pre.scrollHeight;
        }
    } catch (e) { pre.textContent = `Could not read the log: ${e.message}`; }
}

function openRunModal() {
    document.getElementById('runFormError').textContent = '';
    document.getElementById('runModal').classList.add('active');
}
function closeRunModal() {
    document.getElementById('runModal').classList.remove('active');
}

async function submitRun(event) {
    event.preventDefault();
    const button = document.getElementById('runSubmit');
    const error = document.getElementById('runFormError');
    error.textContent = '';
    button.disabled = true;
    button.textContent = 'Starting the broker, then the engine…';
    try {
        const run = await api('/api/v1/runs', {
            method: 'POST',
            body: JSON.stringify({
                symbols: document.getElementById('runSymbols').value
                            .split(',').map(s => s.trim()).filter(Boolean),
                mode: document.getElementById('runMode').value,
                interval: document.getElementById('runInterval').value,
                days: Number(document.getElementById('runDays').value),
                fund: Number(document.getElementById('runFund').value),
                speed: Number(document.getElementById('runSpeed').value),
                start_date: document.getElementById('runStart').value || '',
            }),
        });
        closeRunModal();
        toast(`Run ${run.id} started`, 'ok');
        selectRun(run.id);
        showSection('dashboard');
        loadRuns();
    } catch (e) {
        error.textContent = e.message;
    } finally {
        button.disabled = false;
        button.textContent = 'Start run';
    }
}

async function stopCurrentRun() {
    let sup;
    try { sup = await api('/api/v1/supervisor'); } catch (e) { return; }
    if (!sup.busy || sup.run_id === null) { toast('Nothing to stop'); return; }
    if (!confirm(`Stop run ${sup.run_id}? The engine cancels its resting ` +
                 `orders on the way out, then the broker is stopped too.`)) return;
    try {
        await api(`/api/v1/runs/${sup.run_id}`, { method: 'DELETE' });
        toast(`Run ${sup.run_id} stopped`, 'ok');
        refreshAll(); loadRuns();
    } catch (e) { toast(e.message, 'error'); }
}

/* ── account, positions, orders ───────────────────────────────────────────── */

async function loadAccount() {
    const tbody = document.getElementById('positionsTable');
    let body;
    try { body = await api('/api/v1/broker/account'); }
    catch (e) { emptyRow(tbody, 7, e.message); return; }

    const positions = body.positions || [];
    document.getElementById('posBalance').textContent = num(body.balance);
    const value = positions.reduce((a, p) => a + (p.market_value || 0), 0);
    const cost = positions.reduce((a, p) => a + (p.avg_cost || 0) * (p.quantity || 0), 0);
    const upnl = positions.reduce((a, p) => a + (p.unrealized_pnl || 0), 0);
    document.getElementById('posValue').textContent = num(value);
    document.getElementById('posCost').textContent = num(cost);
    const upnlEl = document.getElementById('posUpnl');
    upnlEl.textContent = signed(upnl);
    upnlEl.className = `text-2xl font-black tabular-nums ${pnlClass(upnl)}`;

    if (!positions.length) {
        emptyRow(tbody, 7, 'No positions. Buy something from Manual Trade, or start a run.');
        return;
    }
    tbody.innerHTML = positions.map(p => {
        const base = (p.avg_cost || 0) * (p.quantity || 0);
        const ret = base ? (p.unrealized_pnl / base) * 100 : null;
        return `<tr class="hover:bg-slate-50">
            <td class="px-4 md:px-6 py-3 font-bold font-mono">${esc(p.symbol)}</td>
            <td class="px-4 md:px-6 py-3 text-right tabular-nums">${int(p.quantity)}</td>
            <td class="hidden md:table-cell px-4 md:px-6 py-3 text-right tabular-nums">${num(p.avg_cost)}</td>
            <td class="px-4 md:px-6 py-3 text-right tabular-nums">${num(p.current_price)}</td>
            <td class="px-4 md:px-6 py-3 text-right tabular-nums">${num(p.market_value)}</td>
            <td class="px-4 md:px-6 py-3 text-right tabular-nums font-bold ${pnlClass(p.unrealized_pnl)}">${signed(p.unrealized_pnl)}</td>
            <td class="hidden sm:table-cell px-4 md:px-6 py-3 text-right tabular-nums ${pnlClass(ret)}">${ret === null ? '—' : signed(ret) + '%'}</td>
        </tr>`;
    }).join('');
}

const ORDER_BADGE = {
    FILLED: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    CANCELLED: 'bg-slate-100 text-slate-500 border-slate-200',
    REJECTED: 'bg-red-50 text-red-700 border-red-200',
    PARTIAL: 'bg-blue-50 text-blue-700 border-blue-200',
};
function orderBadge(status) {
    return ORDER_BADGE[status] || 'bg-amber-50 text-amber-700 border-amber-200';
}
const CANCELLABLE = new Set(['PLACED', 'COMMITTED_WAIT_MARKET_OPEN',
    'COMMITTED_WAIT_MATCHING', 'PARTIAL', 'PreSubmitted', 'Submitted',
    'PartFilled']);

async function loadOrders() {
    const tbody = document.getElementById('ordersTable');
    let body;
    try { body = await api('/api/v1/broker/orders'); }
    catch (e) { emptyRow(tbody, 8, e.message); return; }
    const orders = (body.orders || []).slice().sort(
        (a, b) => String(b.order_datetime).localeCompare(String(a.order_datetime)));
    if (!orders.length) { emptyRow(tbody, 8, 'No orders.'); return; }
    tbody.innerHTML = orders.map(o => {
        const id = o.id || o.ordno || '';
        const live = CANCELLABLE.has(String(o.status));
        return `<tr class="hover:bg-slate-50">
            <td class="px-4 md:px-6 py-3 font-mono text-xs">${esc(String(id).slice(0, 8))}</td>
            <td class="px-4 md:px-6 py-3 text-xs tabular-nums text-slate-500">${esc(o.order_datetime)}</td>
            <td class="px-4 md:px-6 py-3 font-bold font-mono">${esc(o.symbol)}</td>
            <td class="px-4 md:px-6 py-3 font-bold ${o.action === 'BUY' ? 'text-rose-600' : 'text-emerald-600'}">${esc(o.action)}</td>
            <td class="px-4 md:px-6 py-3 text-right tabular-nums">${int(o.quantity)}</td>
            <td class="px-4 md:px-6 py-3 text-right tabular-nums">${num(o.price)}</td>
            <td class="px-4 md:px-6 py-3"><span class="text-[10px] font-black uppercase px-2 py-1 rounded-md border ${orderBadge(o.status)}">${esc(o.status)}</span></td>
            <td class="px-4 md:px-6 py-3 text-right">${live
                ? `<button onclick="cancelOne('${esc(id)}')" class="text-[10px] font-black text-red-600 uppercase hover:underline">Cancel</button>`
                : '<span class="text-[10px] text-slate-300 uppercase">—</span>'}</td>
        </tr>`;
    }).join('');
}

async function cancelOne(orderId) {
    if (!confirm(`Cancel order ${orderId.slice(0, 8)}?`)) return;
    try {
        const res = await api(`/api/v1/broker/orders/${encodeURIComponent(orderId)}`,
                              { method: 'DELETE' });
        toast(`${orderId.slice(0, 8)}: ${res.status}`,
              res.status === 'CANCELLED' ? 'ok' : 'warn');
        loadOrders();
    } catch (e) { toast(e.message, 'error'); }
}

async function cancelAll() {
    /* Spells out that a bot's orders go too. The shell's `cancel` does this
     * with no prompt at all, which is fine at a terminal and not fine behind
     * a button you can hit by accident. */
    if (!confirm('Cancel every order the broker will still cancel?\n\n' +
                 'This includes any resting order a running bot placed. The ' +
                 'bot will be told its order was cancelled, which it handles, ' +
                 'but it is the bot\'s plan you are changing.')) return;
    try {
        const res = await api('/api/v1/broker/orders/cancel-all', { method: 'POST' });
        toast(`${res.cancelled} cancelled of ${res.examined} examined`, 'ok');
        loadOrders();
    } catch (e) { toast(e.message, 'error'); }
}

async function loadManualOrders() {
    const tbody = document.getElementById('manualOrdersTable');
    let rows;
    try { rows = await api('/api/v1/broker/manual-orders?limit=50'); }
    catch (e) { emptyRow(tbody, 7, e.message); return; }
    if (!rows.length) { emptyRow(tbody, 7, 'Nothing placed by hand yet.'); return; }
    tbody.innerHTML = rows.map(o => `<tr class="hover:bg-slate-50">
        <td class="px-4 md:px-6 py-3 text-xs tabular-nums text-slate-500">${shortTime(o.created_at)}</td>
        <td class="px-4 md:px-6 py-3 font-mono text-xs">${esc(o.order_id.slice(0, 8))}</td>
        <td class="px-4 md:px-6 py-3 font-bold font-mono">${esc(o.symbol)}</td>
        <td class="px-4 md:px-6 py-3 font-bold ${o.action === 'BUY' ? 'text-rose-600' : 'text-emerald-600'}">${esc(o.action)}</td>
        <td class="px-4 md:px-6 py-3 text-right tabular-nums">${int(o.quantity)}</td>
        <td class="px-4 md:px-6 py-3 text-right tabular-nums">${num(o.price)}</td>
        <td class="px-4 md:px-6 py-3"><span class="text-[10px] font-black uppercase px-2 py-1 rounded-md border ${orderBadge(o.status)}">${esc(o.status)}</span>
            ${o.message ? `<p class="text-[10px] text-slate-400 mt-1">${esc(o.message)}</p>` : ''}</td>
    </tr>`).join('');
}

/* ── market ───────────────────────────────────────────────────────────────── */

async function loadSnapshots() {
    const tbody = document.getElementById('snapshotTable');
    const symbols = document.getElementById('snapSymbols').value;
    try {
        const body = await api(`/api/v1/broker/snapshot?symbols=${encodeURIComponent(symbols)}`);
        const rows = body.snapshots || [];
        if (!rows.length) { emptyRow(tbody, 7, 'Nothing came back.'); return; }
        tbody.innerHTML = rows.map(s => s.error
            ? `<tr><td class="px-3 py-2 font-mono font-bold">${esc(s.symbol)}</td><td colspan="6" class="px-3 py-2 text-red-600 text-xs">${esc(s.error)}</td></tr>`
            : `<tr class="hover:bg-slate-50">
                <td class="px-3 py-2 font-mono font-bold">${esc(s.symbol)}</td>
                <td class="px-3 py-2 text-xs tabular-nums text-slate-500">${shortTime(s.timestamp)}</td>
                <td class="px-3 py-2 text-right tabular-nums font-bold">${num(s.close)}</td>
                <td class="px-3 py-2 text-right tabular-nums">${num(s.open)}</td>
                <td class="px-3 py-2 text-right tabular-nums">${num(s.high)}</td>
                <td class="px-3 py-2 text-right tabular-nums">${num(s.low)}</td>
                <td class="px-3 py-2 text-right tabular-nums">${int(s.volume)}</td>
            </tr>`).join('');
    } catch (e) { emptyRow(tbody, 7, e.message); }
}

async function loadKbars() {
    const symbol = document.getElementById('kbSymbol').value.trim();
    const start = document.getElementById('kbStart').value;
    const end = document.getElementById('kbEnd').value;
    const interval = document.getElementById('kbInterval').value;
    const note = document.getElementById('kbarsNote');
    if (!symbol || !start || !end) { note.textContent = 'Pick a symbol and both dates.'; return; }
    note.textContent = 'Loading…';
    try {
        const body = await api(`/api/v1/broker/kbars?symbol=${encodeURIComponent(symbol)}` +
            `&start=${start}&end=${end}&interval=${interval}`);
        const bars = body.kbars || [];
        note.textContent = `${int(bars.length)} bar(s) · range is [${start}, ${end}) — the end date is excluded.`;
        const ctx = document.getElementById('kbarsChart');
        if (kbarsChart) kbarsChart.destroy();
        kbarsChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: bars.map(b => shortTime(b.timestamp)),
                datasets: [{
                    label: `${symbol} close`, data: bars.map(b => b.close),
                    borderColor: '#0f172a', borderWidth: 1.5, pointRadius: 0,
                    fill: false, tension: 0.1,
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false, animation: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { maxTicksLimit: 10, font: { size: 9 } }, grid: { display: false } },
                    y: { ticks: { font: { size: 9 } }, grid: { color: '#f1f5f9' } },
                },
            },
        });
    } catch (e) { note.textContent = e.message; }
}

async function loadClock() {
    const panel = document.getElementById('clockPanel');
    try {
        const body = await api('/api/v1/broker/clock');
        const c = body.clock || {};
        /* Shown as the server sends them. These are naive Asia/Taipei values
         * and new Date() would reinterpret them as UTC, shifting every one by
         * eight hours. */
        const fields = [
            ['Market time', c.mock_current_time],
            ['Timeline origin', c.mock_init_time],
            ['Real time', c.real_current_time],
            ['Playback speed', c.playback_speed ? `${c.playback_speed}×` : '—'],
            ['Paused', c.paused ? 'yes' : 'no'],
            ['Market open', body.market_open ? 'yes' : 'no'],
        ];
        panel.innerHTML = fields.map(([k, v]) =>
            `<div class="bg-slate-50 rounded-xl p-3 border border-slate-100">
                <p class="text-[9px] font-bold text-slate-400 uppercase">${esc(k)}</p>
                <p class="text-sm font-bold tabular-nums">${esc(shortTime(v) === '—' ? v : shortTime(v))}</p>
            </div>`).join('');
        document.getElementById('clockDisplay').textContent =
            shortTime(c.mock_current_time);
    } catch (e) {
        panel.innerHTML = `<p class="text-sm text-slate-400 col-span-4">${esc(e.message)}</p>`;
    }
}

/* ── manual trade ─────────────────────────────────────────────────────────── */

async function quoteForOrder() {
    const symbol = document.getElementById('ordSymbol').value.trim();
    const panel = document.getElementById('quotePanel');
    if (!symbol) { panel.textContent = 'Enter a symbol first.'; return; }
    panel.textContent = 'Fetching…';
    try {
        const body = await api(`/api/v1/broker/snapshot?symbols=${encodeURIComponent(symbol)}`);
        const s = (body.snapshots || [])[0];
        if (!s || s.error) { panel.textContent = (s && s.error) || 'No price.'; return; }
        panel.innerHTML = `
            <div class="flex items-baseline gap-2"><span class="text-3xl font-black tabular-nums">${num(s.close)}</span><span class="text-xs text-slate-400">${esc(s.symbol)}</span></div>
            <p class="text-[11px] text-slate-400 mt-1">${shortTime(s.timestamp)} · day H ${num(s.high)} / L ${num(s.low)}</p>
            <div class="flex gap-2 mt-3">
                <button onclick="usePrice(${s.close})" class="text-[10px] font-black uppercase bg-slate-100 px-3 py-1.5 rounded-lg hover:bg-slate-200">Use ${num(s.close)}</button>
                <button onclick="usePrice(${(s.close * 1.001).toFixed(2)})" class="text-[10px] font-black uppercase bg-slate-100 px-3 py-1.5 rounded-lg hover:bg-slate-200">+0.1%</button>
                <button onclick="usePrice(${(s.close * 0.999).toFixed(2)})" class="text-[10px] font-black uppercase bg-slate-100 px-3 py-1.5 rounded-lg hover:bg-slate-200">−0.1%</button>
            </div>`;
    } catch (e) { panel.textContent = e.message; }
}

function usePrice(price) {
    document.getElementById('ordPrice').value = price;
}

async function loadMarketStatus() {
    const el = document.getElementById('tradeMarketStatus');
    try {
        const body = await api('/api/v1/broker/clock');
        const open = body.market_open;
        el.innerHTML = `<span class="font-bold ${open ? 'text-emerald-600' : 'text-slate-500'}">` +
            `${open ? 'Open' : 'Closed'}</span> · market time ` +
            `<b class="tabular-nums">${shortTime((body.clock || {}).mock_current_time)}</b>` +
            `<p class="text-[11px] text-slate-400 mt-1">A closed market does not refuse the order: the ` +
            `broker commits it and waits for the open.</p>`;
    } catch (e) { el.textContent = e.message; }
}

async function submitOrder(event) {
    event.preventDefault();
    const button = document.getElementById('ordSubmit');
    const out = document.getElementById('orderResult');
    const confirmed = document.getElementById('ordConfirm').checked;
    if (!confirmed) {
        out.innerHTML = '<p class="text-amber-700 font-bold">Tick the acknowledgement first.</p>';
        return;
    }
    const payload = {
        symbol: document.getElementById('ordSymbol').value.trim().toUpperCase(),
        action: document.getElementById('ordAction').value,
        price: Number(document.getElementById('ordPrice').value),
        quantity: Number(document.getElementById('ordQty').value),
        odd_lot: document.getElementById('ordLot').value === '1',
        confirm: true,
    };
    if (!confirm(`${payload.action} ${payload.quantity} share(s) of ` +
                 `${payload.symbol} at ${payload.price}?`)) return;
    button.disabled = true;
    out.textContent = 'Placing…';
    try {
        const res = await api('/api/v1/broker/orders',
                              { method: 'POST', body: JSON.stringify(payload) });
        /* A rejection is a 200 with a REJECTED status, not an error: the broker
         * answered, it just said no, and the reason is the useful part. */
        const ok = res.status !== 'REJECTED';
        out.innerHTML = `<div class="p-3 rounded-xl border ${orderBadge(res.status)}">
            <p class="font-black uppercase text-[10px]">${esc(res.status)}</p>
            <p class="mt-1">${esc(res.message || '')}</p>
            <p class="text-[10px] text-slate-500 mt-1 font-mono">${esc(res.order_id)}</p>
        </div>`;
        toast(`${res.status}: ${res.message || payload.symbol}`, ok ? 'ok' : 'warn');
        document.getElementById('ordConfirm').checked = false;
        loadManualOrders();
    } catch (e) {
        out.innerHTML = `<p class="text-red-600 font-bold">${esc(e.message)}</p>`;
    } finally { button.disabled = false; }
}

/* ── audit ────────────────────────────────────────────────────────────────── */

async function loadAudit() {
    const tbody = document.getElementById('auditTable');
    let rows;
    try { rows = await api('/api/v1/audit?limit=200'); }
    catch (e) { emptyRow(tbody, 4, e.message); return; }
    if (!rows.length) { emptyRow(tbody, 4, 'Nothing logged yet.'); return; }
    tbody.innerHTML = rows.map(r => `<tr class="hover:bg-slate-50">
        <td class="px-4 md:px-6 py-3 text-xs tabular-nums text-slate-500">${shortTime(r.timestamp)}</td>
        <td class="px-4 md:px-6 py-3"><span class="text-[10px] font-black uppercase px-2 py-1 rounded-md border bg-slate-100 text-slate-600 border-slate-200">${esc(r.action)}</span></td>
        <td class="px-4 md:px-6 py-3 font-mono text-xs">${esc(r.target)}</td>
        <td class="hidden lg:table-cell px-4 md:px-6 py-3 text-xs text-slate-500">${esc(r.details)}</td>
    </tr>`).join('');
}

/* ── polling ──────────────────────────────────────────────────────────────── */

function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => {
        if (!document.getElementById('autoRefresh').checked) return;
        if (document.hidden) return;   // no point polling a hidden tab
        const page = currentPage();
        loadStatus();
        loadBrokerLamp();
        if (page === 'dashboard') { loadEquity(); loadRoundTrips(); }
        if (page === 'bots') { loadBots(); }
        if (page === 'runs') {
            loadRuns();
            if (document.getElementById('logFollow').checked) loadRunLog();
        }
    }, POLL_MS);
}

/* ── strategies / editor ──────────────────────────────────────────────────────
 *
 * The editor itself is static/vendor/codemirror.bundle.js, which exposes
 * window.FinHubEditor and nothing else (see tools/editor/README.md). It is
 * created on first use rather than at boot, because most visits never open
 * this page and a 460 KB editor should not be mounted for them.
 *
 * Checking costs about a second — it is a subprocess in the CJTrade checkout,
 * most of which is importing TA-Lib — so it runs on save, on demand, and after
 * a long idle pause. Not per keystroke. */

const CHECK_IDLE_MS = 1200;

let editorView = null;
let editorStrategy = null;      // the row being edited, or null
let editorClean = '';           // the source as last saved
let checkTimer = null;

function editorIsDirty() {
    return !!(editorView && editorStrategy
              && FinHubEditor.getValue(editorView) !== editorClean);
}

async function ensureEditor() {
    if (editorView) return editorView;
    if (!window.FinHubEditor) {
        toast('The code editor failed to load. Reload the page.', 'error');
        return null;
    }
    editorView = FinHubEditor.create(
        document.getElementById('editorHost'), '', onEditorChanged);
    /* Completion over the strategy API. Best effort: without it CodeMirror
     * still completes Python keywords and the user's own names, so a failure
     * here must not stop the editor opening. */
    try {
        const ref = await api('/api/v1/strategies/api-reference');
        FinHubEditor.setApi(ref.entries || []);
        if (ref.error) {
            toast('Completion for the strategy API is unavailable: '
                  + ref.error, 'error');
        }
    } catch (e) {
        toast('Could not load the strategy API reference: ' + e.message,
              'error');
    }
    return editorView;
}

function onEditorChanged() {
    const dirty = editorIsDirty();
    document.getElementById('editorDirty').classList.toggle('hidden', !dirty);
    if (!dirty) return;
    /* A stored verdict described the stored text, so it stops applying the
     * moment the text changes. */
    setEditorStatus('Edited. Not checked yet.', 'idle');
    clearTimeout(checkTimer);
    checkTimer = setTimeout(() => checkStrategy(true), CHECK_IDLE_MS);
}

function setEditorStatus(message, kind) {
    const el = document.getElementById('editorStatus');
    el.textContent = message;
    el.className = 'text-xs ' + (
        kind === 'ok' ? 'text-emerald-600 font-semibold'
        : kind === 'error' ? 'text-red-600 font-semibold'
        : kind === 'busy' ? 'text-slate-500'
        : 'text-slate-400');
}

function setEditorButtons(enabled) {
    ['editorSaveBtn', 'editorCheckBtn', 'editorDeleteBtn'].forEach(
        id => document.getElementById(id).disabled = !enabled);
}

async function loadStrategies(selectId) {
    const host = document.getElementById('strategyList');
    let rows;
    try {
        rows = await api('/api/v1/strategies');
    } catch (e) {
        host.innerHTML = `<p class="px-4 py-6 text-xs text-red-600">${esc(e.message)}</p>`;
        return;
    }
    if (!rows.length) {
        host.innerHTML = '<p class="px-4 py-6 text-xs text-slate-400">'
            + 'Nothing yet. Press <b>+ New Strategy</b>.</p>';
        return;
    }
    host.innerHTML = rows.map(s => {
        /* Three states, not two: never checked is not the same as checked and
         * broken, and a tick on unchecked text would be a lie. */
        const mark = s.last_check_ok === 1
            ? '<span class="text-emerald-500" title="checked, runnable">●</span>'
            : s.last_check_ok === 0
            ? `<span class="text-red-500" title="${esc(s.last_check_error || 'has errors')}">●</span>`
            : '<span class="text-slate-300" title="not checked">●</span>';
        const active = editorStrategy && editorStrategy.id === s.id;
        const off = s.enabled === false;
        return `<button onclick="openStrategy(${s.id})"
            class="w-full text-left px-4 py-3 hover:bg-slate-50 transition ${active ? 'bg-slate-50' : ''} ${off ? 'opacity-50' : ''}">
            <div class="flex items-center gap-2">${mark}
                <span class="font-bold text-sm truncate">${esc(s.name)}</span>
                ${off ? '<span class="text-[9px] font-bold text-amber-600 uppercase shrink-0">off</span>' : ''}</div>
            <div class="text-[11px] text-slate-400 mt-0.5 ml-4">${esc(s.symbol)}
                · ${esc(shortTime(s.updated_at))}</div>
        </button>`;
    }).join('');
    if (selectId) await openStrategy(selectId);
}

async function openStrategy(id) {
    if (editorIsDirty() && !confirm(
            'This strategy has unsaved changes. Discard them?')) {
        return;
    }
    const view = await ensureEditor();
    if (!view) return;
    let s;
    try {
        s = await api(`/api/v1/strategies/${id}`);
    } catch (e) {
        toast(e.message, 'error');
        return;
    }
    editorStrategy = s;
    editorClean = s.source;
    FinHubEditor.setValue(view, s.source);
    FinHubEditor.showDiagnostics(view, []);
    document.getElementById('editorTitle').textContent = s.name;
    document.getElementById('editorSubtitle').textContent =
        `${s.symbol} · strategy #${s.id}`
        + (s.seeded_from ? ` · from the ${s.seeded_from} example` : '');
    document.getElementById('editorDirty').classList.add('hidden');
    document.getElementById('editorParams').classList.add('hidden');
    document.getElementById('editorDiagnostics').classList.add('hidden');
    setEditorButtons(true);
    setEnabledToggle(s.enabled !== false);
    setEditorStatus(
        s.last_check_ok === 1 ? 'Checked and runnable.'
        : s.last_check_ok === 0 ? (s.last_check_error || 'Has errors.')
        : 'Not checked yet.',
        s.last_check_ok === 1 ? 'ok' : s.last_check_ok === 0 ? 'error' : 'idle');
    loadStrategies();            // repaint the list so the active row shows
}

async function checkStrategy(quiet) {
    if (!editorView || !editorStrategy) return;
    clearTimeout(checkTimer);
    setEditorStatus('Checking…', 'busy');
    let result;
    try {
        result = await api('/api/v1/strategies/check', {
            method: 'POST',
            body: JSON.stringify({source: FinHubEditor.getValue(editorView)}),
        });
    } catch (e) {
        setEditorStatus(e.message, 'error');
        if (!quiet) toast(e.message, 'error');
        return;
    }
    renderCheck(result);
    return result;
}

function renderCheck(result) {
    const diags = result.diagnostics || [];
    FinHubEditor.showDiagnostics(editorView, diags);

    const panel = document.getElementById('editorDiagnostics');
    panel.classList.toggle('hidden', diags.length === 0);
    panel.innerHTML = diags.map(d => `
        <div class="text-xs flex gap-2 ${d.severity === 'warning' ? 'text-amber-700' : 'text-red-600'}">
            <button onclick="gotoLine(${d.line})"
                class="font-mono font-bold shrink-0 hover:underline">L${d.line}</button>
            <span>${esc(d.message)}</span>
        </div>`).join('');

    const params = result.params || [];
    const paramBox = document.getElementById('editorParams');
    paramBox.classList.toggle('hidden', params.length === 0);
    document.getElementById('editorParamList').innerHTML = params.map(p => {
        const lo = p.min === undefined || p.min === null ? '—' : p.min;
        const hi = p.max === undefined || p.max === null ? '—' : p.max;
        const bounds = (p.min !== undefined || p.max !== undefined)
            ? ` <span class="text-slate-400">(${esc(lo)} … ${esc(hi)})</span>` : '';
        return `<div class="text-xs bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
            <div class="font-semibold">${esc(p.label)}</div>
            <div class="text-slate-500 tabular-nums">${esc(String(p.default))}
                <span class="text-slate-300">${esc(p.kind)}</span>${bounds}</div>
        </div>`;
    }).join('');

    if (result.ok) {
        setEditorStatus(params.length
            ? `No problems. ${params.length} parameter(s) declared.`
            : 'No problems.', 'ok');
    } else {
        const n = diags.filter(d => d.severity !== 'warning').length;
        setEditorStatus(`${n} problem${n === 1 ? '' : 's'} — this will not run.`,
                        'error');
    }
}

function gotoLine(line) {
    if (!editorView) return;
    const doc = editorView.state.doc;
    const at = doc.line(Math.max(1, Math.min(doc.lines, line)));
    editorView.dispatch({selection: {anchor: at.from}, scrollIntoView: true});
    editorView.focus();
}

async function saveStrategy() {
    if (!editorView || !editorStrategy) return;
    const source = FinHubEditor.getValue(editorView);
    const btn = document.getElementById('editorSaveBtn');
    btn.disabled = true;
    try {
        await api(`/api/v1/strategies/${editorStrategy.id}`, {
            method: 'PUT', body: JSON.stringify({source}),
        });
        editorClean = source;
        document.getElementById('editorDirty').classList.add('hidden');
        toast('Saved');
        /* Check the saved text and record the verdict, so the dot in the list
         * means something without anyone pressing Check. */
        renderCheck(await api(
            `/api/v1/strategies/${editorStrategy.id}/check`, {method: 'POST'}));
        loadStrategies();
        loadBots();              // the check dot on its bot card just changed
    } catch (e) {
        toast(e.message, 'error');
    } finally {
        btn.disabled = false;
    }
}

function closeEditor() {
    editorStrategy = null;
    editorClean = '';
    if (editorView) {
        FinHubEditor.setValue(editorView, '');
        FinHubEditor.showDiagnostics(editorView, []);
    }
    document.getElementById('editorTitle').textContent = 'No strategy open';
    document.getElementById('editorSubtitle').textContent =
        'Pick one on the left, or make a new one';
    document.getElementById('editorDirty').classList.add('hidden');
    document.getElementById('editorParams').classList.add('hidden');
    document.getElementById('editorDiagnostics').classList.add('hidden');
    setEditorButtons(false);
    setEditorStatus('Nothing checked yet.', 'idle');
}

async function deleteStrategy() {
    if (!editorStrategy) return;
    if (!confirm(`Delete "${editorStrategy.name}"? This cannot be undone.`)) {
        return;
    }
    try {
        await api(`/api/v1/strategies/${editorStrategy.id}`, {method: 'DELETE'});
    } catch (e) {
        toast(e.message, 'error');
        return;
    }
    toast('Deleted');
    closeEditor();
    loadStrategies();
    /* The bots page lists strategies, so it is now showing one that no longer
     * exists. Repainted here rather than left to the poll, because the poll
     * only runs while that page is the open one. */
    loadBots();
}

/* The templates, from CJTrade. Loaded once per page: adding one over there
 * changes this dropdown with no edit here. */
let templatesLoaded = false;

async function loadTemplates() {
    if (templatesLoaded) return;
    const select = document.getElementById('strategyTemplate');
    try {
        const body = await api('/api/v1/strategies/templates');
        const list = body.templates || [];
        if (!list.length) return;        // keep the hardcoded fallback option
        select.innerHTML = list.map(t =>
            `<option value="${esc(t.kind)}" data-note="${esc(t.note || '')}">
                ${esc(t.label)}</option>`).join('');
        templatesLoaded = true;
        showTemplateNote();
    } catch (e) {
        /* The dropdown keeps its one fallback entry, so a new strategy is
         * still possible without the list. */
        console.warn('could not load the templates:', e.message);
    }
}

function showTemplateNote() {
    const select = document.getElementById('strategyTemplate');
    const option = select.options[select.selectedIndex];
    document.getElementById('strategyTemplateNote').textContent =
        (option && option.dataset.note) || '\u00a0';
}

async function openStrategyModal() {
    document.getElementById('strategyFormError').textContent = '';
    document.getElementById('strategyModal').classList.add('active');
    document.getElementById('strategyName').focus();
    await loadTemplates();
}

function closeStrategyModal() {
    document.getElementById('strategyModal').classList.remove('active');
}

async function submitStrategy(event) {
    event.preventDefault();
    const btn = document.getElementById('strategySubmit');
    const error = document.getElementById('strategyFormError');
    const name = document.getElementById('strategyName').value.trim();
    const symbol = document.getElementById('strategySymbol').value.trim();
    const kind = document.getElementById('strategyTemplate').value;

    error.textContent = '';
    btn.disabled = true;
    btn.textContent = 'Creating…';
    try {
        /* No source: the server fills it in from CJTrade's own template for
         * this kind, which is generated next to the API it demonstrates. */
        const created = await api('/api/v1/strategies', {
            method: 'POST', body: JSON.stringify({name, symbol, kind}),
        });
        closeStrategyModal();
        await loadStrategies(created.id);
        loadBots();              // it belongs on that page from now on
        toast(`Created "${created.name}"`);
    } catch (e) {
        error.textContent = e.message;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Create';
    }
}

/* ── boot ─────────────────────────────────────────────────────────────────── */

window.addEventListener('popstate', () => showSection(currentPage(), false));

document.addEventListener('DOMContentLoaded', async () => {
    if (!token()) { window.location.href = '/login'; return; }

    try {
        const me = await api('/api/v1/auth/me');
        document.getElementById('currentUserDisplay').textContent = me.username;
    } catch (e) { return; }   // api() already redirected on a 401

    document.getElementById('runForm').addEventListener('submit', submitRun);
    document.getElementById('orderForm').addEventListener('submit', submitOrder);
    document.getElementById('strategyForm').addEventListener('submit', submitStrategy);

    // Default the kbars range to the last 30 days.
    const today = new Date();
    const prior = new Date(today.getTime() - 30 * 86400000);
    document.getElementById('kbEnd').value = today.toISOString().slice(0, 10);
    document.getElementById('kbStart').value = prior.toISOString().slice(0, 10);

    showSection(currentPage(), false);
    await refreshAll();
    loadClock();
    startPolling();
});
