import { useEffect, useMemo, useState } from 'react'
import ReactFlow, { Background, Controls, MiniMap } from 'reactflow'
import 'reactflow/dist/style.css'

import { CharpassPanel } from './CharpassPanel'
import { buildFlowGraph } from './graph'
import {
  appendRun,
  createProject,
  getSelectedRun,
  loadWorkspace,
  renameProject,
  saveWorkspace,
  selectRun,
} from './storage'
import type { NarratronState, PageId, ProjectRecord, RunMode, ShotRecord, TraceRecord } from './types'

const PAGE_ORDER: PageId[] = ['Pad', 'Timeline', 'Dashboard', 'Map', 'Player']
const PAGE_ZH: Record<PageId, string> = {
  Pad: '寫板',
  Timeline: '時軌',
  Dashboard: '總覽',
  Map: '因果圖',
  Player: '播放器',
}
const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const SCRIPT_LIMIT = 20000
const SAMPLE_BRIEF = '一名年齡為8歲的小女孩，可愛風格，公主風'
const SAMPLE_SCRIPT = `INT. 廢棄工廠 — 夜

角色
- 卡爾（傷疤覆蓋左臉，手持鏽蝕鐵棍）
- 艾拉（繃帶纏繞右臂，背著醫療包）

道具
- 鏽蝕鐵棍
- 醫療包

場景
- 廢棄工廠：昏暗的吊燈搖晃，地面散落碎玻璃

卡爾：（壓低聲音）守衛換班了，我們有十分鐘。
艾拉：（檢查無線電）信號很弱，但夠用。`

const HARDWARE_POOLS = [
  { level: 'L0', code: 'Big Core', zh: '大核' },
  { level: 'L1', code: 'Mid Core', zh: '中核' },
  { level: 'L2', code: 'Alt Core', zh: '備核' },
  { level: 'L3', code: 'Light Core', zh: '輕核' },
] as const

const PLUGIN_MATRIX = [
  ['P1', 'Tracer', '追跡', '生成前'],
  ['P2', 'Fixer', '固形', '生成前'],
  ['P3', 'Forker', '分岔', '生成前'],
  ['P4', 'Painter', '調色', '生成前'],
  ['P5', 'Mover', '擬動', '生成前/後'],
  ['P6', 'Screener', '篩檢', '生成後'],
  ['P7', 'Router', '路由', '生成前'],
  ['P8', 'Recycler', '重生', '生成前'],
  ['P9', 'Player', '配樂', '生成後'],
  ['P10', 'Filter', '濾聲', '生成後'],
  ['P11', 'Cropper', '裁切', '生成後'],
  ['P12', 'Exporter', '轉檔', '生成後'],
  ['P13', 'Maker', '製本', '生成後'],
] as const

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function deriveCharacterImageMetadata(charpass: Record<string, unknown>): Record<string, string> {
  const meta = asRecord(charpass._meta)
  const identity = asRecord(charpass._identity)
  const refs = Array.isArray(identity.ref_images) ? identity.ref_images : []
  const items = refs
    .map((item) => asRecord(item))
    .filter((item) => typeof item.path === 'string' && String(item.path).trim())

  const faceDetail = items.find((item) => String(item.angle ?? '').trim() === 'face_detail')
  const thumbnail =
    String(meta.thumbnail ?? '').trim() ||
    String(faceDetail?.path ?? '').trim() ||
    String(items[0]?.path ?? '').trim()

  const result: Record<string, string> = {}
  if (thumbnail) {
    result.thumbnail_asset_path = thumbnail
  }
  if (faceDetail) {
    result.face_detail_asset_path = String(faceDetail.path).trim()
  }
  return result
}

function fmtDate(value?: string): string {
  if (!value) {
    return '-'
  }
  return new Date(value).toLocaleString('zh-TW', { hour12: false })
}

function jsonSummary(value: unknown): string {
  if (value == null) {
    return '無資料'
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function padMs(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000))
  const minutes = String(Math.floor(total / 60)).padStart(2, '0')
  const seconds = String(total % 60).padStart(2, '0')
  return `${minutes}:${seconds}`
}

function shotDuration(shot?: ShotRecord): number {
  return Math.max(400, Number(shot?.duration_ms) || 2000)
}

function beatOf(shot?: ShotRecord): string {
  return String(asRecord(shot?.payload).beat || '—')
}

async function callApi(
  mode: RunMode,
  body: { script: string; persist: boolean; bootstrap_overrides?: Record<string, unknown> },
): Promise<NarratronState> {
  const endpoint = mode === 'parse' ? '/parse' : '/direct'
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `HTTP ${response.status}`)
  }

  return (await response.json()) as NarratronState
}

function getProjectStatus(project?: ProjectRecord): string {
  if (!project) {
    return 'missing'
  }
  const run = getSelectedRun(project)
  if (!run) {
    return 'queued'
  }
  if ((run.state.shots ?? []).length > 0) {
    return 'ok'
  }
  return 'stale'
}

function isPageId(value: string): value is PageId {
  return PAGE_ORDER.includes(value as PageId)
}

export default function App() {
  const initialWorkspace = useMemo(() => loadWorkspace(), [])
  const [projects, setProjects] = useState<ProjectRecord[]>(initialWorkspace.projects)
  const [activeProjectId, setActiveProjectId] = useState<string | undefined>(
    initialWorkspace.activeProjectId ?? initialWorkspace.projects[0]?.id,
  )
  const [page, setPage] = useState<PageId>('Pad')
  const [script, setScript] = useState('')
  const [persist, setPersist] = useState(true)
  const [projectName, setProjectName] = useState('')
  const [selectedShotId, setSelectedShotId] = useState<string | undefined>()
  const [selectedTraceId, setSelectedTraceId] = useState<string | undefined>()
  const [loadingMode, setLoadingMode] = useState<RunMode | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedCharId, setSelectedCharId] = useState<string | undefined>()
  const [playing, setPlaying] = useState(false)
  const [playIndex, setPlayIndex] = useState(0)
  const [bootName, setBootName] = useState('')
  const [bootMbti, setBootMbti] = useState('')
  const [bootFlaw, setBootFlaw] = useState('')
  const [bootPersonality, setBootPersonality] = useState('')
  const [bootHabits, setBootHabits] = useState('')

  const activeProject = projects.find((project) => project.id === activeProjectId)
  const selectedRun = getSelectedRun(activeProject)
  const currentState = selectedRun?.state
  const shots = [...(currentState?.shots ?? [])].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
  const traces = currentState?.traces ?? []
  const entities = currentState?.entities ?? []
  const selectedShot = shots.find((shot) => shot.id === selectedShotId) ?? shots[0]
  const selectedTrace = traces.find((trace) => trace.id === selectedTraceId) ?? traces[0]
  const graph = useMemo(() => buildFlowGraph(currentState ?? {}), [currentState])
  const characters = entities.filter((entity) => entity.kind === 'character')
  const selectedCharacter = characters.find((entity) => entity.id === selectedCharId) ?? characters[0]
  const scriptLen = script.length
  const scriptOk = Boolean(script.trim()) && scriptLen <= SCRIPT_LIMIT
  const timelineReady = shots.length > 0
  const mapReady = traces.length > 0 || shots.length > 0
  const playerReady = shots.length > 0 || Boolean(currentState?.mux_uri)
  const bootstrap = asRecord(currentState?.bootstrap)
  const bootActive = bootstrap.active === true
  const bootCharacter = asRecord(bootstrap.character)
  const bootWorld = asRecord(bootstrap.world)
  const bootCurve = asRecord(bootstrap.age_curve)
  const totalMs = shots.reduce((sum, shot) => sum + shotDuration(shot), 0)
  const elapsedMs = shots.slice(0, playIndex).reduce((sum, shot) => sum + shotDuration(shot), 0)

  useEffect(() => {
    const applyHash = () => {
      const hash = location.hash.replace(/^#/, '')
      if (isPageId(hash)) {
        setPage(hash)
      }
    }
    applyHash()
    window.addEventListener('hashchange', applyHash)
    return () => window.removeEventListener('hashchange', applyHash)
  }, [])

  useEffect(() => {
    if (location.hash.replace(/^#/, '') !== page) {
      history.replaceState(null, '', `#${page}`)
    }
  }, [page])

  const runKey = selectedRun?.id ?? ''
  useEffect(() => {
    const ordered = [...(currentState?.shots ?? [])].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    if (!playing || ordered.length === 0 || currentState?.mux_uri) {
      return
    }
    const duration = shotDuration(ordered[playIndex])
    const length = ordered.length
    const timer = window.setTimeout(() => {
      setPlayIndex((index) => (index + 1) % length)
    }, duration)
    return () => window.clearTimeout(timer)
  }, [playing, playIndex, currentState, runKey])

  useEffect(() => {
    if (!bootActive) {
      return
    }
    setBootName(String(bootCharacter.name || ''))
    setBootMbti(String(bootCharacter.mbti || ''))
    setBootFlaw(String(bootCharacter.inner_flaw || ''))
    setBootPersonality(String(bootCharacter.personality || ''))
    const habits = bootCharacter.habits
    setBootHabits(Array.isArray(habits) ? habits.map((item) => String(item)).join('\n') : '')
  }, [runKey, bootActive])

  function updateWorkspace(nextProjects: ProjectRecord[], nextActiveProjectId = activeProjectId) {
    setProjects(nextProjects)
    setActiveProjectId(nextActiveProjectId)
    saveWorkspace({ projects: nextProjects, activeProjectId: nextActiveProjectId })
  }

  function handleCreateProject() {
    const next = createProject(projectName)
    updateWorkspace([next, ...projects], next.id)
    setProjectName('')
    setScript('')
    setPage('Pad')
  }

  function handleRenameProject() {
    if (!activeProject || !projectName.trim()) {
      return
    }
    const nextProjects = projects.map((project) =>
      project.id === activeProject.id ? renameProject(project, projectName) : project,
    )
    updateWorkspace(nextProjects, activeProject.id)
    setProjectName('')
  }

  function handleSelectRun(runId: string) {
    if (!activeProject) {
      return
    }
    const nextProjects = projects.map((project) =>
      project.id === activeProject.id ? selectRun(project, runId) : project,
    )
    updateWorkspace(nextProjects, activeProject.id)
    setPlayIndex(0)
    setPlaying(false)
  }

  async function handleSubmit(mode: RunMode, overrides?: Record<string, unknown>) {
    if (!activeProject) {
      return
    }
    const source = String(overrides ? bootstrap.original_brief || script : script).trim()
    if (!source || source.length > SCRIPT_LIMIT) {
      return
    }

    setLoadingMode(mode)
    setError(null)
    try {
      const state = await callApi(mode, {
        script: source,
        persist,
        ...(overrides ? { bootstrap_overrides: overrides } : {}),
      })
      const nextProjects = projects.map((project) =>
        project.id === activeProject.id ? appendRun(project, { mode, script, persist, state }) : project,
      )
      updateWorkspace(nextProjects, activeProject.id)
      setPage('Pad')
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'API request failed')
    } finally {
      setLoadingMode(null)
    }
  }

  function patchEntityCharpass(
    entityId: string,
    charpass: Record<string, unknown>,
    extra?: Record<string, unknown>,
  ) {
    if (!activeProject || !selectedRun) {
      return
    }
    const nextEntities = [...(selectedRun.state.entities ?? [])]
    const index = nextEntities.findIndex((entity) => entity.id === entityId)
    const current =
      index >= 0 ? nextEntities[index] : { id: entityId, kind: 'character', name: String(extra?.name ?? entityId) }
    const derivedImageMetadata = deriveCharacterImageMetadata(charpass)
    const payload = {
      ...asRecord(current.payload),
      charpass,
      ...derivedImageMetadata,
      ...(extra?.note !== undefined ? { note: extra.note } : {}),
      ...(extra?.continuity_tokens !== undefined ? { continuity_tokens: extra.continuity_tokens } : {}),
    }
    const nextEntity = { ...current, payload }
    if (index >= 0) {
      nextEntities[index] = nextEntity
    } else {
      nextEntities.push(nextEntity)
    }
    const nextState = { ...selectedRun.state, entities: nextEntities }
    const nextProjects = projects.map((project) => {
      if (project.id !== activeProject.id) {
        return project
      }
      return {
        ...project,
        updatedAt: new Date().toISOString(),
        runs: project.runs.map((run) => (run.id === selectedRun.id ? { ...run, state: nextState } : run)),
      }
    })
    updateWorkspace(nextProjects, activeProject.id)
  }

  function pageReady(pageId: PageId): boolean {
    if (pageId === 'Timeline') return timelineReady
    if (pageId === 'Map') return mapReady
    if (pageId === 'Player') return playerReady
    return true
  }

  function renderPad() {
    return (
      <section className="panel page-panel">
        <div className="section-header">
          <div>
            <h2>Pad</h2>
            <p>寫板是唯一可寫入口。可貼完整劇本，或只寫一句話角色簡述。</p>
          </div>
          <span className="pill pill-accent">Alpha Q1 API</span>
        </div>

        <label className="field">
          <span>劇本內容</span>
          <textarea
            value={script}
            onChange={(event) => setScript(event.target.value)}
            placeholder="一名年齡為8歲的小女孩，可愛風格，公主風"
          />
        </label>
        <p className={`hint-inline ${scriptLen > SCRIPT_LIMIT ? 'warn' : ''}`}>
          {scriptLen} / {SCRIPT_LIMIT} 字。空內容禁用送出。
        </p>

        <div className="inline-grid">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={persist}
              onChange={(event) => setPersist(event.target.checked)}
            />
            <span>同步啟用後端 persist（寫入 State Vault）</span>
          </label>
          <div className="hint-card">
            <strong>前端歷史</strong>
            <p>每次 parse/direct 都會存進目前專案的本地歷史，可切回 Timeline、Map 檢視。</p>
          </div>
        </div>

        <div className="button-row">
          <button
            className="primary"
            onClick={() => handleSubmit('direct')}
            disabled={!activeProject || !scriptOk || loadingMode !== null}
          >
            {loadingMode === 'direct' ? 'Directing...' : 'Direct 拆分鏡'}
          </button>
          <button
            className="secondary"
            onClick={() => handleSubmit('parse')}
            disabled={!activeProject || !scriptOk || loadingMode !== null}
          >
            {loadingMode === 'parse' ? 'Parsing...' : '僅 Parse'}
          </button>
          <button className="ghost" onClick={() => setScript(SAMPLE_SCRIPT)}>
            載入範例
          </button>
          <button className="ghost" onClick={() => setScript(SAMPLE_BRIEF)}>
            載入一句話
          </button>
        </div>
        {bootActive ? (
          <div className="next-card">
            <h3>敘事自舉預覽 · 可直接改</h3>
            <p>
              {String(bootWorld.name || '童話王國')} · {String(bootCharacter.name || '')}（
              {String(bootCharacter.age ?? '')}歲）
            </p>
            <label className="field">
              <span>名字</span>
              <input value={bootName} onChange={(event) => setBootName(event.target.value)} />
            </label>
            <label className="field">
              <span>MBTI</span>
              <input value={bootMbti} onChange={(event) => setBootMbti(event.target.value)} />
            </label>
            <label className="field">
              <span>內在矛盾</span>
              <input value={bootFlaw} onChange={(event) => setBootFlaw(event.target.value)} />
            </label>
            <label className="field">
              <span>性格</span>
              <textarea value={bootPersonality} onChange={(event) => setBootPersonality(event.target.value)} />
            </label>
            <label className="field">
              <span>習慣（一行一條）</span>
              <textarea value={bootHabits} onChange={(event) => setBootHabits(event.target.value)} />
            </label>
            <p className="hint-inline">
              年齡曲線：現在 {String(bootCurve.present ?? bootCharacter.age ?? '')} 歲；關鍵幀{' '}
              {Array.isArray(bootCurve.keyframes) ? bootCurve.keyframes.join('、') : '—'}
              ；其餘僅文字預留，不跑 1–80。
            </p>
            <div className="button-row">
              <button
                className="primary"
                onClick={() =>
                  handleSubmit('direct', {
                    name: bootName,
                    mbti: bootMbti,
                    inner_flaw: bootFlaw,
                    personality: bootPersonality,
                    habits: bootHabits.split('\n').map((item) => item.trim()).filter(Boolean),
                  })
                }
                disabled={!activeProject || loadingMode !== null}
              >
                套用並重跑 Direct
              </button>
              <button
                className="ghost"
                onClick={() => setScript(String(bootstrap.seed_script || ''))}
                disabled={!bootstrap.seed_script}
              >
                用生成劇本覆寫寫板
              </button>
            </div>
          </div>
        ) : null}
        {currentState ? (
          <div className="next-card">
            <h3>{shots.length ? '分鏡已完成' : '實體已解析'}</h3>
            <p>
              {shots.length} 個 shot · {characters.length} 個角色。Direct 不必先 Parse。
            </p>
            <div className="button-row">
              <button className="primary" onClick={() => setPage('Timeline')} disabled={!shots.length}>
                查看分鏡
              </button>
              <button className="secondary" onClick={() => setPage('Dashboard')}>
                角色護照
              </button>
              <button className="ghost" onClick={() => setPage('Player')} disabled={!shots.length}>
                播放
              </button>
            </div>
          </div>
        ) : null}
      </section>
    )
  }

  function renderTimeline() {
    return (
      <section className="panel page-panel">
        <div className="section-header">
          <div>
            <h2>Timeline</h2>
            <p>依 shot 順序檢視 Director 輸出，保持只讀。</p>
          </div>
          <span className="pill">{shots.length} shots</span>
        </div>
        <p className="readonly-notice">此畫面為只讀資料，來源是 State Vault 的 shots。</p>
        {shots.length > 0 ? (
          <div className="button-row" style={{ marginBottom: 12 }}>
            <button className="primary" onClick={() => setPage('Dashboard')}>
              下一步：角色護照
            </button>
            <button className="secondary" onClick={() => setPage('Player')}>
              播放分鏡
            </button>
          </div>
        ) : null}

        {shots.length === 0 ? (
          <div className="empty-state">目前沒有 shots。先在 Pad 執行 Direct。</div>
        ) : (
          <div className="content-grid">
            <div className="list-column">
              {shots.map((shot) => (
                <button
                  key={shot.id}
                  className={`list-item ${selectedShot?.id === shot.id ? 'active' : ''}`}
                  onClick={() => setSelectedShotId(shot.id)}
                >
                  <strong>Shot {shot.order ?? '-'}</strong>
                  <span>{shot.camera_language || '未指定鏡頭語言'}</span>
                  <span>
                    {shot.duration_ms ?? 0}ms · {shot.scene_id || '—'} · {beatOf(shot)}
                  </span>
                </button>
              ))}
            </div>
            <DetailCard
              title={selectedShot ? `Shot ${selectedShot.order ?? '-'}` : 'Shot Detail'}
              body={selectedShot}
            />
          </div>
        )}
      </section>
    )
  }

  function renderDashboard() {
    const assets = currentState?.assets ?? []
    const grouped = entities.reduce<Record<string, number>>((acc, entity) => {
      const key = entity.kind || 'unknown'
      acc[key] = (acc[key] ?? 0) + 1
      return acc
    }, {})

    return (
      <section className="panel page-panel">
        <div className="section-header">
          <div>
            <h2>Dashboard</h2>
            <p>專案級總覽：實體、shots、算力池、外掛與角色護照子面板。</p>
          </div>
          <span className="pill pill-accent">{activeProject ? getProjectStatus(activeProject) : 'missing'}</span>
        </div>
        <p className="readonly-notice">總覽為只讀刷新。角色護照是 Dashboard 子面板，不是第六個用戶層畫面。</p>

        <div className="next-grid">
          <div className="next-card">
            <h3>1. 劇本與分鏡</h3>
            <p>{shots.length ? `已有 ${shots.length} 個 shot` : '尚未 Direct。先回 Pad 拆分鏡。'}</p>
            <div className="button-row">
              <button className="secondary" onClick={() => setPage('Pad')}>
                {shots.length ? '回 Pad' : '去 Direct'}
              </button>
            </div>
          </div>
          <div className="next-card">
            <h3>2. 角色護照</h3>
            <p>{characters.length ? `劇本有 ${characters.length} 個角色，請在下方子面板編輯。` : '尚無角色實體。'}</p>
          </div>
          <div className="next-card">
            <h3>3. 播放</h3>
            <p>{shots.length ? '可用 Player 預覽分鏡序列。' : '等 Direct 完成後即可播放。'}</p>
            <div className="button-row">
              <button className="secondary" onClick={() => setPage('Player')} disabled={!shots.length}>
                開 Player
              </button>
            </div>
          </div>
        </div>

        <div className="metrics-grid">
          <MetricCard label="Entities" value={entities.length} />
          <MetricCard label="Shots" value={shots.length} />
          <MetricCard label="Trace Records" value={traces.length} />
          <MetricCard label="Assets" value={assets.length} />
        </div>

        <h3 className="subhead">算力池（只讀，不得自創池名）</h3>
        <div className="pool-grid">
          {HARDWARE_POOLS.map((pool) => (
            <div key={pool.code} className={`pool-card ${pool.code === 'Mid Core' ? 'active' : ''}`}>
              <strong>{pool.code}</strong>
              <span>
                {pool.level} · {pool.zh}
              </span>
              <small>{pool.code === 'Mid Core' ? '本階段 Router 固定選此池' : '待機'}</small>
            </div>
          ))}
        </div>

        <h3 className="subhead">外掛觸發摘要</h3>
        <div className="plugin-grid">
          {PLUGIN_MATRIX.map(([pid, code, zh, phase]) => (
            <div key={pid} className="plugin-card">
              <strong>
                {pid} {code}
              </strong>
              <span>{zh}</span>
              <small>
                {phase} · {pid === 'P7' ? 'Alpha Q1 可觸發' : '介面已凍結'}
              </small>
            </div>
          ))}
        </div>

        <h3 className="subhead">KPI 預留 · 連續性誤差</h3>
        <div className="hint-card">
          <strong>continuity_error = —</strong>
          <p>Keeper（Alpha Q2）尚未回傳此欄位。面板先佔位，不發明數值。</p>
        </div>

        <div className="content-grid dashboard-grid">
          <DetailCard title="Entities by kind" body={grouped} />
          <div className="panel inset-panel">
            <h3>Phase Guardrail</h3>
            <p>`/parse` 與 `/direct` 已可用；`/keep`、`/run`、`/mux` 仍為 501 placeholder。</p>
            <p>角色護照快捷鍵：S 儲存（焦點在子面板時）。</p>
          </div>
        </div>

        <CharpassPanel
          apiBase={API_BASE}
          projectId={activeProject?.id}
          persist={persist}
          characters={characters}
          selectedCharacter={selectedCharacter}
          onSelect={setSelectedCharId}
          onPatchEntity={patchEntityCharpass}
          onError={setError}
        />
      </section>
    )
  }

  function renderMap() {
    return (
      <section className="panel page-panel map-panel">
        <div className="section-header">
          <div>
            <h2>Map</h2>
            <p>以節點圖呈現 entities → trace_log → shots。畫面代號必須是 Map。</p>
          </div>
          <span className="pill">{traces.length} traces</span>
        </div>
        <p className="readonly-notice">此畫面為只讀資料，不得編輯節點或替換資料來源。</p>

        {graph.nodes.length === 0 ? (
          <div className="empty-state">目前沒有可視化資料。先執行 Parse 或 Direct。</div>
        ) : (
          <div className="map-layout">
            <div className="flow-shell">
              <ReactFlow
                nodes={graph.nodes}
                edges={graph.edges}
                fitView
                onNodeClick={(_, node) => {
                  const traceMatch = traces.find((trace) => trace.id === node.id)
                  if (traceMatch) {
                    setSelectedTraceId(traceMatch.id)
                    if (traceMatch.shot_id) {
                      setSelectedShotId(traceMatch.shot_id)
                    }
                  }
                  const shotMatch = shots.find((shot) => shot.id === node.id)
                  if (shotMatch) {
                    setSelectedShotId(shotMatch.id)
                  }
                }}
              >
                <MiniMap zoomable pannable />
                <Controls />
                <Background gap={20} color="#334155" />
              </ReactFlow>
            </div>
            <div className="inspector-column">
              <DetailCard title="Trace Inspector" body={selectedTrace} />
              <DetailCard title="Linked Shot" body={selectedShot} />
              {selectedShot ? (
                <button className="secondary" onClick={() => setPage('Timeline')}>
                  跳到 Timeline 對應 shot
                </button>
              ) : null}
            </div>
          </div>
        )}
      </section>
    )
  }

  function renderPlayer() {
    const muxUri = currentState?.mux_uri
    const current = shots[playIndex]

    return (
      <section className="panel page-panel">
        <div className="section-header">
          <div>
            <h2>Player</h2>
            <p>用戶層播放器。合流成品由 Muxer 提供；與外掛 P9 配樂同名不同層。</p>
          </div>
          <span className="pill">{muxUri ? 'mux_uri 就緒' : 'Muxer 尚未上線'}</span>
        </div>

        {!muxUri ? (
          <div className="notice-banner">
            Alpha Q4 合流器尚未上線（POST /mux 回 501）。以下先以 Director 分鏡序列播放，不把此畫面改名。
          </div>
        ) : null}

        <div className="player-shell filled">
          {muxUri ? (
            <video controls className="video-box" src={String(muxUri)} />
          ) : shots.length === 0 ? (
            <div className="empty-state">尚無分鏡。先在 Pad 執行 Direct。</div>
          ) : (
            <div className="storyboard-frame">
              <p className="eyebrow">Shot {current?.order ?? '-'}</p>
              <h3>{current?.camera_language || '未指定鏡頭語言'}</h3>
              <p>{beatOf(current)}</p>
              <small>
                {current?.duration_ms ?? 0}ms · {current?.scene_id || '—'}
              </small>
            </div>
          )}
        </div>

        {!muxUri && shots.length > 0 ? (
          <div className="player-controls">
            <button className="primary" onClick={() => setPlaying((value) => !value)}>
              {playing ? 'Pause' : 'Play'}
            </button>
            <input
              type="range"
              min={0}
              max={Math.max(shots.length - 1, 0)}
              value={playIndex}
              onChange={(event) => {
                setPlaying(false)
                setPlayIndex(Number(event.target.value))
              }}
            />
            <span className="muted">
              {padMs(elapsedMs)} / {padMs(totalMs)}
            </span>
            <button
              className="ghost"
              onClick={() => {
                setPlaying(false)
                setPlayIndex(0)
              }}
            >
              Refresh
            </button>
          </div>
        ) : null}
      </section>
    )
  }

  function renderPage() {
    switch (page) {
      case 'Timeline':
        return renderTimeline()
      case 'Dashboard':
        return renderDashboard()
      case 'Map':
        return renderMap()
      case 'Player':
        return renderPlayer()
      case 'Pad':
      default:
        return renderPad()
    }
  }

  return (
    <div className="app-shell">
      {loadingMode ? (
        <div className="loading-mask">
          <span className="spinner" /> {loadingMode === 'parse' ? 'Parsing…' : 'Directing…'}
        </div>
      ) : null}
      <aside className="sidebar">
        <div className="brand-block">
          <p className="eyebrow">Narratron</p>
          <h1>GUI Prototype</h1>
          <p className="muted">Pad → Timeline → Dashboard → Map → Player</p>
        </div>

        <div className="panel sidebar-panel">
          <h3>Projects</h3>
          <label className="field">
            <span>專案名稱</span>
            <input
              value={projectName}
              onChange={(event) => setProjectName(event.target.value)}
              placeholder="例如：Episode 01"
            />
          </label>
          <div className="button-row compact">
            <button className="primary" onClick={handleCreateProject}>
              新增專案
            </button>
            <button className="ghost" onClick={handleRenameProject} disabled={!activeProject}>
              重新命名
            </button>
          </div>
          <div className="project-list">
            {projects.map((project) => (
              <button
                key={project.id}
                className={`list-item ${project.id === activeProjectId ? 'active' : ''}`}
                onClick={() => setActiveProjectId(project.id)}
              >
                <strong>{project.name}</strong>
                <span>{project.runs.length} runs</span>
              </button>
            ))}
          </div>
        </div>

        <div className="panel sidebar-panel">
          <h3>Pages</h3>
          <div className="page-nav">
            {PAGE_ORDER.map((pageId, index) => {
              const ready = pageReady(pageId)
              const next =
                (pageId === 'Pad' && !timelineReady) ||
                (pageId === 'Timeline' && timelineReady && page !== 'Timeline') ||
                (pageId === 'Dashboard' && timelineReady && page === 'Timeline')
              return (
                <button
                  key={pageId}
                  className={`nav-button ${page === pageId ? 'active' : ''} ${next ? 'next' : ''}`}
                  title={ready ? PAGE_ZH[pageId] : '可先點入查看空狀態；內容來自 Pad 的 Direct'}
                  onClick={() => setPage(pageId)}
                >
                  <span>
                    {index + 1} {pageId}
                  </span>
                  <small>{next ? '下一步' : PAGE_ZH[pageId]}</small>
                </button>
              )
            })}
          </div>
        </div>

        <div className="panel sidebar-panel">
          <h3>Run History</h3>
          {!activeProject || activeProject.runs.length === 0 ? (
            <div className="empty-state small">尚無 run 歷史。</div>
          ) : (
            <div className="project-list">
              {activeProject.runs.map((run) => (
                <button
                  key={run.id}
                  className={`list-item ${selectedRun?.id === run.id ? 'active' : ''}`}
                  onClick={() => handleSelectRun(run.id)}
                >
                  <strong>{run.mode.toUpperCase()}</strong>
                  <span>{fmtDate(run.createdAt)}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar panel">
          <div>
            <p className="eyebrow">Current Project</p>
            <h2>{activeProject?.name ?? '尚未選擇專案'}</h2>
            <p className="muted">
              {selectedRun
                ? `${selectedRun.mode.toUpperCase()} · ${fmtDate(selectedRun.createdAt)}`
                : '建立專案後，在 Pad 輸入劇本並送出'}
            </p>
          </div>
          <div className="status-strip">
            <span className="pill">API: {API_BASE || 'vite proxy → :8080'}</span>
            <span className="pill pill-accent">Persist: {persist ? 'on' : 'off'}</span>
            <span className="pill">{shots.length} shots</span>
            <span className="pill">{traces.length} traces</span>
          </div>
        </header>

        {error ? <div className="error-banner">{error}</div> : null}
        {renderPage()}
      </main>
    </div>
  )
}

function MetricCard(props: { label: string; value: number }) {
  return (
    <div className="metric-card">
      <span>{props.label}</span>
      <strong>{props.value}</strong>
    </div>
  )
}

function DetailCard(props: { title: string; body: ShotRecord | TraceRecord | object | undefined }) {
  return (
    <div className="panel inset-panel detail-card">
      <h3>{props.title}</h3>
      {props.body ? <pre>{jsonSummary(props.body)}</pre> : <div className="empty-state small">尚未選擇資料。</div>}
    </div>
  )
}
