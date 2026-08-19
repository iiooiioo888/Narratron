"""CharacterOS GUI 管理面板。"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Panel"])


@router.get("/admin/panel", response_class=HTMLResponse)
def get_admin_panel() -> str:
    """提供角色 GUI 管理/生成面板。"""
    return """<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CharacterOS Full Editor</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; color: #1f2937; }
    h1 { margin-bottom: 8px; }
    .hint { color: #6b7280; margin-bottom: 20px; line-height: 1.5; }
    .field-hint { font-size: 12px; color: #9ca3af; margin: -4px 0 8px; line-height: 1.45; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .card { border: 1px solid #d1d5db; border-radius: 10px; padding: 14px; }
    .card h2 { margin-top: 0; font-size: 18px; }
    .card .section-desc { font-size: 13px; color: #6b7280; margin: -4px 0 12px; line-height: 1.45; }
    label { display: block; font-size: 13px; font-weight: 600; margin: 8px 0 4px; }
    input, select, textarea, button { width: 100%; box-sizing: border-box; padding: 8px; margin-bottom: 8px; }
    button { cursor: pointer; border: 0; border-radius: 8px; background: #2563eb; color: #fff; }
    button.secondary { background: #374151; }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
    pre { background: #111827; color: #e5e7eb; padding: 10px; border-radius: 8px; max-height: 320px; overflow: auto; }
    .list { max-height: 320px; overflow: auto; border: 1px solid #e5e7eb; border-radius: 8px; padding: 8px; }
    .item { padding: 8px; border-bottom: 1px solid #f3f4f6; cursor: pointer; border-radius: 6px; display: grid; grid-template-columns: 56px 1fr; gap: 10px; align-items: center; }
    .item:hover { background: #f9fafb; }
    .item.active { background: #eff6ff; border: 1px solid #93c5fd; }
    .item:last-child { border-bottom: 0; }
    .item-thumb { width: 56px; height: 56px; border-radius: 10px; overflow: hidden; background: #f3f4f6; border: 1px solid #e5e7eb; display: grid; place-items: center; color: #9ca3af; font-size: 12px; }
    .item-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .item-main { min-width: 0; }
    .item-main strong, .item-main span { display: block; }
    .inline { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .status { font-size: 13px; color: #4b5563; min-height: 1.2em; }
    .status.ok { color: #059669; }
    .status.err { color: #dc2626; }
    .id-badge { display: inline-block; padding: 6px 10px; border-radius: 8px; background: #f3f4f6; font-family: Consolas, monospace; font-size: 14px; margin-bottom: 8px; }
    .id-badge.empty { color: #9ca3af; font-style: italic; font-family: inherit; }
    textarea.json { min-height: 110px; font-family: Consolas, monospace; }
    .steps { font-size: 13px; color: #374151; background: #f9fafb; border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; line-height: 1.55; }
    .steps ol { margin: 6px 0 0 18px; padding: 0; }
    .full-span { grid-column: 1 / -1; }
    .stat-row { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
    .stat-chip { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 999px; background: #f3f4f6; font-size: 13px; }
    .stat-chip.pending { background: #fef3c7; color: #92400e; }
    .stat-chip.ready { background: #d1fae5; color: #065f46; }
    .stat-chip.failed { background: #fee2e2; color: #991b1b; }
    .stat-chip.mode { background: #eff6ff; color: #1d4ed8; }
    .queue-toolbar { display: grid; grid-template-columns: 1fr 1fr auto auto auto auto auto; gap: 8px; align-items: end; margin-bottom: 10px; }
    .queue-toolbar label { margin-top: 0; }
    .queue-toolbar button { margin-bottom: 0; }
    .queue-table-wrap { overflow: auto; border: 1px solid #e5e7eb; border-radius: 8px; max-height: 360px; }
    table.queue-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    table.queue-table th, table.queue-table td { padding: 8px 10px; border-bottom: 1px solid #f3f4f6; text-align: left; vertical-align: top; }
    table.queue-table th { background: #f9fafb; position: sticky; top: 0; z-index: 1; }
    table.queue-table tr:hover td { background: #f9fafb; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; }
    .badge.pending { background: #fef3c7; color: #92400e; }
    .badge.ready { background: #d1fae5; color: #065f46; }
    .badge.failed { background: #fee2e2; color: #991b1b; }
    .mono { font-family: Consolas, monospace; font-size: 12px; word-break: break-all; }
    .queue-empty { padding: 16px; color: #9ca3af; text-align: center; }
    .queue-actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
    .queue-actions button { width: auto; margin: 0; padding: 6px 10px; font-size: 12px; }
    .queue-actions a { font-size: 12px; color: #2563eb; text-decoration: none; }
    .preview-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; margin-top: 14px; }
    .preview-card { border: 1px solid #e5e7eb; border-radius: 10px; padding: 8px; background: #fff; }
    .preview-card img { width: 100%; height: 160px; object-fit: cover; border-radius: 8px; background: #f3f4f6; }
    .preview-card .caption { margin-top: 6px; font-size: 12px; color: #4b5563; word-break: break-word; }
    @media (max-width: 960px) {
      .grid { grid-template-columns: 1fr; }
      .queue-toolbar { grid-template-columns: 1fr 1fr; }
    }
  </style>
</head>
<body>
  <h1>CharacterOS 完整角色編輯器</h1>
  <div class="hint">
    集中管理角色 Core／Profile／Manifest、視覺風格與生圖流程。
    <strong>角色 ID 由系統自動分配</strong>，請從左側清單點選角色，無需手動輸入編號。
    若 PostgreSQL 未啟動，會自動改讀寫本機 <code>data/charpasses/</code> 進行測試。
    生圖僅能在此 GUI 面板操作，API 直連生圖入口已停用。
  </div>

  <div class="grid">
    <section class="card">
      <h2>角色清單</h2>
      <p class="section-desc">點選一筆角色後，編輯器與生圖區會自動帶入該角色的系統 ID。</p>
      <label>名稱搜尋</label>
      <div class="field-hint">支援模糊比對；留空則列出全部角色。</div>
      <input id="searchName" placeholder="例如：卡爾、主角、反派…" />
      <button onclick="loadCharacters()">重新載入清單</button>
      <div id="characterList" class="list"></div>
      <div id="listStatus" class="status"></div>
    </section>

    <section class="card">
      <h2>完整角色編輯（Core + Profile）</h2>
      <p class="section-desc">編輯核心身份與專案 Profile；manifest 內的 <code>_style.character_style</code> 會影響生圖提示詞。</p>
      <label>目前選擇的角色 ID（系統分配，唯讀）</label>
      <div class="field-hint">由資料庫自動編號；切換角色請回到左側清單點選。</div>
      <div id="characterIdDisplay" class="id-badge empty">尚未選擇角色</div>
      <input id="characterId" type="hidden" value="" />
      <div class="inline">
        <button id="btnLoadEditor" onclick="loadCharacterEditor()" disabled>載入編輯資料</button>
        <button id="btnSaveEditor" class="secondary" onclick="saveCharacterEditor()" disabled>儲存角色</button>
      </div>

      <label>名稱／代號</label>
      <div class="field-hint">名稱為顯示用；代號可填內部識別碼（可留空）。</div>
      <div class="inline">
        <input id="editName" placeholder="角色名稱，例如：卡爾" />
        <input id="editCodename" placeholder="代號，例如：K-01（可留空）" />
      </div>

      <label>基準年齡／性別光譜</label>
      <div class="field-hint">性別光譜 0～1：0 偏陽剛、1 偏陰柔、0.5 中性；變體生圖時可用「年齡」覆蓋基準年齡。</div>
      <div class="inline">
        <input id="editBaseAge" type="number" min="0" max="150" placeholder="基準年齡，例如：28" />
        <input id="editGenderSpectrum" type="number" min="0" max="1" step="0.1" placeholder="性別光譜 0～1" />
      </div>

      <label>標籤 tags（逗號分隔）</label>
      <div class="field-hint">用於搜尋與分類，例如：protagonist, modern, cyberpunk</div>
      <input id="editTags" placeholder="protagonist, modern" />

      <label>identity_anchor（身份錨點 JSON）</label>
      <div class="field-hint">鎖定臉部／髮型等不可變特徵；生圖時用於維持角色一致性。</div>
      <textarea id="editIdentityAnchor" class="json" placeholder='{"face_shape":"oval","hair":"short black"}'></textarea>

      <label>metadata（擴充 JSON）</label>
      <div class="field-hint">任意鍵值，不參與生圖 prompt 組裝。</div>
      <textarea id="editMetadata" class="json"></textarea>

      <label>風格預設／建立者</label>
      <div class="inline">
        <input id="editStylePreset" placeholder="style_preset，例如：cinematic_realistic" />
        <input id="editCreatedBy" placeholder="created_by，例如：gui-panel" />
      </div>

      <label>專案名稱／專案 ID</label>
      <div class="inline">
        <input id="editProjectName" placeholder="專案名稱，例如：Episode 01" />
        <input id="editProjectId" placeholder="專案 ID（可留空）" />
      </div>

      <label>outfit_config（服裝 JSON）</label>
      <div class="field-hint">預設服裝與配件設定；purpose=outfit 生圖時會參考。</div>
      <textarea id="editOutfitConfig" class="json"></textarea>

      <label>manifest JSON（含 _style／角色風格）</label>
      <div class="field-hint">完整護照 manifest；<code>_style.character_style</code> 含 art_prompt、reference_images 等生圖必要欄位。</div>
      <textarea id="editManifest" class="json" style="min-height: 180px;"></textarea>

      <label>備註 notes</label>
      <textarea id="editNotes" rows="3" placeholder="給自己的備註，不會寫進生圖 prompt"></textarea>
      <div id="editorStatus" class="status"></div>
    </section>

    <section class="card">
      <h2>生圖設定（WAN／OpenAI 相容）</h2>
      <p class="section-desc">設定第三方生圖 API；儲存後僅供本面板「生成圖片」使用，不開放公開 API 直連。</p>
      <button onclick="loadImagingConfig()">讀取目前設定</button>
      <label>Provider（生圖後端）</label>
      <div class="field-hint">wan＝阿里百煉；openai＝OpenAI 相容；http＝自訂 webhook；null＝只組 prompt 不呼叫網路（測試用）。</div>
      <select id="provider">
        <option value="wan">wan（阿里百煉 WAN）</option>
        <option value="openai">openai（OpenAI 相容介面）</option>
        <option value="http">http（自訂 HTTP webhook）</option>
        <option value="null">null（僅組 prompt，不打 API）</option>
      </select>
      <label>Base URL（API 端點）</label>
      <div class="field-hint">WAN 可填 compatible-mode/v1；留空則使用已儲存的設定。</div>
      <input id="baseUrl" value="https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1" />
      <label>Model（模型名稱）</label>
      <div class="field-hint">例如 wan2.7-image-pro；依 provider 文件填寫。</div>
      <input id="model" value="wan2.7-image-pro" />
      <label>API Key（留空代表不修改已儲存的金鑰）</label>
      <input id="apiKey" type="password" placeholder="sk-… 或百煉 API Key" />
      <label><input id="persistEnv" type="checkbox" checked style="width:auto;margin-right:6px;" /> 同步寫入專案根目錄 .env</label>
      <button onclick="saveImagingConfig()">儲存生圖設定</button>
      <div id="cfgStatus" class="status"></div>
    </section>

    <section class="card">
      <h2>變體／生圖</h2>
      <p class="section-desc">依選中角色請求演化變體，並把第三方生圖工作排入同一個佇列，交由下方任務面板實際執行。</p>
      <div class="steps">
        <strong>建議流程</strong>
        <ol>
          <li>左側清單點選角色（ID 自動帶入）</li>
          <li>（可選）填寫變體參數 → 按「請求變體」</li>
          <li>選擇生圖用途 → 可填額外風格 → 按「生成圖片」排入任務</li>
          <li>到下方佇列任務面板按「執行」或「處理全部 pending」</li>
          <li>任務完成後可直接在面板預覽圖片，並用「複製最後提示詞」備份 prompt</li>
        </ol>
      </div>
      <label>目前選擇的角色 ID（與編輯器同步，唯讀）</label>
      <div id="imgCharacterIdDisplay" class="id-badge empty">尚未選擇角色</div>
      <input id="imgCharacterId" type="hidden" value="" />

      <label>變體參數（皆可留空，留空則使用 Profile 基準值）</label>
      <div class="field-hint">先請求變體可預先排入佇列；生圖仍可直接使用目前 manifest。</div>
      <div class="inline">
        <input id="age" type="number" min="0" max="150" placeholder="目標年齡，例如：45" />
        <input id="emotion" placeholder="情緒：neutral / happy / sad / angry" />
      </div>
      <div class="inline">
        <input id="scene" placeholder="場景：battle / formal_event / casual_street" />
        <input id="injury" type="number" min="0" max="1" step="0.1" placeholder="受傷程度 0～1" />
      </div>
      <button id="btnVariant" class="secondary" onclick="requestVariant()" disabled>請求變體（排入佇列）</button>

      <label>生圖用途 Purpose</label>
      <div class="field-hint">identity＝身份參考；outfit＝服裝；expression＝表情；thumb＝縮圖。每次生圖預設產出<strong>多視角</strong>（正／背／左／右／四分之三／頂／底），其中 identity 會額外補 1 張面部細節圖。</div>
      <select id="purpose">
        <option value="identity">identity（身份／臉部參考）</option>
        <option value="outfit">outfit（服裝造型）</option>
        <option value="expression">expression（表情特寫）</option>
        <option value="thumb">thumb（縮圖預覽）</option>
      </select>

      <label>額外風格描述（會拼進 prompt）</label>
      <div class="field-hint">疊加在 manifest 內 <code>_style.character_style</code> 之上；可寫畫風、光線、構圖等中文或英文關鍵詞。</div>
      <textarea id="extra" rows="3" placeholder="例如：賽博龐克霓虹、電影級側光、油畫筆觸、8K 細節、霧面膚質"></textarea>

      <div class="inline">
        <button id="btnGenerate" onclick="generateImages()" disabled>生成圖片（排入佇列）</button>
        <button id="btnCopyPrompt" class="secondary" onclick="copyPrompt()" disabled>複製最後提示詞</button>
      </div>
      <label>變體 API 回應</label>
      <pre id="variantOutput">{}</pre>
      <label>生圖 API 回應</label>
      <pre id="imageOutput">{}</pre>
      <div id="imgStatus" class="status"></div>
    </section>

    <section class="card full-span">
      <h2>佇列任務面板</h2>
      <p class="section-desc">
        檢視變體生成佇列（pending／ready／failed）。
        PostgreSQL 未啟動時，任務寫入本機 <code>data/charpasses/.characteros-queue.json</code>。
      </p>

      <div id="queueStats" class="stat-row"></div>

      <div class="queue-toolbar">
        <div>
          <label>狀態篩選</label>
          <select id="queueStatusFilter">
            <option value="">全部狀態</option>
            <option value="pending">pending（等待中）</option>
            <option value="ready">ready（已完成）</option>
            <option value="failed">failed（失敗）</option>
          </select>
        </div>
        <div>
          <label>角色 ID（可留空）</label>
          <input id="queueCoreFilter" type="number" min="1" placeholder="例如：1" />
        </div>
        <button onclick="loadQueueTasks()">重新載入佇列</button>
        <button onclick="processNextQueueTask()">處理下一筆</button>
        <button onclick="processAllQueueTasks()">處理全部 pending</button>
        <button class="secondary" onclick="toggleQueueAutoRefresh()">自動刷新：關</button>
        <button class="secondary" onclick="filterQueueBySelected()" id="btnQueueSelected" disabled>只看目前角色</button>
      </div>

      <div class="queue-table-wrap">
        <table class="queue-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>角色</th>
              <th>狀態</th>
              <th>優先級</th>
              <th>演化參數</th>
              <th>Hash</th>
              <th>建立時間</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody id="queueTaskBody">
            <tr><td colspan="8" class="queue-empty">載入中…</td></tr>
          </tbody>
        </table>
      </div>
      <div id="queuePreview" class="preview-grid"></div>
      <div id="queueStatus" class="status"></div>
    </section>
  </div>

  <script>
    let lastPrompt = "";
    let selectedCharacterId = "";
    let queueAutoRefreshTimer = null;

    // 角色視覺預設：當 manifest 尚未填入 _style.character_style.visual 時，自動補齊
    const DEFAULT_STYLE_PRESET = "3D建模風格, T型體";
    const DEFAULT_CREATED_BY = DEFAULT_STYLE_PRESET;
    const DEFAULT_STYLE_MEDIUM = "3D建模風格";
    const DEFAULT_STYLE_AESTHETIC = "T型體";

    const STATUS_LABELS = {
      pending: "等待中",
      ready: "已完成",
      failed: "失敗",
    };

    function reviewStatusLabel(task) {
      const imageGen = task && task.result_metadata && task.result_metadata.image_generation;
      const review = imageGen && typeof imageGen.review === "object" ? imageGen.review : {};
      const status = String(review.status || "").trim();
      if (!status) return "";
      if (status === "pending") return "待接受";
      if (status === "accepted") return "已接受";
      if (status === "rejected") return "已拒絕";
      return status;
    }

    function setJson(id, payload) {
      document.getElementById(id).textContent = JSON.stringify(payload, null, 2);
    }

    function setStatus(id, text, kind) {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = text || "";
      el.className = "status" + (kind === "ok" ? " ok" : kind === "err" ? " err" : "");
    }

    async function parseResponseJson(resp) {
      const text = await resp.text();
      if (!text) return {};
      try {
        return JSON.parse(text);
      } catch {
        const preview = text.replace(/\\s+/g, " ").trim().slice(0, 160);
        throw new Error(preview || `HTTP ${resp.status}`);
      }
    }

    function apiErrorDetail(data, fallback) {
      if (!data || data.detail === undefined || data.detail === null) return fallback;
      return typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    }

    function characterAssetUrl(characterId, assetPath) {
      const clean = String(assetPath || "").trim().replace(/^\\/+/, "");
      return clean ? `/api/v1/characters/${characterId}/assets/${clean}` : "";
    }

    function pickCharacterThumbnail(character) {
      const metadata = character && character.metadata && typeof character.metadata === "object"
        ? character.metadata
        : {};
      const faceDetail = typeof metadata.face_detail_asset_path === "string" ? metadata.face_detail_asset_path : "";
      const thumbnail = typeof metadata.thumbnail_asset_path === "string" ? metadata.thumbnail_asset_path : "";
      return faceDetail || thumbnail || "";
    }

    function imagePreviewCards(task) {
      const imageGen = task.result_metadata && task.result_metadata.image_generation;
      const images = imageGen && Array.isArray(imageGen.images) ? imageGen.images : [];
      return images
        .filter((image) => image && image.asset_path)
        .map((image) => {
          const src = characterAssetUrl(task.core_id, image.asset_path);
          const badge = image.angle === "face_detail" ? "面部細節" : (image.angle || "unclassified");
          return `
            <div class="preview-card">
              <img src="${src}" alt="${task.character_name || task.core_id}" loading="lazy" />
              <div class="caption">
                <strong>${task.character_name || `#${task.core_id}`}</strong><br/>
                ${(imageGen.purpose || "identity")} / ${badge}
              </div>
            </div>
          `;
        });
    }

    function updateCharacterSelection(id, name) {
      selectedCharacterId = id ? String(id) : "";
      document.getElementById("characterId").value = selectedCharacterId;
      document.getElementById("imgCharacterId").value = selectedCharacterId;

      const idLabel = selectedCharacterId
        ? `#${selectedCharacterId}${name ? " · " + name : ""}`
        : "";
      const idDisplay = document.getElementById("characterIdDisplay");
      const imgDisplay = document.getElementById("imgCharacterIdDisplay");
      if (selectedCharacterId) {
        idDisplay.textContent = idLabel;
        idDisplay.className = "id-badge";
        imgDisplay.textContent = idLabel;
        imgDisplay.className = "id-badge";
      } else {
        idDisplay.textContent = "尚未選擇角色";
        idDisplay.className = "id-badge empty";
        imgDisplay.textContent = "尚未選擇角色";
        imgDisplay.className = "id-badge empty";
      }

      const hasId = Boolean(selectedCharacterId);
      document.getElementById("btnLoadEditor").disabled = !hasId;
      document.getElementById("btnSaveEditor").disabled = !hasId;
      document.getElementById("btnVariant").disabled = !hasId;
      document.getElementById("btnGenerate").disabled = !hasId;
      document.getElementById("btnCopyPrompt").disabled = !lastPrompt;
      document.getElementById("btnQueueSelected").disabled = !hasId;

      document.querySelectorAll("#characterList .item").forEach((node) => {
        node.classList.toggle("active", node.dataset.id === selectedCharacterId);
      });
    }

    async function loadCharacters() {
      const name = document.getElementById("searchName").value.trim();
      const query = name ? `?name=${encodeURIComponent(name)}` : "";
      setStatus("listStatus", "載入中…");
      try {
        const resp = await fetch(`/api/v1/characters${query}`);
        const data = await parseResponseJson(resp);
        if (!resp.ok) {
          throw new Error(apiErrorDetail(data, "載入失敗"));
        }
        const list = document.getElementById("characterList");
        list.innerHTML = "";
        if (!data || data.length === 0) {
          list.innerHTML = '<div class="item" style="cursor:default;color:#9ca3af;">查無角色。請先在資料庫建立角色，或調整搜尋關鍵字。</div>';
          updateCharacterSelection("", "");
          setStatus("listStatus", "共 0 筆角色", "err");
          return;
        }
        (data || []).forEach((item) => {
          const div = document.createElement("div");
          div.className = "item";
          div.dataset.id = String(item.id);
          const thumb = pickCharacterThumbnail(item);
          const thumbHtml = thumb
            ? `<div class="item-thumb"><img src="${characterAssetUrl(item.id, thumb)}" alt="${item.name || item.id}" loading="lazy" /></div>`
            : `<div class="item-thumb">無圖</div>`;
          div.innerHTML = `${thumbHtml}<div class="item-main"><strong>#${item.id} ${item.name || "（未命名）"}</strong><span class="status">${(item.tags || []).join(", ") || "無標籤"}</span></div>`;
          div.onclick = () => {
            updateCharacterSelection(item.id, item.name || "");
            loadCharacterEditor();
          };
          list.appendChild(div);
        });
        setStatus("listStatus", `共 ${data.length} 筆；點選一筆以帶入系統 ID`, "ok");
        if (selectedCharacterId) {
          updateCharacterSelection(selectedCharacterId, "");
        }
      } catch (err) {
        setStatus("listStatus", `載入失敗：${err.message}`, "err");
      }
    }

    function parseJsonField(id) {
      const raw = document.getElementById(id).value.trim();
      if (!raw) return {};
      return JSON.parse(raw);
    }

    function pretty(value) {
      return JSON.stringify(value || {}, null, 2);
    }

    async function loadCharacterEditor() {
      const id = document.getElementById("characterId").value;
      if (!id) {
        setStatus("editorStatus", "請先從左側清單選擇角色", "err");
        return;
      }
      setStatus("editorStatus", "載入中…");
      try {
        const resp = await fetch(`/api/v1/characters/${id}/editor`);
        const data = await parseResponseJson(resp);
        if (!resp.ok) {
          throw new Error(apiErrorDetail(data, "載入失敗"));
        }
        const core = data.core || {};
        const profile = data.profile || {};
        document.getElementById("editName").value = core.name || "";
        document.getElementById("editCodename").value = core.codename || "";
        document.getElementById("editBaseAge").value = core.base_age ?? "";
        document.getElementById("editGenderSpectrum").value = core.gender_spectrum ?? "";
        document.getElementById("editTags").value = (core.tags || []).join(", ");
        document.getElementById("editIdentityAnchor").value = pretty(core.identity_anchor);
        document.getElementById("editMetadata").value = pretty(core.metadata);
        document.getElementById("editProjectName").value = profile.project_name || "";
        document.getElementById("editProjectId").value = profile.project_id || "";
        const stylePreset = profile.style_preset || DEFAULT_STYLE_PRESET;
        const createdBy = profile.created_by || DEFAULT_CREATED_BY;
        document.getElementById("editStylePreset").value = stylePreset;
        document.getElementById("editCreatedBy").value = createdBy;
        document.getElementById("editOutfitConfig").value = pretty(profile.outfit_config);
        let manifestObj = profile.manifest || {};
        if (manifestObj && typeof manifestObj === "object") {
          manifestObj._meta = manifestObj._meta || {};
          if (!manifestObj._meta.created_by) manifestObj._meta.created_by = createdBy;

          manifestObj._style = manifestObj._style || {};
          manifestObj._style.character_style = manifestObj._style.character_style || {};
          manifestObj._style.character_style.visual = manifestObj._style.character_style.visual || {};

          const visual = manifestObj._style.character_style.visual;
          if (!visual.medium) visual.medium = DEFAULT_STYLE_MEDIUM;
          if (!visual.aesthetic) visual.aesthetic = DEFAULT_STYLE_AESTHETIC;
        }
        document.getElementById("editManifest").value = pretty(manifestObj);
        document.getElementById("editNotes").value = profile.notes || "";
        updateCharacterSelection(id, core.name || "");
        setStatus("editorStatus", "角色資料已載入，可編輯後按「儲存角色」", "ok");
      } catch (err) {
        setStatus("editorStatus", `載入失敗：${err.message}`, "err");
      }
    }

    async function saveCharacterEditor() {
      const id = document.getElementById("characterId").value;
      if (!id) {
        setStatus("editorStatus", "請先從左側清單選擇角色", "err");
        return;
      }
      try {
        const payload = {
          name: document.getElementById("editName").value.trim(),
          codename: document.getElementById("editCodename").value.trim() || null,
          base_age: Number(document.getElementById("editBaseAge").value || 0),
          gender_spectrum: document.getElementById("editGenderSpectrum").value === "" ? null : Number(document.getElementById("editGenderSpectrum").value),
          tags: document.getElementById("editTags").value.split(",").map((x) => x.trim()).filter(Boolean),
          identity_anchor: parseJsonField("editIdentityAnchor"),
          metadata: parseJsonField("editMetadata"),
          project_name: document.getElementById("editProjectName").value.trim() || null,
          project_id: document.getElementById("editProjectId").value.trim() || null,
          style_preset: document.getElementById("editStylePreset").value.trim() || null,
          created_by: document.getElementById("editCreatedBy").value.trim() || null,
          outfit_config: parseJsonField("editOutfitConfig"),
          manifest: parseJsonField("editManifest"),
          notes: document.getElementById("editNotes").value.trim() || null
        };
        setStatus("editorStatus", "儲存中…");
        const resp = await fetch(`/api/v1/characters/${id}/editor`, {
          method: "PUT",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload),
        });
        const data = await parseResponseJson(resp);
        if (!resp.ok) {
          throw new Error(apiErrorDetail(data, "儲存失敗"));
        }
        setStatus("editorStatus", "角色儲存成功", "ok");
        setJson("variantOutput", data);
        await loadCharacters();
      } catch (err) {
        setStatus("editorStatus", `儲存失敗：${err.message}`, "err");
      }
    }

    async function requestVariant() {
      const id = document.getElementById("imgCharacterId").value;
      if (!id) {
        setStatus("imgStatus", "請先從左側清單選擇角色", "err");
        return;
      }
      setStatus("imgStatus", "請求變體中…");
      try {
        const variant = await enqueueVariantTask(id);
        const resp = variant.resp;
        const data = variant.data;
        setJson("variantOutput", data);
        if (resp.status === 202) {
          setStatus("imgStatus", "變體已排入佇列（202），背景處理中", "ok");
          await loadQueueTasks();
        } else if (resp.ok) {
          setStatus("imgStatus", "變體已就緒，可直接生圖", "ok");
        } else {
          throw new Error(data.detail ? JSON.stringify(data.detail) : `HTTP ${resp.status}`);
        }
      } catch (err) {
        setStatus("imgStatus", `請求變體失敗：${err.message}`, "err");
      }
    }

    function buildVariantParams() {
      const params = new URLSearchParams();
      const age = document.getElementById("age").value;
      const emotion = document.getElementById("emotion").value.trim();
      const scene = document.getElementById("scene").value.trim();
      const injury = document.getElementById("injury").value;
      if (age) params.set("age", age);
      if (emotion) params.set("emotion", emotion);
      if (scene) params.set("scene", scene);
      if (injury) params.set("injury", injury);
      return params;
    }

    async function enqueueVariantTask(characterId, queueNonce) {
      const params = buildVariantParams();
      const nonce = queueNonce ? String(queueNonce) : "";
      if (nonce) params.set("queue_nonce", nonce);
      const resp = await fetch(`/api/v1/characters/${characterId}/variant?${params.toString()}`);
      const data = await parseResponseJson(resp);
      return { resp, data };
    }

    async function loadImagingConfig() {
      setStatus("cfgStatus", "讀取設定中…");
      try {
        const resp = await fetch("/api/v1/admin/imaging-config");
        const data = await parseResponseJson(resp);
        if (!resp.ok) {
          throw new Error(apiErrorDetail(data, "讀取失敗"));
        }
        document.getElementById("provider").value = data.provider || "wan";
        document.getElementById("baseUrl").value = data.base_url || "";
        document.getElementById("model").value = data.model || "";
        setStatus(
          "cfgStatus",
          `已載入。API Key：${data.has_api_key ? "已設定" : "尚未設定（生圖前請填寫）"}`,
          data.has_api_key ? "ok" : "err"
        );
      } catch (err) {
        setStatus("cfgStatus", `讀取失敗：${err.message}`, "err");
      }
    }

    async function saveImagingConfig() {
      const payload = {
        provider: document.getElementById("provider").value,
        base_url: document.getElementById("baseUrl").value.trim(),
        model: document.getElementById("model").value.trim(),
        persist_env: document.getElementById("persistEnv").checked
      };
      const apiKey = document.getElementById("apiKey").value.trim();
      if (apiKey) payload.api_key = apiKey;
      setStatus("cfgStatus", "儲存中…");
      try {
        const resp = await fetch("/api/v1/admin/imaging-config", {
          method: "PUT",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload),
        });
        const data = await parseResponseJson(resp);
        if (!resp.ok) {
          throw new Error(apiErrorDetail(data, "儲存失敗"));
        }
        setStatus(
          "cfgStatus",
          `設定已更新。API Key：${data.has_api_key ? "已設定" : "尚未設定"}`,
          "ok"
        );
      } catch (err) {
        setStatus("cfgStatus", `儲存失敗：${err.message}`, "err");
      }
    }

    async function generateImages() {
      const id = document.getElementById("imgCharacterId").value;
      if (!id) {
        setStatus("imgStatus", "請先從左側清單選擇角色", "err");
        return;
      }
      setStatus("imgStatus", "正在建立生圖佇列任務…");
      try {
        const payload = {
          purpose: document.getElementById("purpose").value,
          provider: document.getElementById("provider").value,
          base_url: document.getElementById("baseUrl").value.trim(),
          model: document.getElementById("model").value.trim(),
          extra: document.getElementById("extra").value.trim(),
          age: document.getElementById("age").value ? Number(document.getElementById("age").value) : null,
          emotion: document.getElementById("emotion").value.trim() || null,
          scene: document.getElementById("scene").value.trim() || null,
          injury: document.getElementById("injury").value ? Number(document.getElementById("injury").value) : null,
          multi_angle: true,
          persist: true
        };
        const apiKey = document.getElementById("apiKey").value.trim();
        if (apiKey) payload.api_key = apiKey;
        const resp = await fetch(`/api/v1/characters/${id}/image-queue`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CharacterOS-Panel": "enabled"
          },
          body: JSON.stringify(payload),
        });
        const data = await parseResponseJson(resp);
        if (!resp.ok) {
          throw new Error(apiErrorDetail(data, `HTTP ${resp.status}`));
        }
        setJson("imageOutput", data);
        lastPrompt = "";
        document.getElementById("btnCopyPrompt").disabled = true;
        setStatus(
          "imgStatus",
          `生圖任務已排入佇列 #${data.task && data.task.id ? data.task.id : "?"}，請在下方任務面板執行`,
          "ok"
        );
        await loadQueueTasks();
      } catch (err) {
        setStatus("imgStatus", `生圖失敗：${err.message}`, "err");
      }
    }

    function formatDateTime(value) {
      if (!value) return "—";
      try {
        const dt = new Date(value);
        if (Number.isNaN(dt.getTime())) return String(value);
        return dt.toLocaleString("zh-TW", { hour12: false });
      } catch {
        return String(value);
      }
    }

    function renderQueueStats(data) {
      const stats = data.stats || {};
      const mode = data.storage_mode === "database" ? "PostgreSQL" : "本機 JSON";
      const box = document.getElementById("queueStats");
      box.innerHTML = `
        <span class="stat-chip mode">儲存模式：${mode}</span>
        <span class="stat-chip pending">等待中 ${stats.total_pending ?? 0}</span>
        <span class="stat-chip ready">已完成 ${stats.total_ready ?? 0}</span>
        <span class="stat-chip failed">失敗 ${stats.total_failed ?? 0}</span>
        <span class="stat-chip">平均等待 ${Math.round(stats.average_wait_time_ms || 0)} ms</span>
        <span class="stat-chip">最久 pending ${Math.round(stats.oldest_pending_age_seconds || 0)} 秒</span>
      `;
    }

    function renderQueueTasks(data) {
      renderQueueStats(data);
      const body = document.getElementById("queueTaskBody");
      const preview = document.getElementById("queuePreview");
      const tasks = data.tasks || [];
      const latestReadyWithPrompt = tasks.find((task) => {
        const imageGen = task.result_metadata && task.result_metadata.image_generation;
        return imageGen && imageGen.prompt;
      });
      if (latestReadyWithPrompt) {
        lastPrompt = latestReadyWithPrompt.result_metadata.image_generation.prompt || lastPrompt;
        document.getElementById("btnCopyPrompt").disabled = !lastPrompt;
      }
      if (!tasks.length) {
        body.innerHTML = '<tr><td colspan="8" class="queue-empty">目前沒有符合條件的佇列任務。可按「請求變體」新增一筆。</td></tr>';
        preview.innerHTML = "";
        return;
      }
      body.innerHTML = tasks.map((task) => {
        const status = task.status || "pending";
        const statusLabel = STATUS_LABELS[status] || status;
        const reviewLabel = reviewStatusLabel(task);
        const reviewStatus = task.result_metadata && task.result_metadata.image_generation && task.result_metadata.image_generation.review
          ? String(task.result_metadata.image_generation.review.status || "")
          : "";
        const params = JSON.stringify(task.evolution_params || {});
        const name = task.character_name ? `#${task.core_id} · ${task.character_name}` : `#${task.core_id}`;
        const actionHtml = status === "pending"
          ? `<div class="queue-actions"><button class="secondary" onclick="processQueueTask(${task.id})">執行</button></div>`
          : status === "ready" && task.result_url
            ? `<div class="queue-actions">
                <a href="${task.result_url}" target="_blank" rel="noopener noreferrer">查看結果</a>
                ${reviewStatus === "pending" ? `<button onclick="acceptQueueTask(${task.id})">接受入庫</button><button class="secondary" onclick="rejectQueueTask(${task.id})">拒絕</button>` : ``}
              </div>`
            : task.error_message
              ? `<div class="queue-actions"><span title="${task.error_message.replace(/"/g, "&quot;")}">失敗</span></div>`
              : `<div class="queue-actions"><span>—</span></div>`;
        return `
          <tr>
            <td>${task.id}</td>
            <td>${name}</td>
            <td><span class="badge ${status}">${statusLabel}</span>${reviewLabel ? `<div class="status">${reviewLabel}</div>` : ""}</td>
            <td>${task.priority ?? 0}</td>
            <td class="mono">${params}</td>
            <td class="mono">${(task.variant_hash || "").slice(0, 16)}…</td>
            <td>${formatDateTime(task.created_at)}</td>
            <td>${actionHtml}</td>
          </tr>
        `;
      }).join("");
      const previewCards = [];
      tasks.forEach((task) => {
        imagePreviewCards(task).forEach((card) => {
          previewCards.push(card);
        });
      });
      preview.innerHTML = previewCards.join("");
    }

    async function processQueueTask(taskId) {
      setStatus("queueStatus", `正在處理任務 #${taskId}…`);
      try {
        const resp = await fetch(`/api/v1/admin/queue-tasks/${taskId}/process`, {
          method: "POST",
        });
        const data = await parseResponseJson(resp);
        if (!resp.ok) {
          throw new Error(apiErrorDetail(data, "處理任務失敗"));
        }
        const task = data.task || {};
        const status = task.status || "unknown";
        const imageGen = task.result_metadata && task.result_metadata.image_generation;
        if (imageGen && imageGen.prompt) {
          lastPrompt = imageGen.prompt;
          document.getElementById("btnCopyPrompt").disabled = false;
          setJson("imageOutput", imageGen);
        }
        setStatus("queueStatus", `任務 #${taskId} 已處理，狀態：${status}`, status === "failed" ? "err" : "ok");
        await loadQueueTasks();
      } catch (err) {
        setStatus("queueStatus", `處理失敗：${err.message}`, "err");
      }
    }

    async function processNextQueueTask() {
      setStatus("queueStatus", "正在處理下一筆 pending 任務…");
      try {
        const resp = await fetch("/api/v1/admin/queue-tasks/process-next", {
          method: "POST",
        });
        const data = await parseResponseJson(resp);
        if (!resp.ok) {
          throw new Error(apiErrorDetail(data, "處理下一筆任務失敗"));
        }
        if (!data.task) {
          setStatus("queueStatus", "目前沒有 pending 任務可處理", "ok");
        } else {
          const imageGen = data.task.result_metadata && data.task.result_metadata.image_generation;
          if (imageGen && imageGen.prompt) {
            lastPrompt = imageGen.prompt;
            document.getElementById("btnCopyPrompt").disabled = false;
            setJson("imageOutput", imageGen);
          }
          setStatus("queueStatus", `已處理任務 #${data.task.id}，狀態：${data.task.status}`, data.task.status === "failed" ? "err" : "ok");
        }
        await loadQueueTasks();
      } catch (err) {
        setStatus("queueStatus", `處理失敗：${err.message}`, "err");
      }
    }

    async function acceptQueueTask(taskId) {
      setStatus("queueStatus", `正在接受任務 #${taskId}…`);
      try {
        const resp = await fetch(`/api/v1/admin/queue-tasks/${taskId}/accept`, { method: "POST" });
        const data = await parseResponseJson(resp);
        if (!resp.ok) throw new Error(apiErrorDetail(data, "接受任務失敗"));
        setStatus("queueStatus", `任務 #${taskId} 已接受並寫回角色資料`, "ok");
        await loadQueueTasks();
        if (selectedCharacterId && String(data.task && data.task.core_id || "") === String(selectedCharacterId)) {
          await loadCharacterEditor();
        }
      } catch (err) {
        setStatus("queueStatus", `接受失敗：${err.message}`, "err");
      }
    }

    async function rejectQueueTask(taskId) {
      setStatus("queueStatus", `正在拒絕任務 #${taskId}…`);
      try {
        const resp = await fetch(`/api/v1/admin/queue-tasks/${taskId}/reject`, { method: "POST" });
        const data = await parseResponseJson(resp);
        if (!resp.ok) throw new Error(apiErrorDetail(data, "拒絕任務失敗"));
        setStatus("queueStatus", `任務 #${taskId} 已拒絕，不會寫回角色資料`, "ok");
        await loadQueueTasks();
      } catch (err) {
        setStatus("queueStatus", `拒絕失敗：${err.message}`, "err");
      }
    }

    async function processAllQueueTasks() {
      setStatus("queueStatus", "正在批次處理 pending 任務…");
      try {
        const resp = await fetch("/api/v1/admin/queue-tasks/process-all?limit=100", {
          method: "POST",
        });
        const data = await parseResponseJson(resp);
        if (!resp.ok) {
          throw new Error(apiErrorDetail(data, "批次處理任務失敗"));
        }
        const latestTaskWithPrompt = (Array.isArray(data.tasks) ? data.tasks : []).find((task) => {
          const imageGen = task.result_metadata && task.result_metadata.image_generation;
          return imageGen && imageGen.prompt;
        });
        if (latestTaskWithPrompt) {
          lastPrompt = latestTaskWithPrompt.result_metadata.image_generation.prompt || lastPrompt;
          document.getElementById("btnCopyPrompt").disabled = false;
          setJson("imageOutput", latestTaskWithPrompt.result_metadata.image_generation);
        }
        setStatus("queueStatus", `本次已處理 ${data.processed ?? 0} 筆任務`, "ok");
        await loadQueueTasks();
      } catch (err) {
        setStatus("queueStatus", `批次處理失敗：${err.message}`, "err");
      }
    }

    async function loadQueueTasks() {
      setStatus("queueStatus", "載入佇列中…");
      try {
        const params = new URLSearchParams();
        const status = document.getElementById("queueStatusFilter").value;
        const coreId = document.getElementById("queueCoreFilter").value.trim();
        if (status) params.set("status", status);
        if (coreId) params.set("core_id", coreId);
        params.set("limit", "100");
        const resp = await fetch(`/api/v1/admin/queue-tasks?${params.toString()}`);
        const data = await parseResponseJson(resp);
        if (!resp.ok) {
          throw new Error(apiErrorDetail(data, "載入佇列失敗"));
        }
        renderQueueTasks(data);
        setStatus("queueStatus", `共 ${data.total ?? 0} 筆任務`, "ok");
      } catch (err) {
        document.getElementById("queueTaskBody").innerHTML =
          `<tr><td colspan="8" class="queue-empty">${err.message}</td></tr>`;
        setStatus("queueStatus", `載入失敗：${err.message}`, "err");
      }
    }

    function filterQueueBySelected() {
      if (!selectedCharacterId) {
        setStatus("queueStatus", "請先選擇角色", "err");
        return;
      }
      document.getElementById("queueCoreFilter").value = selectedCharacterId;
      loadQueueTasks();
    }

    function toggleQueueAutoRefresh() {
      const btn = document.querySelector('button[onclick="toggleQueueAutoRefresh()"]');
      if (queueAutoRefreshTimer) {
        clearInterval(queueAutoRefreshTimer);
        queueAutoRefreshTimer = null;
        if (btn) btn.textContent = "自動刷新：關";
        setStatus("queueStatus", "已停止自動刷新", "ok");
        return;
      }
      queueAutoRefreshTimer = setInterval(loadQueueTasks, 5000);
      if (btn) btn.textContent = "自動刷新：開（5s）";
      setStatus("queueStatus", "已啟動每 5 秒自動刷新", "ok");
      loadQueueTasks();
    }

    async function copyPrompt() {
      if (!lastPrompt) {
        setStatus("imgStatus", "尚無可複製的提示詞，請先生成圖片", "err");
        return;
      }
      await navigator.clipboard.writeText(lastPrompt);
      setStatus("imgStatus", "提示詞已複製到剪貼簿", "ok");
    }

    updateCharacterSelection("", "");
    loadCharacters();
    loadImagingConfig();
    loadQueueTasks();
  </script>
</body>
</html>
"""
