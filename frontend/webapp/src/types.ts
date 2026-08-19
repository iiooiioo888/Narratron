export type PageId = 'Pad' | 'Timeline' | 'Dashboard' | 'Map' | 'Player'
export type RunMode = 'parse' | 'direct'

export interface EntityRecord {
  id: string
  name?: string
  kind?: string
  payload?: unknown
}

export interface ShotRecord {
  id: string
  order?: number
  scene_id?: string | null
  camera_language?: string
  duration_ms?: number | null
  payload?: unknown
}

export interface TraceRecord {
  id: string
  entity_id?: string | null
  shot_id?: string | null
  cause?: string
  effect?: string
  payload?: unknown
}

export interface NarratronState {
  entities?: EntityRecord[]
  shots?: ShotRecord[]
  traces?: TraceRecord[]
  assets?: unknown[]
  mux_uri?: string | null
  [key: string]: unknown
}

export interface ProjectRun {
  id: string
  createdAt: string
  mode: RunMode
  script: string
  persist: boolean
  state: NarratronState
}

export interface ProjectRecord {
  id: string
  name: string
  createdAt: string
  updatedAt: string
  selectedRunId?: string
  runs: ProjectRun[]
}
