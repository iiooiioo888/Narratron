const CHAROS_API = "";
const NARRATRON_API = "http://localhost:8080";
const SCRIPT_LIMIT = 20000;
const PAGES = ["Pad", "Timeline", "Dashboard", "Map", "Player"];
const HASH_ALIASES = {
  home: "Pad",
  parse: "Pad",
  direct: "Pad",
  characters: "Dashboard",
  imaging: "Dashboard",
  queue: "Dashboard",
  graph: "Map",
  monitor: "Dashboard",
  Pad: "Pad",
  Timeline: "Timeline",
  Dashboard: "Dashboard",
  Map: "Map",
  Player: "Player",
};
const DASH_ALIASES = {
  characters: "characters",
  imaging: "imaging",
  queue: "queue",
  monitor: "monitor",
};
const PAGE_META = {
  Pad: { title: "Pad 寫板", sub: "寫劇本，按 Direct 拆分鏡（會一併解析實體）" },
  Timeline: { title: "Timeline 時軌", sub: "只讀檢視 Director 輸出的 shots" },
  Dashboard: { title: "Dashboard 總覽", sub: "角色護照、生圖與佇列都在此子面板" },
  Map: { title: "Map 因果圖", sub: "只讀 Trace Log 視覺化" },
  Player: { title: "Player 播放器", sub: "合流成品播放；Alpha Q1 先以分鏡序列" },
};
const HARDWARE_POOLS = [
  { level: "L0", code: "Big Core", zh: "大核" },
  { level: "L1", code: "Mid Core", zh: "中核" },
  { level: "L2", code: "Alt Core", zh: "備核" },
  { level: "L3", code: "Light Core", zh: "輕核" },
];
const PLUGIN_MATRIX = [
  ["P1", "Tracer", "追跡", "生成前"],
  ["P2", "Fixer", "固形", "生成前"],
  ["P3", "Forker", "分岔", "生成前"],
  ["P4", "Painter", "調色", "生成前"],
  ["P5", "Mover", "擬動", "生成前/後"],
  ["P6", "Screener", "篩檢", "生成後"],
  ["P7", "Router", "路由", "生成前"],
  ["P8", "Recycler", "重生", "生成前"],
  ["P9", "Player", "配樂", "生成後"],
  ["P10", "Filter", "濾聲", "生成後"],
  ["P11", "Cropper", "裁切", "生成後"],
  ["P12", "Exporter", "轉檔", "生成後"],
  ["P13", "Maker", "製本", "生成後"],
];
const SAMPLE_SCRIPT = `INT. 廢棄工廠 — 夜

角色
- 卡爾（傷疤覆蓋左臉，手持鏽蝕鐵棍）
- 艾拉（繃帶纏繞右臂，背著醫療包）

道具
- 鏽蝕鐵棍
- 醫療包
- 老式無線電

場景
- 廢棄工廠：昏暗的吊燈搖晃，地面散落碎玻璃與鏽蝕零件

卡爾：（壓低聲音）守衛換班了，我們有十分鐘。
艾拉：（檢查無線電）信號很弱，但夠用。
卡爾握緊鐵棍，帶頭走向走廊深處。
艾拉跟上，繃帶上滲出淡淡血跡。`;

let currentPage = "Pad";
let dashTab = "overview";
let lastParseState = null;
let lastDirectState = null;
let lastError = "";
let selectedCharId = "";
let allCharacters = [];
let selectedShotId = "";
let selectedTraceId = "";
let playerIndex = 0;
let playerPlaying = false;
let playerTimer = null;
let queueTimer = null;
let inspectorOpen = false;
let lastGenAccepted = null;
let lastGenTaskKey = "";
let lastQueueTasks = [];

function currentState() {
  return lastDirectState || lastParseState;
}

function shots() {
  return [...((currentState() || {}).shots || [])].sort((a, b) => (a.order || 0) - (b.order || 0));
}

function traces() {
  return (currentState() || {}).traces || [];
}

function entities() {
  return (currentState() || {}).entities || [];
}

function persistSession() {
  try {
    sessionStorage.setItem(
      "narratron.gui",
      JSON.stringify({
        lastParseState,
        lastDirectState,
        script: document.getElementById("padScript")?.value || "",
        persist: document.getElementById("padPersist")?.checked !== false,
        selectedShotId,
        selectedTraceId,
        dashTab,
        selectedCharId,
      }),
    );
  } catch {
    /* ignore quota */
  }
}

function restoreSession() {
  try {
    const raw = sessionStorage.getItem("narratron.gui");
    if (!raw) return;
    const data = JSON.parse(raw);
    lastParseState = data.lastParseState || null;
    lastDirectState = data.lastDirectState || null;
    selectedShotId = data.selectedShotId || "";
    selectedTraceId = data.selectedTraceId || "";
    if (data.dashTab) dashTab = data.dashTab;
    if (data.selectedCharId) selectedCharId = data.selectedCharId;
    const script = document.getElementById("padScript");
    if (script && data.script) script.value = data.script;
    const persist = document.getElementById("padPersist");
    if (persist && data.persist === false) persist.checked = false;
  } catch {
    /* ignore */
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function setStatus(id, msg, kind = "") {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.className = "status-bar " + kind;
}

function setBanner(id, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!msg) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  el.textContent = msg;
  el.classList.remove("hidden");
}

function setInspector(title, body) {
  document.getElementById("inspectorTitle").textContent = title;
  const box = document.getElementById("inspectorBody");
  if (typeof body === "string") {
    box.innerHTML = body;
  } else {
    box.innerHTML = `<pre>${escapeHtml(pretty(body))}</pre>`;
  }
}

function setLoading(on) {
  document.getElementById("loadingMask").classList.toggle("hidden", !on);
}

async function api(base, path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (!base) headers["X-CharacterOS-Panel"] = headers["X-CharacterOS-Panel"] || "enabled";
  const resp = await fetch(base + path, { ...opts, headers });
  const text = await resp.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!resp.ok) {
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data);
    const err = new Error(detail || `HTTP ${resp.status}`);
    err.status = resp.status;
    throw err;
  }
  return data;
}

function formatTime(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("zh-TW", { hour12: false });
  } catch {
    return String(value);
  }
}

function badgeClass(status) {
  const s = String(status || "").toLowerCase();
  if (s === "ready" || s === "accepted") return "badge-ready";
  if (s === "pending") return "badge-pending";
  if (s === "failed") return "badge-failed";
  if (s === "running") return "badge-live";
  if (s === "waiting") return "badge-waiting";
  return "badge-pending";
}

function statusLabel(status) {
  return { pending: "等待中", running: "生成中", ready: "已完成", failed: "失敗", accepted: "已入庫", waiting: "排隊中" }[status] || status;
}

function padMs(ms) {
  const total = Math.max(0, Math.round((ms || 0) / 1000));
  const m = String(Math.floor(total / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function hasShots() {
  return shots().length > 0;
}

function hasTraces() {
  return traces().length > 0;
}

function hasMux() {
  return Boolean((currentState() || {}).mux_uri);
}

function parsedCharacters() {
  return entities().filter((item) => String(item.kind || "").toLowerCase() === "character");
}

function missingParsedPassports() {
  const existing = new Set(allCharacters.map((item) => String(item.name || "").trim()));
  return parsedCharacters().filter((item) => {
    const name = String(item.name || "").trim();
    return name && !existing.has(name);
  });
}

function recommendedAction() {
  if (!currentState() || !hasShots()) {
    return {
      page: "Pad",
      tab: null,
      label: "開始寫板",
      copy: "在 Pad 寫劇本，按 Direct 拆分鏡。不必先 Parse。",
    };
  }
  if (missingParsedPassports().length || !allCharacters.length) {
    return {
      page: "Dashboard",
      tab: "characters",
      label: "寫入角色護照",
      copy: missingParsedPassports().length
        ? `已有 ${shots().length} 個分鏡。下一步把 ${missingParsedPassports().length} 個角色寫進護照。`
        : `已有 ${shots().length} 個分鏡。下一步在 Dashboard 建立角色護照。`,
    };
  }
  if (allCharacters.length && dashTab !== "queue") {
    return {
      page: "Dashboard",
      tab: "imaging",
      label: "開始生圖",
      copy: "角色護照就緒後，在生圖子面板排入年齡軸並啟動 worker。",
    };
  }
  return {
    page: "Player",
    tab: null,
    label: "播放分鏡",
    copy: "可以到 Timeline 檢查鏡頭，或直接用 Player 預覽分鏡序列。",
  };
}

function goDash(tab) {
  dashTab = tab || "overview";
  navigate("Dashboard");
  setDashTab(dashTab);
}

function goRecommended() {
  const action = recommendedAction();
  if (action.tab) goDash(action.tab);
  else navigate(action.page);
}

function toggleInspector() {
  inspectorOpen = !inspectorOpen;
  applyInspectorVisibility();
}

function shouldShowInspector() {
  if (inspectorOpen) return true;
  if (currentPage === "Timeline" && selectedShotId) return true;
  if (currentPage === "Map") return true;
  if (currentPage === "Player" && hasShots()) return true;
  return false;
}

function applyInspectorVisibility() {
  const body = document.querySelector(".workspace-body");
  body?.classList.toggle("inspector-collapsed", !shouldShowInspector());
}

function updateNavReady() {
  const action = recommendedAction();
  document.querySelectorAll(".nav-item[data-page]").forEach((btn) => {
    const page = btn.dataset.page;
    const done =
      (page === "Pad" && Boolean(currentState())) ||
      (page === "Timeline" && hasShots()) ||
      (page === "Dashboard" && allCharacters.length > 0) ||
      (page === "Map" && (hasTraces() || hasShots())) ||
      (page === "Player" && hasShots());
    const next = action.page === page;
    btn.classList.toggle("done", done);
    btn.classList.toggle("next", next && currentPage !== page);
    btn.classList.remove("locked");
    const hint = btn.querySelector(".nav-hint");
    if (hint) {
      hint.textContent = next && currentPage !== page ? "下一步" : done ? "完成" : "";
    }
    btn.title = next ? action.copy : "";
  });
  const journey = document.getElementById("journeyCopy");
  const journeyBtn = document.getElementById("journeyBtn");
  if (journey) journey.textContent = action.copy;
  if (journeyBtn) journeyBtn.textContent = action.label;
  const pills = [
    `<span class="pill pill-accent">Alpha Q1</span>`,
    `<span class="pill">${parsedCharacters().length} 角色</span>`,
    `<span class="pill">${shots().length} shots</span>`,
    `<span class="pill">${allCharacters.length} 護照</span>`,
    `<span class="pill ${hasMux() ? "pill-live" : "pill-warn"}">${hasMux() ? "mux 就緒" : "Muxer 501"}</span>`,
  ];
  document.getElementById("topPills").innerHTML = pills.join("");
}

function navigate(page, opts = {}) {
  const raw = HASH_ALIASES[page] || page;
  if (!PAGES.includes(raw)) return;
  currentPage = raw;
  document.querySelectorAll("section[id^='page-']").forEach((el) => el.classList.add("hidden"));
  document.getElementById("page-" + raw)?.classList.remove("hidden");
  document.querySelectorAll(".nav-item[data-page]").forEach((el) => {
    el.classList.toggle("active", el.dataset.page === raw);
  });
  const meta = PAGE_META[raw];
  document.getElementById("topTitle").textContent = meta.title;
  document.getElementById("topSubtitle").textContent = meta.sub;
  if (!opts.skipHash) {
    const hash = raw === "Dashboard" && dashTab !== "overview" ? dashTab : raw;
    if (location.hash.slice(1) !== hash) window.location.hash = hash;
  }
  setBanner("errorBanner", lastError);
  if (DASH_ALIASES[page]) setDashTab(DASH_ALIASES[page]);
  if (raw === "Timeline") renderTimeline();
  if (raw === "Dashboard") refreshDashboard();
  else ensureGenPoll(false);
  if (raw === "Map") buildMap();
  if (raw === "Player") refreshPlayer();
  if (raw === "Pad") {
    updatePadButtons();
    renderPadResult();
  }
  updateNavReady();
  applyInspectorVisibility();
  if (!opts.skipInspector) {
    setInspector("狀態", {
      page: raw,
      characters: parsedCharacters().length,
      passports: allCharacters.length,
      shots: shots().length,
      traces: traces().length,
      last_error: lastError || null,
    });
  }
}

function setDashTab(tab) {
  dashTab = tab;
  ["overview", "characters", "imaging", "queue", "monitor"].forEach((name) => {
    document.getElementById("dash-" + name)?.classList.toggle("hidden", name !== tab);
  });
  document.querySelectorAll("#dashTabs button").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  if (tab === "characters") loadCharacters();
  if (tab === "imaging") {
    switchImagingTab("generate");
    loadImagingConfig();
    populateImgCharSelect();
  }
  if (tab === "monitor") loadMonitor();
  if (tab === "overview") renderDashboardOverview();
  if (currentPage === "Dashboard") refreshGenerationFeedback({ silent: tab !== "queue" && tab !== "imaging" });
  persistSession();
  updateNavReady();
}

function updatePadButtons() {
  const script = document.getElementById("padScript");
  if (!script) return;
  const len = script.value.length;
  const count = document.getElementById("padCount");
  count.textContent = `${len} / ${SCRIPT_LIMIT}`;
  count.style.color = len > SCRIPT_LIMIT ? "var(--red)" : "var(--muted)";
  const ok = script.value.trim().length > 0 && len <= SCRIPT_LIMIT;
  document.getElementById("btnParse").disabled = !ok;
  document.getElementById("btnDirect").disabled = !ok;
}

function loadSampleScript() {
  document.getElementById("padScript").value = SAMPLE_SCRIPT;
  updatePadButtons();
  persistSession();
}

function renderPadStats(data) {
  const ents = data.entities || [];
  const trs = data.traces || [];
  const assets = data.assets || [];
  const kinds = {};
  ents.forEach((item) => {
    kinds[item.kind] = (kinds[item.kind] || 0) + 1;
  });
  document.getElementById("padStats").innerHTML = `
    <span class="stat-chip"><span class="num">${ents.length}</span> 實體</span>
    <span class="stat-chip"><span class="num">${(data.shots || []).length}</span> shots</span>
    <span class="stat-chip"><span class="num">${parsedCharacters().length}</span> 角色</span>
    <span class="stat-chip"><span class="num">${trs.length}</span> 因果記錄</span>
    <span class="stat-chip"><span class="num">${assets.length}</span> 資產</span>
    ${Object.entries(kinds)
      .map(([key, val]) => `<span class="stat-chip">${escapeHtml(key)}: ${escapeHtml(val)}</span>`)
      .join("")}
  `;
  document.getElementById("padOutput").textContent = pretty(data);
  renderPadResult();
}

function renderPadResult() {
  const box = document.getElementById("padNext");
  if (!box) return;
  const data = currentState();
  if (!data) {
    box.innerHTML = "";
    return;
  }
  const chars = parsedCharacters();
  const shotCount = shots().length;
  const mode = lastDirectState ? "direct" : "parse";
  const title = mode === "direct" ? "分鏡已完成" : "實體已解析";
  const charList = chars.length
    ? `<ul>${chars.map((item) => `<li>${escapeHtml(item.name || item.id)}</li>`).join("")}</ul>`
    : "<p>沒有解析到角色。可在 Dashboard 手動新增。</p>";
  const nextButtons =
    mode === "direct"
      ? `<button class="btn btn-primary" type="button" onclick="navigate('Timeline')">查看分鏡</button>
         <button class="btn btn-secondary" type="button" onclick="syncParsedCharactersThenPassport()">寫入角色護照</button>
         <button class="btn btn-secondary" type="button" onclick="goDash('imaging')">開始生圖</button>`
      : `<button class="btn btn-primary" type="button" onclick="runDirect()">接著 Direct 拆分鏡</button>
         <button class="btn btn-secondary" type="button" onclick="syncParsedCharactersThenPassport()">先寫入角色護照</button>`;
  box.innerHTML = `<div class="next-card primary">
    <h3>${title}</h3>
    <p>${shotCount} 個 shot · ${chars.length} 個角色 · ${entities().length} 個實體</p>
    ${charList}
    <div class="btn-row">${nextButtons}</div>
  </div>`;
}

async function runParse() {
  const script = document.getElementById("padScript").value.trim();
  if (!script || script.length > SCRIPT_LIMIT) return;
  const persist = document.getElementById("padPersist").checked;
  setStatus("padStatus", "解析中…", "loading");
  setLoading(true);
  lastError = "";
  try {
    const data = await api(NARRATRON_API, "/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ script, persist }),
    });
    lastParseState = data;
    persistSession();
    renderPadStats(data);
    updateNavReady();
    setStatus("padStatus", `✓ Parse 完成：${(data.entities || []).length} 實體。若要拆分鏡，請按 Direct。`, "ok");
    setInspector("Parse 摘要", {
      status: "ok",
      endpoint: "POST /parse",
      entities: (data.entities || []).length,
      traces: (data.traces || []).length,
    });
    inspectorOpen = false;
    applyInspectorVisibility();
  } catch (err) {
    lastError = err.message;
    setStatus("padStatus", `✗ 解析失敗：${err.message}`, "err");
    setBanner("errorBanner", err.message);
  } finally {
    setLoading(false);
  }
}

async function runDirect() {
  const script = document.getElementById("padScript").value.trim();
  if (!script || script.length > SCRIPT_LIMIT) return;
  const persist = document.getElementById("padPersist").checked;
  setStatus("padStatus", "分鏡調度中…", "loading");
  setLoading(true);
  lastError = "";
  try {
    const data = await api(NARRATRON_API, "/direct", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ script, persist }),
    });
    lastDirectState = data;
    persistSession();
    renderPadStats(data);
    updateNavReady();
    setStatus("padStatus", `✓ Direct 完成：${(data.shots || []).length} 個 shot。下一步可查看分鏡或寫入角色護照。`, "ok");
    setInspector("Direct 摘要", {
      status: "ok",
      endpoint: "POST /direct",
      shots: (data.shots || []).length,
      traces: (data.traces || []).length,
    });
    inspectorOpen = false;
    applyInspectorVisibility();
  } catch (err) {
    lastError = err.message;
    setStatus("padStatus", `✗ 分鏡調度失敗：${err.message}`, "err");
    setBanner("errorBanner", err.message);
  } finally {
    setLoading(false);
  }
}

function renderTimeline() {
  const list = shots();
  document.getElementById("timelineCount").textContent = `${list.length} shots`;
  const empty = document.getElementById("timelineEmpty");
  const grid = document.getElementById("timelineGrid");
  if (!list.length) {
    empty.classList.remove("hidden");
    grid.classList.add("hidden");
    const next = document.getElementById("timelineNext");
    if (next) next.innerHTML = "";
    return;
  }
  empty.classList.add("hidden");
  grid.classList.remove("hidden");
  if (!selectedShotId || !list.some((item) => item.id === selectedShotId)) {
    selectedShotId = list[0].id;
  }
  document.getElementById("timelineList").innerHTML = list
    .map((shot) => {
      const beat = (shot.payload && shot.payload.beat) || "—";
      return `<button type="button" class="timeline-item${shot.id === selectedShotId ? " active" : ""}" onclick="selectShot(${JSON.stringify(shot.id)})">
        <div class="camera">#${escapeHtml(shot.order)} · ${escapeHtml(shot.camera_language || "未指定")}</div>
        <div class="beat">${escapeHtml(beat)}</div>
        <div style="font-size:11px;color:var(--muted);margin-top:4px;">${escapeHtml(shot.duration_ms)}ms · ${escapeHtml(shot.scene_id || "—")}</div>
      </button>`;
    })
    .join("");
  const selected = list.find((item) => item.id === selectedShotId) || list[0];
  document.getElementById("timelineDetail").innerHTML = renderShotHuman(selected);
  const next = document.getElementById("timelineNext");
  if (next) {
    next.innerHTML = `<div class="next-card primary">
      <h3>分鏡已可檢視</h3>
      <p>確認鏡頭後，把劇本角色寫入護照，才能生圖。</p>
      <div class="btn-row">
        <button class="btn btn-primary" type="button" onclick="syncParsedCharactersThenPassport()">寫入角色護照</button>
        <button class="btn btn-secondary" type="button" onclick="navigate('Player')">播放分鏡</button>
        <button class="btn btn-secondary" type="button" onclick="navigate('Map')">看因果圖</button>
      </div>
    </div>`;
  }
  setInspector("Shot", selected);
}

function renderShotHuman(shot) {
  if (!shot) return "選擇一個 shot。";
  const beat = (shot.payload && shot.payload.beat) || "—";
  const scene = shot.scene_id || "—";
  return `<p><strong>Shot #${escapeHtml(shot.order)}</strong> · ${escapeHtml(shot.camera_language || "未指定鏡頭")}</p>
    <p><strong>節拍</strong> ${escapeHtml(beat)}</p>
    <p><strong>場景</strong> ${escapeHtml(scene)} · <strong>時長</strong> ${escapeHtml(shot.duration_ms)}ms</p>
    <details class="json-fold"><summary>原始 JSON</summary><pre>${escapeHtml(pretty(shot))}</pre></details>`;
}

function selectShot(shotId) {
  selectedShotId = shotId;
  persistSession();
  renderTimeline();
}

function renderDashboardOverview() {
  const state = currentState() || {};
  const action = recommendedAction();
  const chars = parsedCharacters();
  const next = document.getElementById("dashNext");
  if (next) {
    next.innerHTML = `
      <div class="next-card ${action.page === "Pad" ? "primary" : ""}">
        <h3>1. 劇本與分鏡</h3>
        <p>${hasShots() ? `已有 ${shots().length} 個 shot` : "尚未 Direct。先回 Pad 拆分鏡。"}</p>
        <div class="btn-row">
          <button class="btn btn-secondary btn-sm" type="button" onclick="navigate('Pad')">${hasShots() ? "回 Pad" : "去 Direct"}</button>
          <button class="btn btn-secondary btn-sm" type="button" onclick="navigate('Timeline')" ${hasShots() ? "" : "disabled"}>看 Timeline</button>
        </div>
      </div>
      <div class="next-card ${action.tab === "characters" ? "primary" : ""}">
        <h3>2. 角色護照</h3>
        <p>${allCharacters.length ? `已有 ${allCharacters.length} 本護照` : chars.length ? `劇本有 ${chars.length} 個角色，尚未寫入護照` : "尚無角色。可手動新增。"}</p>
        <div class="btn-row">
          <button class="btn btn-primary btn-sm" type="button" onclick="syncParsedCharactersThenPassport()">寫入護照</button>
        </div>
      </div>
      <div class="next-card ${action.tab === "imaging" ? "primary" : ""}">
        <h3>3. 生圖佇列</h3>
        <p>選角色、排入年齡軸，worker 會依序生成。</p>
        <div class="btn-row">
          <button class="btn btn-secondary btn-sm" type="button" onclick="goDash('imaging')">去生圖</button>
          <button class="btn btn-secondary btn-sm" type="button" onclick="goDash('queue')">看佇列</button>
        </div>
      </div>
      <div class="next-card">
        <h3>4. 播放</h3>
        <p>${hasShots() ? "可用 Player 預覽分鏡序列。" : "等 Direct 完成後即可播放。"}</p>
        <div class="btn-row">
          <button class="btn btn-secondary btn-sm" type="button" onclick="navigate('Player')" ${hasShots() ? "" : "disabled"}>開 Player</button>
        </div>
      </div>
    `;
  }
  document.getElementById("dashMetrics").innerHTML = `
    <div class="metric-card"><span>Entities</span><strong>${entities().length}</strong></div>
    <div class="metric-card"><span>Shots</span><strong>${shots().length}</strong></div>
    <div class="metric-card"><span>角色護照</span><strong>${allCharacters.length}</strong></div>
    <div class="metric-card"><span>Assets</span><strong>${(state.assets || []).length}</strong></div>
  `;
  document.getElementById("dashPools").innerHTML = HARDWARE_POOLS.map((pool) => {
    const active = pool.code === "Mid Core";
    return `<div class="pool-card${active ? " active" : ""}">
      <div class="code">${escapeHtml(pool.code)}</div>
      <div class="zh">${escapeHtml(pool.level)} · ${escapeHtml(pool.zh)}</div>
      <div class="muted" style="margin-top:8px;font-size:12px;">${active ? "本階段 Router 固定選此池" : "待機"}</div>
    </div>`;
  }).join("");
  document.getElementById("dashPlugins").innerHTML = PLUGIN_MATRIX.map(([pid, code, zh, phase]) => {
    const live = pid === "P7" ? "Alpha Q1 可觸發（固定 Mid Core）" : "介面已凍結，執行待後續季";
    return `<div class="plugin-card">
      <div class="pid">${escapeHtml(pid)} ${escapeHtml(code)}</div>
      <div>${escapeHtml(zh)}</div>
      <div class="phase">${escapeHtml(phase)} · ${escapeHtml(live)}</div>
    </div>`;
  }).join("");
  const grouped = {};
  entities().forEach((item) => {
    const key = item.kind || "unknown";
    grouped[key] = (grouped[key] || 0) + 1;
  });
  const kinds = Object.entries(grouped)
    .map(([key, val]) => `${key}: ${val}`)
    .join(" · ") || "尚無實體";
  setInspector("Dashboard", { kinds, phase: "Alpha Q1", keeper: "501", muxer: "501" });
}

function refreshDashboard() {
  if (dashTab === "overview") renderDashboardOverview();
  if (dashTab === "characters") loadCharacters();
  if (dashTab === "imaging") {
    loadImagingConfig();
    populateImgCharSelect();
  }
  if (dashTab === "monitor") loadMonitor();
  refreshGenerationFeedback({ silent: true });
}

function buildMap() {
  const state = currentState();
  const box = document.getElementById("mapContainer");
  if (!state) {
    box.innerHTML = '<div class="empty-state">尚無資料。請先在 Pad 執行 Parse 或 Direct。</div>';
    return;
  }
  const ents = entities();
  const shotList = shots();
  const traceList = traces();
  const width = 920;
  const height = Math.max(420, Math.max(ents.length, shotList.length, traceList.length) * 48 + 80);
  const nodes = [];
  const edges = [];
  ents.forEach((item, index) => {
    const y = 50 + index * ((height - 80) / Math.max(ents.length - 1, 1));
    nodes.push({ id: item.id, label: item.name || item.id, x: 110, y, kind: item.kind, group: "entity" });
  });
  shotList.forEach((item, index) => {
    const y = 50 + index * ((height - 80) / Math.max(shotList.length - 1, 1));
    nodes.push({ id: item.id, label: `#${item.order}`, x: width - 110, y, kind: "shot", group: "shot" });
  });
  traceList.forEach((item, index) => {
    const y = 40 + index * ((height - 60) / Math.max(traceList.length - 1, 1));
    nodes.push({
      id: item.id,
      label: String(item.cause || item.effect || item.id).slice(0, 18),
      x: width / 2,
      y,
      kind: "trace",
      group: "trace",
    });
    if (item.entity_id) edges.push({ from: item.entity_id, to: item.id });
    if (item.shot_id) edges.push({ from: item.id, to: item.shot_id });
  });
  const nodeMap = Object.fromEntries(nodes.map((node) => [node.id, node]));
  const colors = { character: "#6aa6ff", prop: "#9b7bff", scene: "#3ddc97", shot: "#ffcc66", trace: "#ff6b6b" };
  let svg = `<svg width="100%" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg" style="background:#0b0b10;">`;
  svg += `<defs><marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#555"/></marker></defs>`;
  edges.forEach((edge) => {
    const from = nodeMap[edge.from];
    const to = nodeMap[edge.to];
    if (from && to) {
      svg += `<line x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" stroke="#333" stroke-width="1.5" marker-end="url(#arrow)"/>`;
    }
  });
  nodes.forEach((node) => {
    const color = colors[node.kind] || "#aaa";
    const radius = node.group === "trace" ? 7 : 11;
    svg += `<g class="map-node" data-id="${escapeHtml(node.id)}" data-group="${escapeHtml(node.group)}" style="cursor:pointer">
      <circle cx="${node.x}" cy="${node.y}" r="${radius}" fill="${color}" stroke="#0b0b10" stroke-width="2"/>
      <text x="${node.x}" y="${node.y + radius + 14}" text-anchor="middle" fill="#9ca3af" font-size="11">${escapeHtml(node.label)}</text>
    </g>`;
  });
  svg += "</svg>";
  box.innerHTML = svg;
  box.querySelectorAll(".map-node").forEach((node) => {
    node.addEventListener("click", () => inspectMapNode(node.dataset.id, node.dataset.group));
  });
  if (selectedTraceId) inspectMapNode(selectedTraceId, "trace");
}

function inspectMapNode(id, group) {
  if (group === "trace") {
    selectedTraceId = id;
    const trace = traces().find((item) => item.id === id);
    document.getElementById("mapInspector").textContent = pretty(trace || { missing: id });
    setInspector("Trace", trace || { id });
    persistSession();
    return;
  }
  if (group === "shot") {
    selectedShotId = id;
    const shot = shots().find((item) => item.id === id);
    document.getElementById("mapInspector").innerHTML =
      `${escapeHtml(pretty(shot || { id }))}<div class="btn-row" style="margin-top:8px;"><button class="btn btn-secondary btn-sm" type="button" onclick="navigate('Timeline')">跳到 Timeline</button></div>`;
    setInspector("Shot", shot || { id });
    persistSession();
    return;
  }
  const entity = entities().find((item) => item.id === id);
  document.getElementById("mapInspector").textContent = pretty(entity || { id });
  setInspector("Entity", entity || { id });
}

function playerDuration(shot) {
  return Math.max(400, Number(shot?.duration_ms) || 2000);
}

function totalPlayerMs() {
  return shots().reduce((sum, shot) => sum + playerDuration(shot), 0);
}

function refreshPlayer() {
  const list = shots();
  const mux = (currentState() || {}).mux_uri;
  const video = document.getElementById("playerVideo");
  const empty = document.getElementById("playerEmpty");
  const overlay = document.getElementById("playerOverlay");
  const scrub = document.getElementById("playerScrub");
  document.getElementById("playerPhase").textContent = mux ? "mux_uri 就緒" : "Muxer 尚未上線";
  document.getElementById("muxNotice").classList.toggle("hidden", Boolean(mux));
  if (mux) {
    video.classList.remove("hidden");
    empty.classList.add("hidden");
    video.src = String(mux);
    overlay.textContent = "";
    return;
  }
  video.classList.add("hidden");
  if (!list.length) {
    empty.classList.remove("hidden");
    overlay.textContent = "";
    scrub.max = 0;
    return;
  }
  empty.classList.add("hidden");
  if (playerIndex >= list.length) playerIndex = 0;
  scrub.max = String(list.length - 1);
  scrub.value = String(playerIndex);
  renderPlayerFrame();
}

function renderPlayerFrame() {
  const list = shots();
  const shot = list[playerIndex];
  if (!shot) return;
  const overlay = document.getElementById("playerOverlay");
  overlay.innerHTML = `<strong>Shot ${escapeHtml(shot.order)}</strong> · ${escapeHtml(shot.camera_language || "")}<br>${escapeHtml((shot.payload && shot.payload.beat) || "")}`;
  const elapsed = list.slice(0, playerIndex).reduce((sum, item) => sum + playerDuration(item), 0);
  document.getElementById("playerTime").textContent = `${padMs(elapsed)} / ${padMs(totalPlayerMs())}`;
  document.getElementById("playerScrub").value = String(playerIndex);
  setInspector("Player · Shot", shot);
}

function togglePlayer() {
  if (!shots().length && !hasMux()) return;
  if (hasMux()) {
    const video = document.getElementById("playerVideo");
    if (video.paused) video.play();
    else video.pause();
    document.getElementById("btnPlay").textContent = video.paused ? "Play" : "Pause";
    return;
  }
  playerPlaying = !playerPlaying;
  document.getElementById("btnPlay").textContent = playerPlaying ? "Pause" : "Play";
  if (playerPlaying) tickPlayer();
  else if (playerTimer) {
    clearTimeout(playerTimer);
    playerTimer = null;
  }
}

function tickPlayer() {
  if (!playerPlaying) return;
  renderPlayerFrame();
  const list = shots();
  playerTimer = setTimeout(() => {
    playerIndex = (playerIndex + 1) % Math.max(list.length, 1);
    tickPlayer();
  }, playerDuration(list[playerIndex]));
}

function scrubPlayer(value) {
  playerIndex = Number(value) || 0;
  renderPlayerFrame();
}

function assetUrl(charId, path) {
  const raw = String(path || "").trim().replace(/^\/+/, "");
  if (!raw || raw.split("/").includes("..")) return "";
  const encoded = raw.split("/").map(encodeURIComponent).join("/");
  return `${CHAROS_API}/api/v1/characters/${charId}/assets/${encoded}`;
}

function pickThumb(character) {
  const meta = character.metadata || {};
  return meta.face_detail_asset_path || meta.thumbnail_asset_path || meta.thumbnail || "";
}

function filterCharacters() {
  const query = document.getElementById("charSearch").value.trim().toLowerCase();
  const list = query ? allCharacters.filter((item) => (item.name || "").toLowerCase().includes(query)) : allCharacters;
  renderCharList(list);
}

function renderCharList(chars) {
  const box = document.getElementById("charList");
  if (!chars.length) {
    box.innerHTML = '<div style="padding:16px;color:var(--muted);text-align:center;">尚無角色護照。請從劇本同步或手動新增。</div>';
    return;
  }
  box.innerHTML = chars
    .map((item) => {
      const thumb = pickThumb(item);
      const src = thumb ? assetUrl(item.id, thumb) : "";
      const thumbHtml = src
        ? `<img src="${escapeHtml(src)}" alt="" loading="lazy" onerror="this.replaceWith(document.createTextNode('—'))" />`
        : "—";
      return `<div class="char-item${item.id == selectedCharId ? " active" : ""}" onclick="selectChar(${Number(item.id)})">
        <div class="thumb">${thumbHtml}</div>
        <div class="info"><strong>#${escapeHtml(item.id)} ${escapeHtml(item.name || "（未命名）")}</strong><span>${escapeHtml((item.tags || []).join(", ") || "無標籤")}</span></div>
      </div>`;
    })
    .join("");
}

async function loadCharacters() {
  setStatus("charListStatus", "載入中…", "loading");
  try {
    const data = await api(CHAROS_API, "/api/v1/characters?limit=100");
    allCharacters = data || [];
    renderCharList(allCharacters);
    populateImgCharSelect();
    const hint = document.getElementById("charSyncHint");
    if (hint) {
      const parsed = parsedCharacters();
      hint.textContent = parsed.length
        ? `劇本有 ${parsed.length} 個角色。按「從劇本同步」寫入護照。`
        : "Direct 之後可把解析到的角色寫進護照，再去生圖。";
    }
    setStatus("charListStatus", `共 ${allCharacters.length} 筆角色`, "ok");
    updateNavReady();
  } catch (err) {
    setStatus("charListStatus", `載入失敗：${err.message}`, "err");
  }
}

function selectChar(id) {
  selectedCharId = id;
  const found = allCharacters.find((item) => Number(item.id) === Number(id));
  const name = found?.name || "（未命名）";
  document.getElementById("charIdDisplay").textContent = `#${id} · ${name}`;
  const hidden = document.getElementById("imgCharId");
  if (hidden) hidden.value = id;
  const select = document.getElementById("imgCharSelect");
  if (select) select.value = String(id);
  persistSession();
  filterCharacters();
  loadCharEditor();
}

function populateImgCharSelect() {
  const select = document.getElementById("imgCharSelect");
  if (!select) return;
  const current = selectedCharId || select.value;
  select.innerHTML =
    `<option value="">請選擇角色</option>` +
    allCharacters
      .map((item) => `<option value="${escapeHtml(item.id)}">#${escapeHtml(item.id)} ${escapeHtml(item.name || "未命名")}</option>`)
      .join("");
  if (current && allCharacters.some((item) => String(item.id) === String(current))) {
    select.value = String(current);
    document.getElementById("imgCharId").value = current;
  }
}

function onImgCharSelect() {
  const value = document.getElementById("imgCharSelect").value;
  document.getElementById("imgCharId").value = value;
  if (value) selectedCharId = value;
}

async function createCharacterFromForm() {
  const input = document.getElementById("newCharName");
  const name = (input?.value || "").trim();
  if (!name) {
    setStatus("charListStatus", "請輸入角色名稱", "err");
    return;
  }
  setStatus("charListStatus", "建立中…", "loading");
  try {
    const data = await api(CHAROS_API, "/api/v1/characters", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    input.value = "";
    await loadCharacters();
    if (data.id) selectChar(data.id);
    setStatus("charListStatus", data.created ? `✓ 已建立 ${data.name}` : `已有同名角色 ${data.name}`, "ok");
  } catch (err) {
    setStatus("charListStatus", `建立失敗：${err.message}`, "err");
  }
}

async function syncParsedCharacters() {
  const names = parsedCharacters().map((item) => item.name).filter(Boolean);
  if (!names.length) {
    setStatus("charListStatus", "劇本尚未解析到角色。請先 Direct，或手動新增。", "err");
    return [];
  }
  setStatus("charListStatus", "同步中…", "loading");
  try {
    const data = await api(CHAROS_API, "/api/v1/characters/sync-from-script", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ names }),
    });
    await loadCharacters();
    const first = (data.items || [])[0];
    if (first?.id) selectChar(first.id);
    setBanner("noticeBanner", `已同步 ${data.items?.length || 0} 個角色（新增 ${data.created_count || 0}）`);
    setStatus("charListStatus", `✓ 同步完成：新增 ${data.created_count || 0}，既有 ${data.existing_count || 0}`, "ok");
    return data.items || [];
  } catch (err) {
    setStatus("charListStatus", `同步失敗：${err.message}`, "err");
    return [];
  }
}

async function syncParsedCharactersThenPassport() {
  await loadCharacters();
  if (parsedCharacters().length) await syncParsedCharacters();
  goDash("characters");
}

async function loadCharEditor() {
  if (!selectedCharId) {
    setStatus("charEditorStatus", "請先選擇角色", "err");
    return;
  }
  setStatus("charEditorStatus", "載入中…", "loading");
  try {
    const data = await api(CHAROS_API, `/api/v1/characters/${selectedCharId}/editor`);
    const core = data.core || {};
    const profile = data.profile || {};
    document.getElementById("charName").value = core.name || "";
    document.getElementById("charAge").value = core.base_age ?? "";
    document.getElementById("charGender").value = core.gender_spectrum ?? "";
    document.getElementById("charTags").value = (core.tags || []).join(", ");
    document.getElementById("charStylePreset").value = profile.style_preset || "";
    document.getElementById("charManifest").value = pretty(profile.manifest || {});
    document.getElementById("charPassOutput").textContent = pretty(profile.manifest || {});
    setStatus("charEditorStatus", "✓ 已載入", "ok");
    await Promise.all([
      loadCharImageGallery(selectedCharId),
      loadCharAgeBrowser(selectedCharId),
    ]);
  } catch (err) {
    setStatus("charEditorStatus", `載入失敗：${err.message}`, "err");
  }
}

let ageGalleryCache = { charId: null, items: [], selectedAge: null };

async function loadCharAgeBrowser(charId) {
  const strip = document.getElementById("charAgeStrip");
  const meta = document.getElementById("charAgeMeta");
  const face = document.getElementById("charAgeFace");
  const tpose = document.getElementById("charAgeTpose");
  if (!strip || !meta || !face || !tpose) return;
  if (!charId) {
    ageGalleryCache = { charId: null, items: [], selectedAge: null };
    meta.textContent = "選擇角色後可瀏覽 1–80 歲。";
    strip.innerHTML = "";
    face.innerHTML = '<span class="muted">尚未選擇</span>';
    tpose.innerHTML = '<span class="muted">尚未選擇</span>';
    return;
  }
  meta.textContent = "載入年齡圖庫…";
  strip.innerHTML = "";
  try {
    const data = await api(CHAROS_API, `/api/v1/characters/${charId}/age-gallery`);
    const items = data.items || [];
    ageGalleryCache = { charId: Number(charId), items, selectedAge: null };
    meta.textContent = `${data.character_name || ("#" + charId)} · 面部 ${data.face_count || 0}/80 · T 型 ${data.tpose_count || 0}/80`;
    strip.innerHTML = items
      .map((item) => {
        const classes = ["age-chip"];
        if (item.has_face_detail && item.has_tpose) classes.push("has-both");
        else if (item.has_face_detail || item.has_tpose) classes.push("has-face");
        else classes.push("is-empty");
        return `<button type="button" class="${classes.join(" ")}" data-age="${item.age}" onclick="selectCharAge(${item.age})">${item.age}</button>`;
      })
      .join("");
    const preferred =
      items.find((item) => item.has_face_detail || item.has_tpose) ||
      items.find((item) => Number(item.age) === 25) ||
      items[0];
    if (preferred) selectCharAge(preferred.age);
  } catch (err) {
    meta.textContent = `無法載入年齡圖庫：${err.message}`;
    face.innerHTML = '<span class="muted">載入失敗</span>';
    tpose.innerHTML = '<span class="muted">載入失敗</span>';
  }
}

function selectCharAge(age) {
  const strip = document.getElementById("charAgeStrip");
  const face = document.getElementById("charAgeFace");
  const tpose = document.getElementById("charAgeTpose");
  const meta = document.getElementById("charAgeMeta");
  if (!strip || !face || !tpose) return;
  const item = (ageGalleryCache.items || []).find((entry) => Number(entry.age) === Number(age));
  ageGalleryCache.selectedAge = Number(age);
  strip.querySelectorAll(".age-chip").forEach((btn) => {
    btn.classList.toggle("is-active", Number(btn.dataset.age) === Number(age));
  });
  const charId = ageGalleryCache.charId || selectedCharId;
  const faceSrc = item && (item.face_detail_url || assetUrl(charId, item.face_detail_asset_path));
  const tposeSrc = item && (item.tpose_url || assetUrl(charId, item.tpose_asset_path));
  face.innerHTML = faceSrc
    ? `<img src="${escapeHtml(faceSrc)}" alt="${Number(age)} 歲面部" loading="lazy" />`
    : `<span class="muted">${Number(age)} 歲尚無面部圖</span>`;
  tpose.innerHTML = tposeSrc
    ? `<img src="${escapeHtml(tposeSrc)}" alt="${Number(age)} 歲 T 型" loading="lazy" />`
    : `<span class="muted">${Number(age)} 歲尚無 T 型圖</span>`;
  if (meta && item) {
    const bits = [`已選 ${item.age} 歲`];
    bits.push(item.has_face_detail ? "面部 ✓" : "面部 —");
    bits.push(item.has_tpose ? "T 型 ✓" : "T 型 —");
    meta.textContent = bits.join(" · ");
  }
}

async function loadCharImageGallery(charId) {
  const box = document.getElementById("charImageGallery");
  if (!box) return;
  box.innerHTML = '<p class="muted">載入圖片中…</p>';
  try {
    const data = await api(CHAROS_API, `/api/v1/characters/${charId}/versions`);
    const cards = [];
    const seen = new Set();
    const found = allCharacters.find((item) => Number(item.id) === Number(charId));
    const metaThumb = pickThumb(found || {});
    if (metaThumb) {
      seen.add(metaThumb);
      cards.push(previewCardHtml(charId, metaThumb, "目前預覽"));
    }
    (data.branches || []).forEach((branch) => {
      const paths = [
        branch.hero_asset_path,
        branch.face_detail_asset_path,
        branch.thumbnail_asset_path,
        branch.representative_asset_path,
        ...((branch.asset_paths || []).filter(Boolean)),
      ];
      paths.forEach((path) => {
        const clean = String(path || "").trim();
        if (!clean || seen.has(clean)) return;
        seen.add(clean);
        const label = [branch.purpose || branch.kind, branch.status].filter(Boolean).join(" · ");
        cards.push(previewCardHtml(charId, clean, label));
      });
    });
    box.innerHTML = cards.join("") || '<p class="muted">尚無已生成圖片。請到生圖子面板排入任務。</p>';
  } catch (err) {
    box.innerHTML = `<p class="muted">無法載入圖片：${escapeHtml(err.message)}</p>`;
  }
}

function previewCardHtml(charId, path, caption) {
  const src = assetUrl(charId, path);
  if (!src) return "";
  return `<div class="preview-card"><img src="${escapeHtml(src)}" alt="" loading="lazy" onerror="this.parentElement.style.display='none'" /><div class="caption">${escapeHtml(caption || path)}</div></div>`;
}

async function saveCharEditor() {
  if (!selectedCharId) {
    setStatus("charEditorStatus", "請先選擇角色", "err");
    return;
  }
  setStatus("charEditorStatus", "儲存中…", "loading");
  try {
    const payload = {
      name: document.getElementById("charName").value.trim(),
      base_age: Number(document.getElementById("charAge").value || 0),
      gender_spectrum: document.getElementById("charGender").value === "" ? null : Number(document.getElementById("charGender").value),
      tags: document.getElementById("charTags").value.split(",").map((item) => item.trim()).filter(Boolean),
      style_preset: document.getElementById("charStylePreset").value.trim() || null,
      manifest: (() => {
        try {
          return JSON.parse(document.getElementById("charManifest").value || "{}");
        } catch {
          return {};
        }
      })(),
    };
    await api(CHAROS_API, `/api/v1/characters/${selectedCharId}/editor`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setStatus("charEditorStatus", "✓ 儲存成功", "ok");
    loadCharacters();
  } catch (err) {
    setStatus("charEditorStatus", `儲存失敗：${err.message}`, "err");
  }
}

function switchImagingTab(tab) {
  ["generate", "config", "providers"].forEach((name) => {
    document.getElementById("imagingTab-" + name)?.classList.toggle("hidden", name !== tab);
  });
  document.querySelectorAll("#imagingTabs button").forEach((btn, index) => {
    btn.classList.toggle("active", ["generate", "config", "providers"][index] === tab);
  });
  if (tab === "providers") loadProviders();
  if (tab === "generate") populateImgCharSelect();
}

async function loadImagingConfig() {
  setStatus("imgCfgStatus", "讀取中…", "loading");
  try {
    const data = await api(CHAROS_API, "/api/v1/admin/imaging-config");
    document.getElementById("imgProvider").value = data.provider || "wan";
    document.getElementById("imgModel").value = data.model || "";
    document.getElementById("imgBaseUrl").value = data.base_url || "";
    setStatus("imgCfgStatus", `已載入。API Key：${data.has_api_key ? "已設定" : "尚未設定"}`, "ok");
  } catch (err) {
    setStatus("imgCfgStatus", `讀取失敗：${err.message}`, "err");
  }
}

async function saveImagingConfig() {
  const payload = {
    provider: document.getElementById("imgProvider").value,
    base_url: document.getElementById("imgBaseUrl").value.trim(),
    model: document.getElementById("imgModel").value.trim(),
    persist_env: true,
  };
  const key = document.getElementById("imgApiKey").value.trim();
  if (key) payload.api_key = key;
  setStatus("imgCfgStatus", "儲存中…", "loading");
  try {
    const data = await api(CHAROS_API, "/api/v1/admin/imaging-config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setStatus("imgCfgStatus", `✓ 已更新。API Key：${data.has_api_key ? "已設定" : "尚未設定"}`, "ok");
  } catch (err) {
    setStatus("imgCfgStatus", `儲存失敗：${err.message}`, "err");
  }
}

async function loadProviders() {
  try {
    const data = await api(CHAROS_API, "/api/v1/imaging/providers");
    document.getElementById("imgProvidersOutput").textContent = pretty(data);
  } catch (err) {
    document.getElementById("imgProvidersOutput").textContent = `載入失敗：${err.message}`;
  }
}

function phaseLabel(phase) {
  return (
    {
      face_detail: "面部",
      tpose: "T 型",
      identity: "身份",
      outfit: "服裝",
      expression: "表情",
      thumb: "縮圖",
      age_span: "年齡軸",
    }[String(phase || "")] || phase || "生圖"
  );
}

function taskImageRequest(task) {
  return ((task && task.evolution_params) || {})._image_request || {};
}

function taskStepLabel(task) {
  const req = taskImageRequest(task);
  const phase = phaseLabel(req.phase || req.purpose || task.purpose);
  if (req.age === 0 || req.age) return `${phase} ${req.age} 歲`;
  return phase;
}

function elapsedLabel(startedAt) {
  if (!startedAt) return "";
  const start = new Date(startedAt).getTime();
  if (Number.isNaN(start)) return "";
  const total = Math.max(0, Math.round((Date.now() - start) / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return m ? `${m} 分 ${s} 秒` : `${s} 秒`;
}

function phaseCounts(steps, phase) {
  const items = (steps || []).filter((item) => item.phase === phase);
  const done = items.filter((item) => item.status === "accepted" || item.status === "ready").length;
  return { done, total: items.length };
}

function ensureGenPoll(busy) {
  const want = currentPage === "Dashboard";
  const ms = busy ? 2000 : 8000;
  if (!want) {
    if (queueTimer) {
      clearInterval(queueTimer);
      queueTimer = null;
    }
    return;
  }
  if (queueTimer && ensureGenPoll.ms === ms) return;
  if (queueTimer) clearInterval(queueTimer);
  ensureGenPoll.ms = ms;
  queueTimer = setInterval(() => refreshGenerationFeedback({ silent: true }), ms);
}

function renderGenerationLive(worker, span) {
  const box = document.getElementById("genLive");
  if (!box) return false;
  const current = worker.current_task || {};
  const running = Boolean(worker.busy || worker.running_count || current.id);
  const failed = Boolean((span && span.failed_count) || worker.last_status === "failed" || worker.failed_count);
  const open = Boolean(span && span.has_open_pipeline);
  const paused = Boolean(worker.paused);
  if (!running && !open && !paused && !failed && !worker.auto_run) {
    box.className = "gen-live hidden";
    box.innerHTML = "";
    return false;
  }
  const pct = span && span.total_steps ? Math.round((span.accepted_count / span.total_steps) * 100) : running ? 5 : 0;
  const workerLabel = paused ? "已暫停" : running ? "生成中" : worker.auto_run ? "排隊中" : "待命";
  let tone = "idle";
  if (failed && span && span.blocking_reason) tone = "err";
  else if (paused) tone = "warn";
  else if (running) tone = "busy";
  const elapsed = current.started_at ? elapsedLabel(current.started_at) : "";
  const currentLine = current.id
    ? `${current.character_name || "角色"} · ${escapeHtml(current.label || taskStepLabel(current))}${elapsed ? ` · 已過 ${elapsed}` : ""}`
    : span && span.next_age != null
      ? `下一步 ${phaseLabel(span.next_phase)} ${span.next_age} 歲`
      : "等待 worker 接下一步";
  const headline = (span && span.headline) || (running ? "正在向模型請求生圖，請稍候。" : "佇列待命");
  const faces = phaseCounts(span && span.steps, "face_detail");
  const tposes = phaseCounts(span && span.steps, "tpose");
  const hint = paused
    ? "目前這張仍會跑完，之後不會自動接下一步。"
    : failed && span && span.blocking_reason
      ? span.blocking_reason
      : "一次只生成一張。完成後自動入庫，再接下一步。呼叫模型常需 20–60 秒。";
  box.className = `gen-live ${tone}`;
  box.innerHTML = `
    <div class="gen-live-head">
      <div>
        <div class="gen-live-title">${escapeHtml(headline)}</div>
        <div class="gen-live-meta">${escapeHtml(currentLine)}</div>
      </div>
      <span class="badge ${running ? "badge-live" : failed ? "badge-failed" : "badge-pending"}">${escapeHtml(workerLabel)}</span>
    </div>
    <div class="progress" title="${pct}%"><span style="width:${pct}%"></span></div>
    <div class="gen-live-phases">
      <span>總進度 ${span ? `${span.accepted_count || 0}/${span.total_steps || 0}` : "—"}</span>
      ${faces.total ? `<span>面部 ${faces.done}/${faces.total}</span>` : ""}
      ${tposes.total ? `<span>T 型 ${tposes.done}/${tposes.total}</span>` : ""}
      <span>等待 ${worker.pending_count || 0} · 排隊 ${worker.waiting_count || 0} · 失敗 ${worker.failed_count || 0}</span>
    </div>
    <p class="hint" style="margin-top:8px;">${escapeHtml(hint)}</p>
  `;
  return running || open || paused;
}

async function refreshGenerationFeedback(opts = {}) {
  const silent = Boolean(opts.silent);
  if (currentPage !== "Dashboard") {
    ensureGenPoll(false);
    return;
  }
  let worker = {};
  let span = null;
  try {
    worker = await api(CHAROS_API, "/api/v1/admin/queue-worker");
  } catch {
    worker = {};
  }
  const coreId = document.getElementById("queueCoreId")?.value.trim() || document.getElementById("imgCharId")?.value || "";
  try {
    const params = new URLSearchParams();
    if (coreId) params.set("core_id", coreId);
    span = await api(CHAROS_API, `/api/v1/admin/queue-tasks/age-span-status?${params}`);
  } catch {
    span = null;
  }
  const busy = renderGenerationLive(worker, span);
  ensureGenPoll(busy);
  if (span && lastGenAccepted !== null && span.accepted_count > lastGenAccepted) {
    const label = span.headline || `已完成 ${span.accepted_count}/${span.total_steps}`;
    setBanner("noticeBanner", label);
  }
  if (span) lastGenAccepted = span.accepted_count;
  const taskKey = worker.current_task && worker.current_task.id ? String(worker.current_task.id) : "";
  if (taskKey && taskKey !== lastGenTaskKey && worker.busy) {
    lastGenTaskKey = taskKey;
  }
  if (dashTab === "queue") {
    await loadQueue({ silent: true });
  }
  if (!silent && document.getElementById("queueStatus") && dashTab === "queue") {
    const line = (span && span.headline) || (worker.paused ? "worker 已暫停" : busy ? "正在生成" : "佇列待命");
    setStatus("queueStatus", line, span && span.failed_count ? "err" : busy ? "loading" : "ok");
  }
}

async function queueImageGeneration() {
  const charId = document.getElementById("imgCharId").value || document.getElementById("imgCharSelect")?.value;
  if (!charId) {
    setStatus("imgGenStatus", "請先選擇角色。若清單是空的，請先從劇本同步護照。", "err");
    return;
  }
  const found = allCharacters.find((item) => String(item.id) === String(charId));
  const name = found?.name || `#${charId}`;
  const purpose = document.getElementById("imgPurpose").value;
  setStatus("imgGenStatus", `正在為 ${name} 排入 ${phaseLabel(purpose)}…`, "loading");
  try {
    let imaging = {};
    try {
      imaging = await api(CHAROS_API, "/api/v1/admin/imaging-config");
    } catch (_err) {
      imaging = {};
    }
    const provider = (document.getElementById("imgProvider")?.value || imaging.provider || "").trim();
    const model = (document.getElementById("imgModel")?.value || imaging.model || "").trim();
    const baseUrl = (document.getElementById("imgBaseUrl")?.value || imaging.base_url || "").trim();
    const payload = {
      purpose,
      extra: document.getElementById("imgExtra").value.trim(),
      persist: true,
    };
    if (provider) payload.provider = provider;
    if (model) payload.model = model;
    if (baseUrl) payload.base_url = baseUrl;
    const data = await api(CHAROS_API, `/api/v1/characters/${charId}/image-queue`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CharacterOS-Panel": "enabled" },
      body: JSON.stringify(payload),
    });
    const queued = data.pipeline === "age_span"
      ? `年齡軸已開始（目前佇列 ${data.created ?? data.total ?? 1} 步，其餘會在每張完成後自動接上）`
      : `任務已排入${data.task && data.task.id ? ` #${data.task.id}` : ""}`;
    document.getElementById("imgGenOutput").textContent = pretty(data);
    setStatus("imgGenStatus", `✓ ${name}：${queued}。正在呼叫模型，請看上方生圖進度。`, "ok");
    const queueCore = document.getElementById("queueCoreId");
    if (queueCore) queueCore.value = charId;
    await startAutoPipeline();
    goDash("queue");
    await refreshGenerationFeedback({ silent: false });
  } catch (err) {
    setStatus("imgGenStatus", `排入失敗：${err.message}`, "err");
    document.getElementById("imgGenOutput").textContent = err.message;
  }
}

async function loadQueue(opts = {}) {
  const statusEl = document.getElementById("queueStatus");
  if (!statusEl) return;
  const silent = Boolean(opts.silent);
  if (!silent) setStatus("queueStatus", "載入中…", "loading");
  try {
    const params = new URLSearchParams();
    const status = document.getElementById("queueFilter").value;
    const coreId = document.getElementById("queueCoreId").value.trim();
    if (status) params.set("status", status);
    if (coreId) params.set("core_id", coreId);
    params.set("limit", "200");
    const data = await api(CHAROS_API, `/api/v1/admin/queue-tasks?${params}`);
    lastQueueTasks = data.tasks || [];
    renderQueueStats(data.stats || {});
    renderQueueTasks(lastQueueTasks);
    renderQueuePreview(lastQueueTasks);
    const running = lastQueueTasks.find((item) => item.status === "running");
    const line = running
      ? `正在生成 ${taskStepLabel(running)} · 已過 ${elapsedLabel(running.started_at || running.updated_at) || "數秒"}`
      : `共 ${data.total ?? lastQueueTasks.length} 筆任務`;
    setStatus("queueStatus", line, running ? "loading" : "ok");
  } catch (err) {
    if (!silent) setStatus("queueStatus", `載入失敗：${err.message}`, "err");
    document.getElementById("queueBody").innerHTML =
      `<tr><td colspan="7" style="text-align:center;color:var(--red);padding:16px;">${escapeHtml(err.message)}</td></tr>`;
  }
}

function renderQueueStats(stats) {
  document.getElementById("queueStatsRow").innerHTML = `
    <span class="stat-chip"><span class="num">${stats.total_pending || 0}</span> 等待中</span>
    <span class="stat-chip"><span class="num">${stats.total_running || 0}</span> 生成中</span>
    <span class="stat-chip"><span class="num">${stats.total_waiting || 0}</span> 排隊中</span>
    <span class="stat-chip"><span class="num">${stats.total_ready || 0}</span> 已完成</span>
    <span class="stat-chip"><span class="num">${stats.total_failed || 0}</span> 失敗</span>
    <span class="stat-chip">平均等待 ${Math.round(stats.average_wait_time_ms || 0)}ms</span>
  `;
}

function renderQueueTasks(tasks) {
  const body = document.getElementById("queueBody");
  if (!tasks.length) {
    body.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:24px;">無任務</td></tr>';
    return;
  }
  body.innerHTML = tasks
    .map((task) => {
      const status = task.status || "pending";
      const req = taskImageRequest(task);
      const name = task.character_name ? `#${task.core_id} · ${task.character_name}` : `#${task.core_id}`;
      const step = taskStepLabel(task);
      const progress =
        req.step_index && req.total_steps
          ? `${req.step_index}/${req.total_steps}`
          : status === "running"
            ? "生成中"
            : "—";
      const when =
        status === "running"
          ? `已過 ${elapsedLabel(task.started_at || task.updated_at) || "數秒"}`
          : formatTime(task.updated_at || task.created_at);
      const actions = [];
      if (status === "ready") actions.push(`<button class="btn btn-sm btn-secondary" type="button" onclick="acceptTask(${task.id})">接受</button>`);
      if (status === "failed") actions.push(`<button class="btn btn-sm btn-secondary" type="button" onclick="resetTask(${task.id})">重設</button>`);
      const rowClass = status === "running" ? " queue-running" : status === "failed" ? " queue-failed" : "";
      return `<tr class="${rowClass}">
        <td>${escapeHtml(task.id)}</td><td>${escapeHtml(name)}</td>
        <td><span class="badge ${escapeHtml(badgeClass(status))}">${escapeHtml(statusLabel(status))}</span></td>
        <td>${escapeHtml(step)}</td>
        <td>${escapeHtml(progress)}</td>
        <td>${escapeHtml(when)}</td>
        <td>${actions.join(" ") || "—"}</td>
      </tr>`;
    })
    .join("");
}

function collectTaskPreviewImages(task) {
  const meta = task.result_metadata || {};
  const ig = meta.image_generation || {};
  const out = [];
  const seen = new Set();
  const push = (path, angle) => {
    const clean = String(path || "").trim();
    if (!clean || seen.has(clean)) return;
    seen.add(clean);
    out.push({ asset_path: clean, angle: angle || "" });
  };
  (ig.images || []).forEach((img) => {
    if (!img) return;
    push(img.asset_path || img.final_asset_path || img.filename, img.angle);
  });
  push(task.face_detail_asset_path || meta.face_detail_asset_path || ig.face_detail_asset_path, "face_detail");
  push(task.representative_asset_path || meta.representative_asset_path || ig.representative_asset_path, "preview");
  push(task.thumbnail_asset_path || meta.thumbnail_asset_path || ig.thumbnail_asset_path, "thumb");
  (ig.asset_paths || meta.asset_paths || []).forEach((path) => push(path, ""));
  const byAngle = ig.images_by_angle || {};
  Object.entries(byAngle).forEach(([angle, entries]) => {
    (Array.isArray(entries) ? entries : []).forEach((item) => {
      if (typeof item === "string") push(item, angle);
      else if (item && typeof item === "object") push(item.asset_path || item.path, angle);
    });
  });
  return out;
}

function renderQueuePreview(tasks) {
  const cards = [];
  tasks.forEach((task) => {
    collectTaskPreviewImages(task).forEach((img) => {
      const src = assetUrl(task.core_id, img.asset_path);
      if (!src) return;
      cards.push(
        `<div class="preview-card"><img src="${escapeHtml(src)}" alt="" loading="lazy" onerror="this.parentElement.style.display='none'" /><div class="caption">#${escapeHtml(task.core_id)} ${escapeHtml(task.character_name || "")} · ${escapeHtml(img.angle || taskStepLabel(task))}</div></div>`,
      );
    });
  });
  document.getElementById("queuePreview").innerHTML = cards.join("") || '<p class="muted">無預覽圖。完成生圖後會顯示在此與角色護照。</p>';
}

async function acceptTask(id) {
  try {
    await api(CHAROS_API, `/api/v1/admin/queue-tasks/${id}/accept`, { method: "POST" });
    loadQueue();
  } catch (err) {
    setBanner("errorBanner", `接受失敗：${err.message}`);
  }
}

async function resetTask(id) {
  try {
    await api(CHAROS_API, `/api/v1/admin/queue-tasks/${id}/reset`, { method: "POST" });
    loadQueue();
  } catch (err) {
    setBanner("errorBanner", `重設失敗：${err.message}`);
  }
}

async function acceptAllReady() {
  const coreId = document.getElementById("queueCoreId").value.trim();
  const params = new URLSearchParams();
  if (coreId) params.set("core_id", coreId);
  try {
    const data = await api(CHAROS_API, `/api/v1/admin/queue-tasks/accept-all?${params}`, { method: "POST" });
    setStatus("queueStatus", `已批次接受 ${data.accepted || 0} 筆任務`, "ok");
    loadQueue();
  } catch (err) {
    setStatus("queueStatus", `批次接受失敗：${err.message}`, "err");
  }
}

async function startAutoPipeline() {
  try {
    await api(CHAROS_API, "/api/v1/admin/queue-worker/start", { method: "POST" });
    setStatus("queueStatus", "✓ 後端已開始生圖：一次一張，完成後自動入庫", "ok");
    await refreshGenerationFeedback({ silent: false });
  } catch (err) {
    setStatus("queueStatus", `啟動失敗：${err.message}`, "err");
  }
}

async function stopAutoPipeline() {
  try {
    await api(CHAROS_API, "/api/v1/admin/queue-worker/pause", { method: "POST" });
    setStatus("queueStatus", "已暫停。目前這張仍會跑完。", "ok");
    await refreshGenerationFeedback({ silent: true });
  } catch (err) {
    setStatus("queueStatus", `暫停失敗：${err.message}`, "err");
  }
}

async function resetFailed() {
  const coreId = document.getElementById("queueCoreId").value.trim();
  const params = new URLSearchParams();
  if (coreId) params.set("core_id", coreId);
  try {
    const data = await api(CHAROS_API, `/api/v1/admin/queue-tasks/reset-failed?${params}`, { method: "POST" });
    setStatus("queueStatus", `✓ 已重設 ${data.reset || 0} 筆失敗任務`, "ok");
    loadQueue();
  } catch (err) {
    setStatus("queueStatus", `重設失敗：${err.message}`, "err");
  }
}

async function loadMonitor() {
  try {
    const health = await api(CHAROS_API, "/api/v1/health");
    document.getElementById("monitorHealth").textContent = pretty(health);
  } catch (err) {
    document.getElementById("monitorHealth").textContent = `失敗：${err.message}`;
  }
  try {
    const metrics = await api(CHAROS_API, "/api/v1/admin/metrics");
    document.getElementById("monitorMetrics").textContent = pretty(metrics);
    document.getElementById("monitorStats").innerHTML = `
      <span class="stat-chip"><span class="num">${metrics.total_characters || 0}</span> 角色</span>
      <span class="stat-chip"><span class="num">${metrics.total_profiles || 0}</span> Profile</span>
      <span class="stat-chip"><span class="num">${metrics.total_variants || 0}</span> 變體</span>
    `;
  } catch (err) {
    document.getElementById("monitorMetrics").textContent = `失敗：${err.message}`;
  }
  try {
    const worker = await api(CHAROS_API, "/api/v1/admin/queue-worker");
    document.getElementById("monitorWorker").textContent = pretty(worker);
  } catch (err) {
    document.getElementById("monitorWorker").textContent = `失敗：${err.message}`;
  }
}

async function checkHealth() {
  const dot = document.getElementById("healthDot");
  const label = document.getElementById("healthLabel");
  try {
    const data = await api(CHAROS_API, "/api/v1/health");
    dot.style.background = "var(--green)";
    label.textContent = `CharacterOS · ${data.storage_mode || data.status || "ok"}`;
  } catch {
    dot.style.background = "var(--red)";
    label.textContent = "CharacterOS 離線";
  }
}

document.querySelectorAll(".nav-item[data-page]").forEach((btn) => {
  btn.addEventListener("click", () => navigate(btn.dataset.page));
});
document.getElementById("padScript")?.addEventListener("input", () => {
  updatePadButtons();
  persistSession();
});
window.addEventListener("hashchange", () => {
  const page = location.hash.slice(1) || "Pad";
  navigate(HASH_ALIASES[page] || page, { skipHash: true });
  if (DASH_ALIASES[page]) setDashTab(DASH_ALIASES[page]);
});
window.addEventListener("keydown", (event) => {
  if (currentPage !== "Dashboard" || dashTab !== "characters") return;
  if (event.target && ["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName)) return;
  if (event.key === "s" || event.key === "S") {
    event.preventDefault();
    saveCharEditor();
  }
});

restoreSession();
updatePadButtons();
updateNavReady();
checkHealth();
setInterval(checkHealth, 30000);
loadCharacters();
const initHash = location.hash.slice(1) || "Pad";
navigate(HASH_ALIASES[initHash] || initHash, { skipHash: true });
if (DASH_ALIASES[initHash]) setDashTab(DASH_ALIASES[initHash]);
applyInspectorVisibility();
