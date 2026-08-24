/* ══════════════════════════════════════════
   🔵 ちびたるダッシュボード - app.js
   サーバー(/api/all)から受け取った内容を画面に流し込む。
   外部CDNは一切使わない（オフラインでも画面は開く）。
   ══════════════════════════════════════════ */

const TZ = "Asia/Tokyo";
const POLL_MS = 60_000;     // 画面側の再取得（サーバー側にキャッシュがあるので軽い）
const ROTATE_MS = 7_000;    // 赤帯の見出しを入れ替える間隔

let DATA = null;
let alertItems = [];
let alertIdx = 0;

const $  = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

/* ── 時計 ───────────────────────────────── */
const WDAY = ["日", "月", "火", "水", "木", "金", "土"];

function tickClock() {
  const now = new Date();
  const p = new Intl.DateTimeFormat("ja-JP", {
    timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", weekday: "short",
    hour12: false,
  }).formatToParts(now).reduce((a, x) => (a[x.type] = x.value, a), {});

  $("#date").textContent = `${p.year}年${p.month}月${p.day}日`;
  $("#time").textContent = `${p.hour}:${p.minute}:${p.second}`;
  $("#wday").textContent = `${p.weekday}曜日`;
}

/* ── 表示用の小道具 ─────────────────────── */
function hhmm(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(d);
}

function ago(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 60000;
  if (isNaN(diff)) return "";
  if (diff < 1)   return "たった今";
  if (diff < 60)  return `${Math.floor(diff)}分前`;
  if (diff < 1440) return `${Math.floor(diff / 60)}時間前`;
  return `${Math.floor(diff / 1440)}日前`;
}

function isFresh(iso) {
  return iso && (Date.now() - new Date(iso).getTime()) < 3600_000;
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* リンク先は http/https だけ通す（変なスキームを踏まないように） */
function safeUrl(u) {
  try {
    const url = new URL(u, location.href);
    return (url.protocol === "http:" || url.protocol === "https:") ? url.href : "#";
  } catch { return "#"; }
}

/* ── 記事リスト描画 ─────────────────────── */
function renderFeed(el, items, emptyMsg = "記事がありません") {
  if (!el) return;
  if (!items || !items.length) {
    el.innerHTML = `<li class="empty">${esc(emptyMsg)}</li>`;
    return;
  }
  el.innerHTML = items.map((it) => `
    <li>
      <a href="${safeUrl(it.link)}" target="_blank" rel="noopener noreferrer">
        <div class="item-title">${esc(it.title)}</div>
        <div class="item-meta">
          ${it.shindo ? `<span class="item-shindo">震度 ${esc(it.shindo)}</span>` : ""}
          <span class="src">${esc(it.source || it.feed || "―")}</span>
          <span class="${isFresh(it.published) ? "fresh" : ""}">${esc(ago(it.published))}</span>
          <span>${esc(hhmm(it.published))}</span>
        </div>
      </a>
    </li>`).join("");
}

/* ── 赤帯（紛争＋地震）───────────────────── */
function renderAlerts(d) {
  const conflict = d.alerts?.conflict?.items || [];
  const qj = d.alerts?.quake?.japan || [];
  const qw = d.alerts?.quake?.world || [];

  // 赤帯で回すのは 地震（強い順に先頭）→ 紛争 の順
  alertItems = [
    ...qj.map((q) => ({
      kind: "quake",
      title: `【地震】最大震度${q.shindo} ${q.place} M${q.mag}`,
      link: q.link, published: q.time, source: "気象庁",
    })),
    ...conflict.map((c) => ({ kind: "conflict", ...c })),
  ];

  const bar = $("#alertbar");
  const count = alertItems.length;
  $("#alertCount").textContent = count;

  if (count === 0) {
    bar.classList.add("calm");
    bar.classList.remove("live");
    $("#alertIcon").textContent = "🛡";
    $("#alertLabel").textContent = "平常";
    $("#alertHeadline").textContent = "現在、重大なアラートはありません";
    $("#alertHeadline").removeAttribute("href");
    $("#alertMeta").textContent =
      `紛争・地震（震度${d.config?.min_shindo ?? 3}以上）を監視中`;
  } else {
    bar.classList.remove("calm");
    bar.classList.add("live");
    $("#alertIcon").textContent = "🚨";
    $("#alertLabel").textContent = qj.length ? "地震・紛争アラート" : "紛争アラート";
    alertIdx = alertIdx % count;
    showAlert(alertIdx);
  }

  // 右端の地震チップ（直近の1件）
  const chip = $("#quakeChip");
  if (qj.length) {
    const q = qj[0];
    chip.hidden = false;
    chip.innerHTML = `<span class="sh">震度${esc(q.shindo)}</span>
      <span>${esc(q.place)}<br><span class="small">${esc(hhmm(q.time))} M${esc(q.mag)}</span></span>`;
  } else {
    chip.hidden = true;
  }

  // 展開パネルの中身
  renderFeed($("#listConflict"), conflict, "紛争関連のアラートはありません");
  renderFeed($("#listQuake"), [
    ...qj.map((q) => ({
      title: `${q.place}（M${q.mag}）`, shindo: q.shindo,
      source: "気象庁", published: q.time, link: q.link,
    })),
    ...qw.map((q) => ({
      title: `【海外】M${q.mag} ${q.place}`,
      source: "USGS", published: q.time, link: q.link,
    })),
  ], `震度${d.config?.min_shindo ?? 3}以上の地震はありません`);

  $("#shindoMin").textContent = d.config?.min_shindo ?? 3;
}

function showAlert(i) {
  const it = alertItems[i];
  if (!it) return;
  const a = $("#alertHeadline");
  a.textContent = it.title;
  if (it.link) a.href = safeUrl(it.link); else a.removeAttribute("href");
  $("#alertMeta").textContent =
    `${it.source || ""} ・ ${hhmm(it.published)}（${ago(it.published)}） ・ ${i + 1}/${alertItems.length}`;
}

/* ── 天気 ───────────────────────────────── */
function renderWeather(w) {
  if (!w) return;
  const c = w.current;
  $("#wxPlace").textContent = w.place || "宮崎県宮崎市";

  if (c) {
    $("#wxIcon").textContent = c.icon || "🌡";
    $("#wxTemp").textContent = (c.temp ?? "--");
    $("#wxLabel").textContent = c.label || "―";
    $("#wxHum").textContent  = `湿度 ${c.humidity ?? "--"}%`;
    $("#wxWind").textContent = `風 ${c.wind ?? "--"} km/h`;
  }
  const t = w.today_temp;
  $("#wxRange").textContent = t ? `最高 ${t.max}℃ / 最低 ${t.min}℃` : "最高 -- / 最低 --";

  if (w.today) {
    $("#wxToday").textContent = `${w.today.icon} 今日: ${w.today.weather}`;
    if (!c) $("#wxIcon").textContent = w.today.icon;
  } else if (w.overview) {
    $("#wxToday").textContent = w.overview.replace(/\n/g, " ").slice(0, 90);
  }

  const week = (w.weekly || []).slice(0, 7);
  $("#wxWeek").innerHTML = week.map((d) => `
    <div class="wx-day">
      <div>${esc(d.md)}(${esc(d.wday)})</div>
      <span class="i">${esc(d.icon)}</span>
      <div class="t"><span class="hi">${esc(d.max || "-")}</span>/<span class="lo">${esc(d.min || "-")}</span></div>
    </div>`).join("");
}

/* ── 為替 ───────────────────────────────── */
function renderFx(fx) {
  const body = $("#fxBody");
  const pairs = fx?.pairs || [];
  if (!pairs.length) {
    body.innerHTML = `<div class="empty">為替を取得できませんでした</div>`;
    return;
  }
  body.innerHTML = pairs.map((p) => `
    <div class="fx-card">
      <div class="fx-pair">${esc(p.pair)}</div>
      <div class="fx-value">${esc(p.value)}</div>
    </div>`).join("");
  $("#fxUpdated").textContent = fx.updated
    ? `${hhmm(fx.updated)} ${fx.source || ""}` : (fx.source || "");
}

/* ── 全体描画 ───────────────────────────── */
function render(d) {
  DATA = d;
  renderAlerts(d);
  renderWeather(d.weather);
  renderFx(d.fx);

  for (const [cat, block] of Object.entries(d.news || {})) {
    renderFeed(document.querySelector(`.feed[data-feed="${cat}"]`), block.items);
  }
  $("#worldCount").textContent = `${d.news?.world?.items?.length || 0}件`;

  $("#updated").textContent = d.generated ? `更新 ${hhmm(d.generated)}` : "―";

  const v = d.vault || {};
  $("#vaultState").textContent = v.error
    ? `📓 ⚠️ Vault未設定`
    : (d.config?.vault_on === false ? "📓 記録OFF" : `📓 ${v.written ?? 0}件を記録`);
  $("#vaultState").title = v.error || v.daily || "";

  const errs = d.errors || [];
  $("#errors").textContent = errs.length ? `⚠️ ${errs.length}件の情報源が取得できませんでした` : "";
  $("#errors").title = errs.join("\n");
}

/* ── 通信 ───────────────────────────────── */
async function load(force = false) {
  const btn = $("#btnRefresh");
  btn.classList.add("loading");
  try {
    const res = await fetch(force ? "/api/refresh" : "/api/all", { cache: "no-store" });
    render(await res.json());
  } catch (e) {
    $("#errors").textContent = "⚠️ サーバーに接続できません（server.py は動いていますか？）";
  } finally {
    btn.classList.remove("loading");
  }
}

/* ── タブ ───────────────────────────────── */
function initTabs() {
  $$(".tabs").forEach((group) => {
    group.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".tab");
      if (!btn) return;
      group.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
      const name = btn.dataset.tab;

      if (group.dataset.group === "alert") {
        $$(".alert-list").forEach((l) =>
          l.classList.toggle("active", l.dataset.panel === name));
        return;
      }
      // 同じパネル内の記事リストを切り替える
      const panel = group.closest(".panel") || document;
      panel.querySelectorAll(".feed[data-feed]").forEach((f) =>
        f.classList.toggle("hidden", f.dataset.feed !== name));
    });
  });
}

function cycleTab(dir) {
  const group = document.querySelector('.tabs[data-group="left"]');
  const tabs = Array.from(group.querySelectorAll(".tab"));
  const cur = tabs.findIndex((t) => t.classList.contains("active"));
  tabs[(cur + dir + tabs.length) % tabs.length].click();
}

/* ── 起動 ───────────────────────────────── */
function init() {
  tickClock();
  setInterval(tickClock, 1000);
  initTabs();

  $("#btnRefresh").addEventListener("click", () => load(true));
  $("#alertToggle").addEventListener("click", () => {
    const p = $("#alertPanel");
    p.hidden = !p.hidden;
    $("#alertToggle").firstChild.textContent = p.hidden ? "▾ " : "▴ ";
  });

  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT") return;
    const k = e.key.toLowerCase();
    if (k === "r") load(true);
    if (k === "f") document.documentElement.requestFullscreen?.();
    if (k === "a") $("#alertToggle").click();
    if (k === "arrowright") cycleTab(1);
    if (k === "arrowleft")  cycleTab(-1);
    if (["1", "2", "3", "4"].includes(k)) {
      const tabs = document.querySelectorAll('.tabs[data-group="left"] .tab');
      tabs[Number(k) - 1]?.click();
    }
  });

  load();
  setInterval(() => load(false), POLL_MS);
  setInterval(() => {
    if (alertItems.length > 1) showAlert(++alertIdx % alertItems.length);
  }, ROTATE_MS);
}

document.addEventListener("DOMContentLoaded", init);
