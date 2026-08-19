import { useMemo, useState } from 'react'
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
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

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
  return new Date(value).toLocaleString()
}

function jsonSummary(value: unknown): string {
  if (value == null) {
    return 'No payload'
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

async function callApi(
  mode: RunMode,
  body: { script: string; persist: boolean },
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
  }

  async function handleSubmit(mode: RunMode) {
    if (!activeProject || !script.trim()) {
      return
    }

    setLoadingMode(mode)
    setError(null)
    try {
      const state = await callApi(mode, { script, persist })
      const nextProjects = projects.map((project) =>
        project.id === activeProject.id ? appendRun(project, { mode, script, persist, state }) : project,
      )
      updateWorkspace(nextProjects, activeProject.id)
      setPage(mode === 'direct' ? 'Timeline' : 'Dashboard')
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

  function renderPad() {
    return (
      <section className="panel page-panel">
        <div className="section-header">
          <div>
            <h2>Pad</h2>
            <p>寫板是唯一可寫入口，負責送出劇本到 `/parse` 或 `/direct`。</p>
          </div>
          <span className="pill pill-accent">Alpha Q1 API</span>
        </div>

        <label className="field">
          <span>劇本內容</span>
          <textarea
            value={script}
            onChange={(event) => setScript(event.target.value)}
            placeholder="輸入角色、道具、場景與分鏡描述..."
          />
        </label>

        <div className="inline-grid">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={persist}
              onChange={(event) => setPersist(event.target.checked)}
            />
            <span>同步啟用後端 `persist`</span>
          </label>
          <div className="hint-card">
            <strong>前端歷史</strong>
            <p>每次 parse/direct 都會存進目前專案的本地歷史，可切回 Timeline、Map 檢視。</p>
          </div>
        </div>

        <div className="button-row">
          <button
            className="primary"
            onClick={() => handleSubmit('parse')}
            disabled={!activeProject || !script.trim() || loadingMode !== null}
          >
            {loadingMode === 'parse' ? 'Parsing...' : 'Parse'}
          </button>
          <button
            className="secondary"
            onClick={() => handleSubmit('direct')}
            disabled={!activeProject || !script.trim() || loadingMode !== null}
          >
            {loadingMode === 'direct' ? 'Directing...' : 'Direct'}
          </button>
        </div>
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

        {shots.length === 0 ? (
          <div className="empty-state">目前沒有 shots。先在 Pad 執行 `Direct`。</div>
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
                  <span>{shot.camera_language || 'camera language missing'}</span>
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
            <p>專案級總覽，整合實體、shots、trace 與後端階段提示。</p>
          </div>
          <span className="pill pill-accent">{activeProject ? getProjectStatus(activeProject) : 'missing'}</span>
        </div>

        <div className="metrics-grid">
          <MetricCard label="Entities" value={entities.length} />
          <MetricCard label="Shots" value={shots.length} />
          <MetricCard label="Trace Records" value={traces.length} />
          <MetricCard label="Assets" value={assets.length} />
        </div>

        <div className="content-grid dashboard-grid">
          <DetailCard title="Entities by kind" body={grouped} />
          <div className="panel inset-panel">
            <h3>Phase Guardrail</h3>
            <p>`/parse` 與 `/direct` 已可用；`/keep`、`/run`、`/mux` 仍為 501 placeholder。</p>
            <p>前端歷史已支援多專案、多次 run 切換。</p>
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
            <p>以 React Flow 呈現 entities → trace_log → shots 的可互動因果圖。</p>
          </div>
          <span className="pill">{traces.length} traces</span>
        </div>

        {graph.nodes.length === 0 ? (
          <div className="empty-state">目前沒有可視化資料。先執行 `Parse` 或 `Direct`。</div>
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
            </div>
          </div>
        )}
      </section>
    )
  }

  function renderPlayer() {
    return (
      <section className="panel page-panel">
        <div className="section-header">
          <div>
            <h2>Player</h2>
            <p>保留合成結果播放區，等待後端 `Muxer` 接入。</p>
          </div>
          <span className="pill">placeholder</span>
        </div>

        <div className="player-shell">
          {currentState?.mux_uri ? (
            <video controls className="video-box" src={String(currentState.mux_uri)} />
          ) : (
            <div className="empty-state">
              `mux_uri` 尚未提供。Alpha Q1 階段這裡只顯示預留播放器版位。
            </div>
          )}
        </div>
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
      <aside className="sidebar">
        <div className="brand-block">
          <p className="eyebrow">Narratron</p>
          <h1>GUI Prototype</h1>
          <p className="muted">Pad → Timeline → Dashboard → Map → Player</p>
        </div>

        <div className="panel sidebar-panel">
          <h3>Projects</h3>
          <label className="field">
            <span>Project name</span>
            <input
              value={projectName}
              onChange={(event) => setProjectName(event.target.value)}
              placeholder="例如：Episode 01"
            />
          </label>
          <div className="button-row compact">
            <button className="primary" onClick={handleCreateProject}>
              New Project
            </button>
            <button className="ghost" onClick={handleRenameProject} disabled={!activeProject}>
              Rename
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
            {PAGE_ORDER.map((pageId) => (
              <button
                key={pageId}
                className={`nav-button ${page === pageId ? 'active' : ''}`}
                onClick={() => setPage(pageId)}
              >
                <span>{pageId}</span>
              </button>
            ))}
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
            <h2>{activeProject?.name ?? 'No project selected'}</h2>
            <p className="muted">
              {selectedRun
                ? `${selectedRun.mode.toUpperCase()} · ${fmtDate(selectedRun.createdAt)}`
                : '建立專案後，在 Pad 輸入劇本並送出'}
            </p>
          </div>
          <div className="status-strip">
            <span className="pill">API: {API_BASE || 'vite proxy -> :8080'}</span>
            <span className="pill pill-accent">Persist: {persist ? 'on' : 'off'}</span>
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
      {props.body ? <pre>{jsonSummary(props.body)}</pre> : <div className="empty-state small">No data selected.</div>}
    </div>
  )
}
