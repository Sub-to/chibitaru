/* ══════════════════════════════════════════
   🔵 ちびたるダッシュボード - app.js
   サーバー(/api/all)から受け取った内容を画面に流し込む。
   外部CDNは一切使わない（オフラインでも画面は開く）。
   ══════════════════════════════════════════ */

const TZ = "Asia/Tokyo";
let POLL_MS = 60_000;       // 画面側の再取得（サーバー側にキャッシュがあるので軽い）
let ROTATE_MS = 7_000;      // 赤帯の見出しを入れ替える間隔

let DATA = null;
let alertItems = [];
let alertIdx = 0;
let pollTimer = null;
let paused = false;         // 画面が隠れている間は止める（電池対策）
let AUTO_SCROLL = true;     // ニュースの自動スクロール
let rotateTimer = null;     // 次のアラートへ切り替えるタイマー
let holdMs = 7_000;         // 今のアラートを表示し続ける時間
let SYS_MS = 3_000;         // このPCの状態を見にいく間隔

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
  $("#time").textContent = `${p.hour}:${p.minute}`;
  $("#sec").textContent  = p.second;
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

/* ── 文字サイズ ─────────────────────────
   Surface 3 のような高精細・小型画面だと既定では文字が小さいので、
   タッチ機かつ横1500px以下なら自動で少し大きくする。
   画面上で「+」「-」キーでも変えられ、この端末に記憶される。 */
const SCALE_KEY = "chibitaru.scale";
const SCALE_MIN = 0.85, SCALE_MAX = 1.6;

function autoScale() {
  const dpr = window.devicePixelRatio || 1;
  const touch = matchMedia("(pointer: coarse)").matches;
  const w = window.innerWidth;

  // OS側で既に拡大されている高DPI画面（GNOMEの200%など）では、
  // ここで更に拡大すると二重拡大になって行数が減る。何もしない。
  if (dpr >= 1.75) return 1.0;
  if (dpr >= 1.4)  return touch ? 1.05 : 1.0;

  // 等倍のまま使っている高精細画面だけ、指で読める大きさに持ち上げる
  if (touch && w <= 1500) return 1.15;
  if (w <= 1300) return 1.05;
  return 1.0;
}

function applyScale(v) {
  const clamped = Math.min(SCALE_MAX, Math.max(SCALE_MIN, v));
  // CSSはpx指定なので font-size では効かない。zoom で全体を拡縮する。
  // （1.0 のときは指定を外して、ブラウザ既定のままにする）
  document.documentElement.style.zoom = clamped === 1 ? "" : String(clamped);
  try { localStorage.setItem(SCALE_KEY, String(clamped)); } catch {}
  return clamped;
}

let uiScale = 1;
function initScale(serverScale) {
  let v = null;
  try { v = parseFloat(localStorage.getItem(SCALE_KEY)); } catch {}
  if (!v || isNaN(v)) {
    v = (serverScale && serverScale !== "auto") ? parseFloat(serverScale) : autoScale();
  }
  uiScale = applyScale(v || 1);
}

function bumpScale(delta) {
  uiScale = applyScale(uiScale + delta);
  const el = $("#updated");
  const keep = el.textContent;
  el.textContent = `文字サイズ ${Math.round(uiScale * 100)}%`;
  setTimeout(() => { el.textContent = keep; }, 1200);
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
    clearTimeout(rotateTimer);
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
  const t = $("#alertText");
  t.textContent = it.title;
  if (it.link) a.href = safeUrl(it.link); else a.removeAttribute("href");
  $("#alertMeta").textContent =
    `${it.source || ""} ・ ${hhmm(it.published)}（${ago(it.published)}） ・ ${i + 1}/${alertItems.length}`;

  requestAnimationFrame(() => {
    const dur = fitHeadline();
    // 実際に流れているときだけ、読み終わるまで待つ。
    // 軽量モードや動きを抑える設定では流さない（＝「…」で省略）ので待たない。
    const still = document.body.classList.contains("light") ||
                  matchMedia("(prefers-reduced-motion: reduce)").matches;
    holdMs = (dur && !still) ? Math.round(dur * 1000 + 1500) : ROTATE_MS;
    scheduleRotate();
  });
}

/* 次のアラートへ切り替える予約。表示時間は見出しの長さで変わる。 */
function scheduleRotate() {
  clearTimeout(rotateTimer);
  if (alertItems.length <= 1) return;   // 1件だけなら流しっぱなしでよい
  rotateTimer = setTimeout(() => {
    if (paused) { scheduleRotate(); return; }
    showAlert(++alertIdx % alertItems.length);   // 次の予約はこの中で行う
  }, holdMs);
}

/* 長い見出しは枠に収まらないので、はみ出した分だけ横に流す。
   収まるものは動かさない（常に動いていると読みにくいため）。 */
function fitHeadline() {
  const a = $("#alertHeadline");
  const t = $("#alertText");
  if (!a || !t) return 0;

  a.classList.remove("scroll");
  a.style.removeProperty("--shift");
  a.style.removeProperty("--dur");

  const over = t.scrollWidth - a.clientWidth;
  if (over > 8) {
    const shift = over + 24;                     // 端まで見せてから少し余白
    // 動く区間は全体の76%（前後で止まる分を除く）。毎秒55px前後で流れるようにする。
    const dur = Math.max(9, Math.round(shift / 55) + 5);
    a.style.setProperty("--shift", `-${shift}px`);
    a.style.setProperty("--dur", `${dur}s`);
    a.classList.add("scroll");
    return dur;
  }
  return 0;
}

/* ── システムモニター ───────────────────── */
function bar(pct, warn = 75, hot = 90) {
  if (pct == null) return "";
  const cls = pct >= hot ? "hot" : pct >= warn ? "warn" : "";
  return `<div class="sys-bar ${cls}"><i style="width:${Math.min(100, Math.max(0, pct))}%"></i></div>`;
}

function tile(label, value, unit = "", sub = "", pct = null, warn = 75, hot = 90) {
  return `<div class="sys-tile">
    <div class="sys-label">${esc(label)}</div>
    <div class="sys-value">${esc(value)}${unit ? `<span class="u">${esc(unit)}</span>` : ""}</div>
    ${sub ? `<div class="sys-sub">${esc(sub)}</div>` : ""}
    ${bar(pct, warn, hot)}
  </div>`;
}

function renderSys(d) {
  const body = $("#sysBody");
  if (!body) return;
  if (!d || d.error) {
    body.innerHTML = `<div class="empty">状態を取得できません</div>`;
    return;
  }
  const c = d.cpu || {}, m = d.memory || {}, k = d.disk || {},
        t = d.temp || {}, p = d.power || {};
  const tiles = [];

  tiles.push(tile("CPU", c.percent ?? "―", c.percent != null ? "%" : "",
                  c.mhz ? `${c.mhz}MHz` : (c.cores ? `${c.cores}コア` : ""),
                  c.percent));

  tiles.push(tile("メモリ", m.used ?? "―", m.used != null ? "GB" : "",
                  m.total ? `/ ${m.total}GB` : "", m.percent));

  tiles.push(tile("ディスク", k.free ?? "―", k.free != null ? "GB空" : "",
                  k.total ? `${k.percent}% 使用` : "", k.percent, 80, 92));

  // 温度・電力・電池は読めた場合だけ出す（機種によっては存在しない）
  if (t.cpu != null) {
    tiles.push(tile("温度", t.cpu, "℃", t.source ? String(t.source).split(":")[0] : "",
                    Math.min(100, (t.cpu / 95) * 100), 70, 85));
  }
  if (p.watt != null) {
    tiles.push(tile("消費電力", p.watt, "W", p.source || ""));
  }
  if (p.battery != null) {
    const st = p.status === "Charging" ? "⚡充電中"
             : p.status === "Full" ? "満充電"
             : (p.time_left ? `残り${p.time_left}` : (p.status || ""));
    tiles.push(tile("電池", p.battery, "%", st, p.battery, 101, 102));
  }

  body.innerHTML = tiles.join("");
  $("#sysUptime").textContent = d.uptime ? `稼働 ${d.uptime}` : "";
}

async function loadSys() {
  if (paused) return;
  try {
    const res = await fetch("/api/sys", { cache: "no-store" });
    renderSys(await res.json());
  } catch { /* サーバーが落ちていても画面は保つ */ }
}

/* ── ニュースの自動スクロール ───────────────
   常時表示なので、放っておいても続きが読めるように少しずつ送る。
   自分で触っている間は止まる。 */
let lastTouch = 0;
function noteInteraction() { lastTouch = Date.now(); }

function autoScrollStep() {
  if (paused || !AUTO_SCROLL) return;
  if (Date.now() - lastTouch < 20_000) return;   // 操作後20秒は触らない
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  document.querySelectorAll(".panel-body").forEach((body) => {
    const room = body.scrollHeight - body.clientHeight;
    if (room < 12) return;                        // スクロールの余地なし

    if (body.scrollTop >= room - 4) {
      body.scrollTo({ top: 0, behavior: "smooth" });   // 一周したら頭へ
      return;
    }
    // 記事1件分ずつ送ると読みやすい
    const item = body.querySelector(".feed:not(.hidden) li");
    const step = item ? Math.max(40, item.getBoundingClientRect().height) : 60;
    body.scrollBy({ top: step, behavior: "smooth" });
  });
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

  if (d.config?.auto_scroll === false) AUTO_SCROLL = false;
  if (d.config?.sysmon_sec) SYS_MS = d.config.sysmon_sec * 1000;

  // 非力なPC向け: アニメーションを止め、更新間隔を延ばす
  if (d.config?.light_mode) {
    document.body.classList.add("light");
    POLL_MS = 180_000;      // 3分
    ROTATE_MS = 12_000;
    SYS_MS = Math.max(SYS_MS, 8_000);
  }

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
  initScale();
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
    if (k === "+" || k === ";" || e.key === "=") bumpScale(0.05);
    if (k === "-") bumpScale(-0.05);
    if (["1", "2", "3", "4"].includes(k)) {
      const tabs = document.querySelectorAll('.tabs[data-group="left"] .tab');
      tabs[Number(k) - 1]?.click();
    }
  });

  // 画面が隠れている間（ロック・最小化）は取得を止めて電池を節約する
  document.addEventListener("visibilitychange", () => {
    paused = document.hidden;
    if (!paused) load(false);      // 復帰したら最新に追いつく
  });

  // 操作中は自動スクロールを止めるため、触ったことを覚えておく
  ["wheel", "touchstart", "mousedown", "keydown"].forEach((ev) =>
    document.addEventListener(ev, noteInteraction, { passive: true }));

  // 画面幅が変わったら見出しの流し方を測り直す
  window.addEventListener("resize", () => requestAnimationFrame(fitHeadline));

  load();
  loadSys();
  schedulePoll();
  setInterval(loadSys, SYS_MS);
  setInterval(autoScrollStep, 8_000);
}

function schedulePoll() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => { if (!paused) load(false); }, POLL_MS);
}

document.addEventListener("DOMContentLoaded", init);
