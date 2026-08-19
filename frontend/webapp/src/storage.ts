import type { ProjectRecord, ProjectRun, RunMode, NarratronState } from './types'

const STORAGE_KEY = 'narratron:webapp:v1'

interface StorageShape {
  projects: ProjectRecord[]
  activeProjectId?: string
}

function nowIso(): string {
  return new Date().toISOString()
}

function makeId(prefix: string): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `${prefix}-${crypto.randomUUID()}`
  }
  return `${prefix}-${Math.random().toString(16).slice(2)}`
}

export function loadWorkspace(): StorageShape {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) {
    return { projects: [] }
  }

  try {
    const parsed = JSON.parse(raw) as StorageShape
    return {
      projects: Array.isArray(parsed.projects) ? parsed.projects : [],
      activeProjectId: parsed.activeProjectId,
    }
  } catch {
    return { projects: [] }
  }
}

export function saveWorkspace(workspace: StorageShape): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(workspace))
}

export function createProject(name?: string): ProjectRecord {
  const stamp = nowIso()
  return {
    id: makeId('project'),
    name: name?.trim() || `Project ${new Date().toLocaleString()}`,
    createdAt: stamp,
    updatedAt: stamp,
    runs: [],
  }
}

export function appendRun(
  project: ProjectRecord,
  input: { mode: RunMode; script: string; persist: boolean; state: NarratronState },
): ProjectRecord {
  const run: ProjectRun = {
    id: makeId('run'),
    createdAt: nowIso(),
    mode: input.mode,
    script: input.script,
    persist: input.persist,
    state: input.state,
  }

  return {
    ...project,
    updatedAt: run.createdAt,
    selectedRunId: run.id,
    runs: [run, ...project.runs],
  }
}

export function selectRun(project: ProjectRecord, runId: string): ProjectRecord {
  return { ...project, selectedRunId: runId, updatedAt: nowIso() }
}

export function renameProject(project: ProjectRecord, name: string): ProjectRecord {
  return { ...project, name: name.trim() || project.name, updatedAt: nowIso() }
}

export function getSelectedRun(project?: ProjectRecord): ProjectRun | undefined {
  if (!project) {
    return undefined
  }
  return project.runs.find((run) => run.id === project.selectedRunId) ?? project.runs[0]
}
