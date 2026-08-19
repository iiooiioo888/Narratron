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
    .hint { color: #6b7280; margin-bottom: 20px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .card { border: 1px solid #d1d5db; border-radius: 10px; padding: 14px; }
    .card h2 { margin-top: 0; font-size: 18px; }
    label { display: block; font-size: 13px; margin: 8px 0 4px; }
    input, select, textarea, button { width: 100%; box-sizing: border-box; padding: 8px; margin-bottom: 8px; }
    button { cursor: pointer; border: 0; border-radius: 8px; background: #2563eb; color: #fff; }
    button.secondary { background: #374151; }
    pre { background: #111827; color: #e5e7eb; padding: 10px; border-radius: 8px; max-height: 320px; overflow: auto; }
    .list { max-height: 320px; overflow: auto; border: 1px solid #e5e7eb; border-radius: 8px; padding: 8px; }
    .item { padding: 8px; border-bottom: 1px solid #f3f4f6; }
    .item:last-child { border-bottom: 0; }
    .inline { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .status { font-size: 13px; color: #4b5563; }
    textarea.json { min-height: 110px; font-family: Consolas, monospace; }
  </style>
</head>
<body>
  <h1>CharacterOS 完整角色編輯器</h1>
  <div class="hint">集中管理角色 Core/Profile/Manifest、風格、生圖設定與生成流程。</div>

  <div class="grid">
    <section class="card">
      <h2>角色清單</h2>
      <label>名稱搜尋</label>
      <input id="searchName" placeholder="例如：卡爾" />
      <button onclick="loadCharacters()">重新載入</button>
      <div id="characterList" class="list"></div>
    </section>

    <section class="card">
      <h2>完整角色編輯（Core + Profile）</h2>
      <label>角色 ID</label>
      <input id="characterId" type="number" min="1" placeholder="例如：1" />
      <div class="inline">
        <button onclick="loadCharacterEditor()">載入編輯資料</button>
        <button class="secondary" onclick="saveCharacterEditor()">儲存角色</button>
      </div>

      <label>名稱 / 代號</label>
      <div class="inline">
        <input id="editName" placeholder="name" />
        <input id="editCodename" placeholder="codename" />
      </div>

      <label>基準年齡 / 性別光譜</label>
      <div class="inline">
        <input id="editBaseAge" type="number" min="0" max="150" placeholder="base_age" />
        <input id="editGenderSpectrum" type="number" min="0" max="1" step="0.1" placeholder="gender_spectrum 0-1" />
      </div>

      <label>tags（逗號分隔）</label>
      <input id="editTags" placeholder="protagonist, modern" />

      <label>identity_anchor JSON</label>
      <textarea id="editIdentityAnchor" class="json"></textarea>

      <label>metadata JSON</label>
      <textarea id="editMetadata" class="json"></textarea>

      <label>style_preset / created_by</label>
      <div class="inline">
        <input id="editStylePreset" placeholder="style_preset" />
        <input id="editCreatedBy" placeholder="created_by" />
      </div>

      <label>project_name / project_id</label>
      <div class="inline">
        <input id="editProjectName" placeholder="project_name" />
        <input id="editProjectId" placeholder="project_id" />
      </div>

      <label>outfit_config JSON</label>
      <textarea id="editOutfitConfig" class="json"></textarea>

      <label>manifest JSON（含 _style / 角色風格）</label>
      <textarea id="editManifest" class="json" style="min-height: 180px;"></textarea>

      <label>notes</label>
      <textarea id="editNotes" rows="3"></textarea>
      <div id="editorStatus" class="status"></div>
    </section>

    <section class="card">
      <h2>生圖設定（WAN / OpenAI 相容）</h2>
      <button onclick="loadImagingConfig()">讀取目前設定</button>
      <label>Provider</label>
      <select id="provider">
        <option value="wan">wan</option>
        <option value="openai">openai</option>
        <option value="http">http</option>
        <option value="null">null</option>
      </select>
      <label>Base URL</label>
      <input id="baseUrl" value="https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1" />
      <label>Model</label>
      <input id="model" value="wan2.7-image-pro" />
      <label>API Key（留空代表不修改）</label>
      <input id="apiKey" type="password" placeholder="sk-..." />
      <label><input id="persistEnv" type="checkbox" checked /> 同步寫入 .env</label>
      <button onclick="saveImagingConfig()">儲存設定</button>
      <div id="cfgStatus" class="status"></div>
    </section>

    <section class="card">
      <h2>變體 / 生圖</h2>
      <label>角色 ID</label>
      <input id="imgCharacterId" type="number" min="1" placeholder="例如：1" />
      <label>變體參數（可留空）</label>
      <div class="inline">
        <input id="age" type="number" min="0" max="150" placeholder="age" />
        <input id="emotion" placeholder="emotion" />
      </div>
      <div class="inline">
        <input id="scene" placeholder="scene" />
        <input id="injury" type="number" min="0" max="1" step="0.1" placeholder="injury 0-1" />
      </div>
      <button class="secondary" onclick="requestVariant()">請求變體</button>
      <label>Purpose</label>
      <select id="purpose">
        <option value="identity">identity</option>
        <option value="outfit">outfit</option>
        <option value="expression">expression</option>
        <option value="thumb">thumb</option>
      </select>
      <label>額外風格描述（會拼進 prompt）</label>
      <textarea id="extra" rows="3" placeholder="例如：賽博龐克、電影級打光、油畫筆觸"></textarea>
      <div class="inline">
        <button onclick="generateImages()">生成圖片</button>
        <button class="secondary" onclick="copyPrompt()">複製最後提示詞</button>
      </div>
      <pre id="variantOutput">{}</pre>
      <pre id="imageOutput">{}</pre>
    </section>
  </div>

  <script>
    let lastPrompt = "";

    function setJson(id, payload) {
      document.getElementById(id).textContent = JSON.stringify(payload, null, 2);
    }

    async function loadCharacters() {
      const name = document.getElementById("searchName").value.trim();
      const query = name ? `?name=${encodeURIComponent(name)}` : "";
      const resp = await fetch(`/api/v1/characters${query}`);
      const data = await resp.json();
      const list = document.getElementById("characterList");
      list.innerHTML = "";
      (data || []).forEach((item) => {
        const div = document.createElement("div");
        div.className = "item";
        div.innerHTML = `<b>#${item.id}</b> ${item.name}<br/><span class="status">${(item.tags || []).join(", ")}</span>`;
        div.onclick = () => {
          document.getElementById("characterId").value = item.id;
          document.getElementById("imgCharacterId").value = item.id;
          loadCharacterEditor();
        };
        list.appendChild(div);
      });
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
      if (!id) return;
      const resp = await fetch(`/api/v1/characters/${id}/editor`);
      const data = await resp.json();
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
      document.getElementById("editStylePreset").value = profile.style_preset || "";
      document.getElementById("editCreatedBy").value = profile.created_by || "";
      document.getElementById("editOutfitConfig").value = pretty(profile.outfit_config);
      document.getElementById("editManifest").value = pretty(profile.manifest);
      document.getElementById("editNotes").value = profile.notes || "";
      document.getElementById("editorStatus").textContent = "角色資料已載入";
    }

    async function saveCharacterEditor() {
      const id = document.getElementById("characterId").value;
      if (!id) return;
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
        const resp = await fetch(`/api/v1/characters/${id}/editor`, {
          method: "PUT",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!resp.ok) {
          throw new Error(data.detail ? JSON.stringify(data.detail) : "儲存失敗");
        }
        document.getElementById("editorStatus").textContent = "角色儲存成功";
        setJson("variantOutput", data);
      } catch (err) {
        document.getElementById("editorStatus").textContent = `儲存失敗：${err.message}`;
      }
    }

    async function requestVariant() {
      const id = document.getElementById("imgCharacterId").value;
      if (!id) return;
      const params = new URLSearchParams();
      const age = document.getElementById("age").value;
      const emotion = document.getElementById("emotion").value.trim();
      const scene = document.getElementById("scene").value.trim();
      const injury = document.getElementById("injury").value;
      if (age) params.set("age", age);
      if (emotion) params.set("emotion", emotion);
      if (scene) params.set("scene", scene);
      if (injury) params.set("injury", injury);
      const resp = await fetch(`/api/v1/characters/${id}/variant?${params.toString()}`);
      const data = await resp.json().catch(() => ({}));
      setJson("variantOutput", data);
    }

    async function loadImagingConfig() {
      const resp = await fetch("/api/v1/admin/imaging-config");
      const data = await resp.json();
      document.getElementById("provider").value = data.provider || "wan";
      document.getElementById("baseUrl").value = data.base_url || "";
      document.getElementById("model").value = data.model || "";
      document.getElementById("cfgStatus").textContent = `已載入，API key 存在：${data.has_api_key ? "是" : "否"}`;
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
      const resp = await fetch("/api/v1/admin/imaging-config", {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      document.getElementById("cfgStatus").textContent = `更新完成，API key 存在：${data.has_api_key ? "是" : "否"}`;
    }

    async function generateImages() {
      const id = document.getElementById("imgCharacterId").value;
      if (!id) return;
      const payload = {
        purpose: document.getElementById("purpose").value,
        provider: document.getElementById("provider").value,
        base_url: document.getElementById("baseUrl").value.trim(),
        model: document.getElementById("model").value.trim(),
        extra: document.getElementById("extra").value.trim(),
        persist: true
      };
      const apiKey = document.getElementById("apiKey").value.trim();
      if (apiKey) payload.api_key = apiKey;
      const resp = await fetch(`/api/v1/characters/${id}/images`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CharacterOS-Panel": "enabled"
        },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      lastPrompt = data.prompt || "";
      setJson("imageOutput", data);
    }

    async function copyPrompt() {
      if (!lastPrompt) return;
      await navigator.clipboard.writeText(lastPrompt);
      alert("提示詞已複製");
    }

    loadCharacters();
    loadImagingConfig();
  </script>
</body>
</html>
"""
