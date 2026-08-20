import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

type ConflictStrategy = 'create_new' | 'merge' | 'overwrite'
type CharpassLayer =
  | '_identity'
  | '_body'
  | '_style'
  | '_expression'
  | '_pose'
  | '_physics'
  | '_voice'
  | '_causal'
  | '_constraints'
  | '_extensions'

const LAYERS: CharpassLayer[] = [
  '_identity',
  '_body',
  '_style',
  '_expression',
  '_pose',
  '_physics',
  '_voice',
  '_causal',
  '_constraints',
  '_extensions',
]

export interface CharacterCard {
  id: string
  name?: string
  kind?: string
  payload?: unknown
}

interface ImageRefItem {
  path: string
  uri?: string
  angle?: string
  note?: string
}

interface CharacterThumbnail {
  src: string
  label: string
}

interface CharacterSummary {
  id: string
  name?: string
  metadata?: Record<string, unknown>
}

interface QueueTask {
  id: number
  core_id: number
  character_name?: string
  variant_hash: string
  evolution_params: Record<string, unknown>
  status: string
  review_status?: string | null
  effective_status?: string | null
  purpose?: string | null
  angles?: string[]
  image_count?: number
  thumbnail_asset_path?: string | null
  face_detail_asset_path?: string | null
  representative_asset_path?: string | null
  representative_angle?: string | null
  has_face_detail?: boolean
  face_detail_count?: number
  priority: number
  error_message?: string | null
  retry_count?: number
  max_retries?: number
  result_url?: string | null
  result_metadata?: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

interface TaskImageDetail extends GeneratedImageItem {
  summary?: string
}

function firstNonEmptyString(...values: unknown[]): string {
  for (const value of values) {
    const text =
      typeof value === 'string'
        ? value.trim()
        : value == null
          ? ''
          : String(value).trim()
    if (text) {
      return text
    }
  }
  return ''
}

function previewAssetPath(source: unknown, reviewStatus?: string): string {
  const item = asRecord(source)
  const status = normalizeStatus(reviewStatus ?? '')
  if (status === 'accepted' || status === 'ready') {
    return firstNonEmptyString(item.final_asset_path, item.asset_path, item.path)
  }
  if (status === 'rejected') {
    return ''
  }
  return firstNonEmptyString(item.asset_path, item.final_asset_path, item.path)
}

function taskTopLevelString(task: QueueTask, field: keyof QueueTask): string {
  const top = task[field]
  if (typeof top === 'string' && top.trim()) {
    return top.trim()
  }
  const metadata = asRecord(task.result_metadata)
  const imageGeneration = asRecord(metadata.image_generation)
  return firstNonEmptyString(metadata[field as string], imageGeneration[field as string])
}

function imageRemoteUrl(source: unknown): string {
  const item = asRecord(source)
  return firstNonEmptyString(item.url, item.uri)
}

function imageSummary(source: unknown, maxLength = 96): string | undefined {
  const item = asRecord(source)
  return (
    summarizeText(item.revised_prompt ?? item.note ?? item.caption ?? item.filename ?? '', '', maxLength) || undefined
  )
}

function taskImagePayload(task: QueueTask): Record<string, unknown> {
  const resultMetadata = asRecord(task.result_metadata)
  const imageGeneration = asRecord(resultMetadata.image_generation)
  const merged: Record<string, unknown> = { ...imageGeneration }
  if (task.purpose) merged.purpose = task.purpose
  if (task.angles?.length) merged.angles = task.angles
  if (task.thumbnail_asset_path) merged.thumbnail_asset_path = task.thumbnail_asset_path
  if (task.face_detail_asset_path) merged.face_detail_asset_path = task.face_detail_asset_path
  if (task.representative_asset_path) merged.representative_asset_path = task.representative_asset_path
  if (task.representative_angle) merged.representative_angle = task.representative_angle
  if (task.has_face_detail != null) merged.has_face_detail = task.has_face_detail
  if (task.face_detail_count != null) merged.face_detail_count = task.face_detail_count
  if (task.image_count != null) merged.image_count = task.image_count
  if (Object.keys(merged).length) {
    return merged
  }
  return resultMetadata
}

function mergedQueueImages(payload: Record<string, unknown>, reviewStatus?: string): unknown[] {
  const bucket = new Map<string, unknown>()

  const register = (source: unknown, forcedAngle?: string) => {
    const item = asRecord(source)
    const assetPath = previewAssetPath(item, reviewStatus)
    const rawUrl = imageRemoteUrl(item)
    if (!assetPath && !rawUrl) {
      return
    }
    const normalizedAngle = String(forcedAngle ?? item.angle ?? '').trim()
    const key = `${assetPath || rawUrl}::${normalizedAngle}`
    if (bucket.has(key)) {
      return
    }
    bucket.set(key, normalizedAngle ? { ...item, angle: normalizedAngle } : item)
  }

  for (const image of asArray(payload.face_detail_images)) {
    register(image, 'face_detail')
  }
  for (const image of asArray(payload.images)) {
    register(image)
  }
  for (const [angle, value] of Object.entries(asRecord(payload.images_by_angle))) {
    for (const image of asArray(value)) {
      register(image, angle)
    }
  }

  return [...bucket.values()]
}

function queueImageCollections(payload: Record<string, unknown>, reviewStatus?: string): unknown[] {
  return mergedQueueImages(payload, reviewStatus)
}

function taskPreviewMetadata(task: QueueTask): Record<string, string> {
  const reviewStatus = taskReviewStatus(task)
  const imageGen = taskImagePayload(task)
  const detailImages = taskDetailImages('', task)
  const detailPaths = detailImages.map((item) => item.path).filter(Boolean)
  const faceDetailByAngle = asArray(asRecord(imageGen.images_by_angle).face_detail)
  const faceDetailAssetPath = firstNonEmptyString(
    taskTopLevelString(task, 'face_detail_asset_path'),
    previewAssetPath(faceDetailByAngle[0], reviewStatus),
    previewAssetPath(asArray(imageGen.face_detail_images)[0], reviewStatus),
    detailImages.find((item) => item.angle === 'face_detail')?.path,
    detailPaths.find((path) => path.includes('face_detail')),
  )
  const thumbnailAssetPath = firstNonEmptyString(
    faceDetailAssetPath,
    taskTopLevelString(task, 'thumbnail_asset_path'),
    taskTopLevelString(task, 'representative_asset_path'),
    previewAssetPath(imageGen.thumbnail_image, reviewStatus),
    detailImages.find((item) => item.angle !== 'face_detail')?.path,
    detailPaths[0],
  )
  const metadata: Record<string, string> = {}
  if (thumbnailAssetPath) {
    metadata.thumbnail_asset_path = thumbnailAssetPath
  }
  if (faceDetailAssetPath) {
    metadata.face_detail_asset_path = faceDetailAssetPath
  }
  return metadata
}

function mergeTaskPreviewSummaries(tasks: QueueTask[]): Record<string, CharacterSummary> {
  const previewRank = (task: QueueTask) => {
    const reviewStatus = taskReviewStatus(task)
    if (reviewStatus === 'accepted' || normalizeStatus(task.status) === 'ready') return 0
    if (reviewStatus === 'pending') return 1
    return 3
  }
  const ordered = [...tasks].sort((left, right) => {
    const rankDelta = previewRank(left) - previewRank(right)
    if (rankDelta !== 0) {
      return rankDelta
    }
    return String(right.updated_at ?? right.created_at ?? '').localeCompare(String(left.updated_at ?? left.created_at ?? ''))
  })
  const next: Record<string, CharacterSummary> = {}
  for (const task of ordered) {
    if (taskReviewStatus(task) !== 'accepted' && normalizeStatus(task.status) !== 'ready') continue
    const characterId = String(task.core_id)
    if (next[characterId]) {
      continue
    }
    const metadata = taskPreviewMetadata(task)
    if (!Object.keys(metadata).length) {
      continue
    }
    next[characterId] = {
      id: characterId,
      name: task.character_name?.trim() || undefined,
      metadata,
    }
  }
  return next
}

function stopSummaryToggle(event: React.MouseEvent<HTMLElement>) {
  event.preventDefault()
  event.stopPropagation()
}

function reviewStatusLabelFromStatus(status?: string): string | null {
  const normalized = normalizeStatus(status)
  if (!normalized) {
    return null
  }
  if (normalized === 'pending') return '等待生成'
  if (normalized === 'accepted' || normalized === 'ready') return '已入庫'
  if (normalized === 'rejected') return '已拒絕'
  return normalized
}

function branchReviewStatusLabel(branch: VersionBranchItem): string | null {
  const summaryFields = asRecord(branch.summary_fields)
  return reviewStatusLabelFromStatus(
    firstNonEmptyString(
      branch.review_status,
      branch.review_label,
      String(summaryFields.review_label ?? ''),
      String(summaryFields.review_status ?? ''),
    ),
  )
}

interface QueueStats {
  total_pending: number
  total_waiting?: number
  total_ready: number
  total_failed: number
  average_wait_time_ms: number
  oldest_pending_age_seconds: number
}

interface QueueTaskListResponse {
  storage_mode: string
  stats: QueueStats
  tasks: QueueTask[]
  total: number
}

interface AgeSpanStep {
  task_id?: number | null
  step_index: number
  phase: string
  age?: number | null
  status: string
  error_message?: string | null
}

interface QueueWorkerStatus {
  paused: boolean
  busy: boolean
  auto_run: boolean
  last_task_id?: number | null
  last_status?: string | null
  last_error?: string | null
}

interface AgeSpanPipelineStatus {
  pipeline_id?: string | null
  core_id?: number | null
  character_name?: string | null
  total_steps: number
  accepted_count: number
  ready_pending_review_count: number
  pending_count: number
  waiting_count?: number
  failed_count: number
  blocking_task_id?: number | null
  blocking_reason?: string | null
  next_runnable_task_id?: number | null
  next_phase?: string | null
  next_age?: number | null
  has_open_pipeline: boolean
  steps?: AgeSpanStep[]
}

type PipelineStepResult = 'blocked' | 'processed' | 'await_review' | 'idle' | 'failed'

type AgeSpanPhaseTab = 'face_detail' | 'tpose'

function ageSpanStepsForPhase(steps: AgeSpanStep[], phase: AgeSpanPhaseTab): AgeSpanStep[] {
  return steps.filter((step) => normalizeStatus(step.phase) === phase)
}

function ageSpanStepStatusLabel(status: string): string {
  const normalized = normalizeStatus(status)
  if (normalized === 'accepted') return '已入庫'
  if (normalized === 'ready') return '已入庫'
  if (normalized === 'pending') return '等待生成'
  if (normalized === 'waiting') return '排隊中'
  if (normalized === 'rejected') return '拒絕'
  if (normalized === 'missing') return '—'
  return normalized || '—'
}

function countStepsByStatus(steps: AgeSpanStep[], status: string): number {
  const target = normalizeStatus(status)
  return steps.filter((step) => normalizeStatus(step.status) === target).length
}

type WorkflowPhase = 'setup' | 'generate' | 'complete'

interface WorkflowSnapshot {
  phase: WorkflowPhase
  title: string
  hint: string
  canAutoRun: boolean
  hasFailed: boolean
  isEmpty: boolean
  isComplete: boolean
}

const WORKFLOW_STEPS: Array<{ key: WorkflowPhase; label: string }> = [
  { key: 'setup', label: '建立任務' },
  { key: 'generate', label: '自動生圖入庫' },
  { key: 'complete', label: '完成' },
]

const WORKFLOW_PHASE_ORDER: WorkflowPhase[] = ['setup', 'generate', 'complete']

const AUTO_CONTINUE_STORAGE_KEY = 'characteros-queue-auto-continue'

function deriveWorkflowSnapshot(
  queueData: QueueTaskListResponse | null,
  ageSpanStatus: AgeSpanPipelineStatus | null,
  queueAutoRun: boolean,
): WorkflowSnapshot {
  const stats = queueData?.stats
  const taskCount = queueData?.tasks?.length ?? 0
  const failedCount = stats?.total_failed ?? ageSpanStatus?.failed_count ?? 0
  const pendingCount = stats?.total_pending ?? ageSpanStatus?.pending_count ?? 0
  const waitingCount = stats?.total_waiting ?? ageSpanStatus?.waiting_count ?? 0

  if (taskCount === 0) {
    return {
      phase: 'setup',
      title: '準備建立生圖任務',
      hint: '選擇角色後，一鍵建立 1–80 歲年齡軸；系統會自動逐步生圖並直接入庫。',
      canAutoRun: false,
      hasFailed: false,
      isEmpty: true,
      isComplete: false,
    }
  }

  const totalSteps = ageSpanStatus?.total_steps ?? 0
  const acceptedCount = ageSpanStatus?.accepted_count ?? 0
  if (totalSteps > 0 && acceptedCount >= totalSteps && pendingCount === 0 && waitingCount === 0) {
    return {
      phase: 'complete',
      title: '年齡軸已全部完成',
      hint: `${totalSteps} 步生圖流程已完成，可清空佇列或建立新任務。`,
      canAutoRun: false,
      hasFailed: failedCount > 0,
      isEmpty: false,
      isComplete: true,
    }
  }

  if (queueAutoRun || pendingCount > 0 || waitingCount > 0 || ageSpanStatus?.next_runnable_task_id) {
    return {
      phase: 'generate',
      title: queueAutoRun ? '自動生圖進行中' : '有待處理任務',
      hint: queueAutoRun
        ? '後端正在向 AI 請求生圖；完成後自動入庫並接下一筆。'
        : '後端 worker 已暫停。按「繼續後端生圖」即可從下一步接著跑。',
      canAutoRun: !queueAutoRun && (pendingCount > 0 || waitingCount > 0),
      hasFailed: failedCount > 0,
      isEmpty: false,
      isComplete: false,
    }
  }

  return {
    phase: 'complete',
    title: '佇列閒置',
    hint: '目前沒有待處理任務。',
    canAutoRun: false,
    hasFailed: failedCount > 0,
    isEmpty: false,
    isComplete: false,
  }
}

function WorkflowStepper({ phase }: { phase: WorkflowPhase }) {
  const currentIndex = WORKFLOW_PHASE_ORDER.indexOf(phase)
  return (
    <div className="workflow-stepper" aria-label="生圖工作流步驟">
      {WORKFLOW_STEPS.map((step, index) => {
        const isComplete = index < currentIndex
        const isCurrent = index === currentIndex
        return (
          <div
            key={step.key}
            className={`workflow-step${isComplete ? ' is-complete' : ''}${isCurrent ? ' is-current' : ''}`}
          >
            <span className="workflow-step-index">{isComplete ? '✓' : index + 1}</span>
            <span className="workflow-step-label">{step.label}</span>
          </div>
        )
      })}
    </div>
  )
}

function QueueStatGrid({
  stats,
  ageSpanStatus,
  queueAutoRun,
}: {
  stats?: QueueStats | null
  ageSpanStatus: AgeSpanPipelineStatus | null
  queueAutoRun: boolean
}) {
  const accepted = ageSpanStatus?.accepted_count ?? 0
  const total = ageSpanStatus?.total_steps ?? 0
  return (
    <div className="queue-stat-grid" aria-label="佇列統計">
      <div className={`queue-stat-card${queueAutoRun ? ' is-active' : ''}`}>
        <span className="queue-stat-label">自動流程</span>
        <strong className="queue-stat-value">{queueAutoRun ? '執行中' : '閒置'}</strong>
      </div>
      <div className="queue-stat-card">
        <span className="queue-stat-label">本步待生</span>
        <strong className="queue-stat-value">{stats?.total_pending ?? ageSpanStatus?.pending_count ?? 0}</strong>
      </div>
      <div className="queue-stat-card">
        <span className="queue-stat-label">後續排隊</span>
        <strong className="queue-stat-value">{stats?.total_waiting ?? ageSpanStatus?.waiting_count ?? 0}</strong>
      </div>
      <div className="queue-stat-card">
        <span className="queue-stat-label">已完成</span>
        <strong className="queue-stat-value">
          {stats?.total_ready ?? ageSpanStatus?.accepted_count ?? 0}
        </strong>
      </div>
      <div className={`queue-stat-card${(stats?.total_failed ?? ageSpanStatus?.failed_count ?? 0) > 0 ? ' queue-stat-card--warn' : ''}`}>
        <span className="queue-stat-label">失敗</span>
        <strong className="queue-stat-value">{stats?.total_failed ?? ageSpanStatus?.failed_count ?? 0}</strong>
      </div>
      {total > 0 ? (
        <div className="queue-stat-card queue-stat-card--progress">
          <span className="queue-stat-label">已入庫</span>
          <strong className="queue-stat-value">
            {accepted}/{total}
          </strong>
        </div>
      ) : null}
    </div>
  )
}

function QueuePhaseProgress({
  ageSpanSteps,
}: {
  ageSpanSteps: AgeSpanStep[]
}) {
  const phases: Array<{ key: AgeSpanPhaseTab; label: string; className: string }> = [
    { key: 'face_detail', label: '面部細緻 1–80 歲', className: 'purpose-face-detail' },
    { key: 'tpose', label: 'T 型外觀 1–80 歲', className: 'purpose-tpose' },
  ]
  return (
    <div className="queue-phase-progress">
      {phases.map((phase) => {
        const steps = ageSpanStepsForPhase(ageSpanSteps, phase.key)
        const accepted = countStepsByStatus(steps, 'accepted') + countStepsByStatus(steps, 'ready')
        const pending = countStepsByStatus(steps, 'pending')
        const waiting = countStepsByStatus(steps, 'waiting')
        const failed = countStepsByStatus(steps, 'failed')
        const total = steps.length || 80
        const percent = Math.round((accepted / total) * 100)
        return (
          <div key={phase.key} className="queue-phase-progress-row">
            <div className="queue-phase-progress-header">
              <span className={`pill ${phase.className}`}>{phase.label}</span>
              <span className="queue-phase-progress-count">
                {accepted}/{total} 已入庫
                {pending > 0 ? ` · ${pending} 進行中` : ''}
                {waiting > 0 ? ` · ${waiting} 排隊` : ''}
                {failed > 0 ? ` · ${failed} 失敗` : ''}
              </span>
            </div>
            <div className="pipeline-progress-bar" aria-hidden="true">
              <div className="pipeline-progress-fill" style={{ width: `${Math.min(100, percent)}%` }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function QueueKeyboardHints({ visible }: { visible: boolean }) {
  if (!visible) {
    return null
  }
  return (
    <div className="queue-kbd-hints" aria-label="流程提示">
      <span>系統自動逐筆生圖並入庫，無需手動確認</span>
    </div>
  )
}

function QueueEmptyHero({
  characterName,
  disabled,
  onStart,
}: {
  characterName: string
  disabled: boolean
  onStart: () => void
}) {
  return (
    <div className="queue-empty-hero">
      <div className="queue-empty-hero-copy">
        <strong>為 {characterName} 建立年齡軸</strong>
        <p>
          一鍵排入年齡軸。後端會先連貫生成 1–80 歲面部細緻圖，再生成對應歲數的 T 型外觀；
          <strong>一次只向 AI 請求一張</strong>，完成後自動入庫並接下一筆。
        </p>
        <ul className="queue-empty-hero-list">
          <li>不必逐個按執行或確認入庫</li>
          <li>每一步都以前一步參考圖鎖定身份，避免批次跑壞連貫性</li>
          <li>關掉頁面後，後端 worker 仍會繼續逐步生圖</li>
        </ul>
      </div>
      <button className="primary workflow-cta queue-empty-hero-cta" onClick={onStart} disabled={disabled}>
        建立 1–80 歲年齡軸並自動開始
      </button>
    </div>
  )
}

interface VersionHistoryItem {
  name: string
  path: string
  kind: string
  is_binary: boolean
}

interface VersionBranchItem {
  kind: string
  branch_id: string
  label: string
  updated_at?: string
  status?: string
  review_status?: string
  effective_status?: string
  purpose?: string
  angles?: string[]
  asset_paths?: string[]
  result_url?: string
  job_id?: string
  record_path?: string
  images_index_path?: string
  response_path?: string
  images_by_angle?: Record<string, unknown>
  thumbnail_asset_path?: string
  face_detail_asset_path?: string
  hero_asset_path?: string
  has_face_detail?: boolean
  face_detail_count?: number
  image_count?: number
  purpose_summary?: string
  face_detail_summary?: string
  review_label?: string
  summary?: string
  angles_summary?: string
  prompt?: string
  final_prompt?: string
  revised_prompt?: string
  negative_prompt?: string
  evolution_params?: Record<string, unknown>
  request?: Record<string, unknown>
  response?: Record<string, unknown>
  review?: Record<string, unknown>
  summary_fields?: Record<string, unknown>
  provider?: string
  model?: string
  sort_order?: number
  manifest_path?: string
}

interface CharacterVersionSummary {
  entity_id: string
  current_path: string
  history: VersionHistoryItem[]
  branches: VersionBranchItem[]
}

interface GeneratedImageItem extends ImageRefItem {
  src: string
}

const PREFERRED_ANGLE_ORDER = ['face_detail', 'front', 'three_quarter', 'left', 'right', 'back', 'top', 'bottom']
const STATUS_BADGE_CLASS: Record<string, string> = {
  pending: 'status-badge pending',
  waiting: 'status-badge waiting',
  accepted: 'status-badge accepted',
  rejected: 'status-badge rejected',
  failed: 'status-badge failed',
  ready: 'status-badge ready',
}

function normalizeStatus(value?: string): string {
  return String(value ?? '').trim().toLowerCase()
}

function purposeBadgeClass(value?: string): string {
  const purpose = normalizeStatus(value)
  if (purpose === 'face_detail') return 'pill purpose-face-detail'
  if (purpose === 'tpose') return 'pill purpose-tpose'
  if (purpose === 'age_span') return 'pill purpose-age-span'
  if (purpose === 'identity') return 'pill purpose-identity'
  if (purpose === 'outfit') return 'pill purpose-outfit'
  if (purpose === 'expression') return 'pill purpose-expression'
  if (purpose === 'thumb') return 'pill purpose-thumb'
  return 'pill pill-ghost'
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function safeJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2)
  } catch {
    return String(value)
  }
}

function taskImageGeneration(task: QueueTask): Record<string, unknown> {
  return taskImagePayload(task)
}

function taskReviewStatus(task: QueueTask): string {
  const imageGen = taskImageGeneration(task)
  const review = asRecord(imageGen.review)
  return normalizeStatus(
    String(
      task.review_status ??
        review.status ??
        imageGen.review_status ??
        asRecord(task.result_metadata).review_status ??
        '',
    ),
  )
}

function effectiveTaskStatus(task: QueueTask): string {
  const explicit = normalizeStatus(firstNonEmptyString(task.effective_status))
  if (explicit === 'accepted' || explicit === 'rejected' || explicit === 'failed') {
    return explicit
  }
  const reviewStatus = taskReviewStatus(task)
  if (reviewStatus === 'accepted' || reviewStatus === 'rejected') {
    return reviewStatus
  }
  const queueStatus = normalizeStatus(task.status)
  if (queueStatus === 'ready') {
    return 'accepted'
  }
  return queueStatus || reviewStatus || 'pending'
}

function branchReviewStatus(branch: VersionBranchItem): string {
  const review = asRecord(branch.review)
  const response = asRecord(branch.response)
  const nestedReview = asRecord(response.review)
  return normalizeStatus(
    String(
      branch.review_status ??
        review.status ??
        response.review_status ??
        nestedReview.status ??
        '',
    ),
  )
}

function branchEffectiveStatus(branch: VersionBranchItem): string {
  const explicit = normalizeStatus(firstNonEmptyString(branch.effective_status))
  if (explicit) {
    return explicit
  }
  const reviewStatus = branchReviewStatus(branch)
  if (reviewStatus === 'accepted' || reviewStatus === 'rejected') {
    return reviewStatus
  }
  return normalizeStatus(branch.status) || reviewStatus || 'ready'
}

function serverQueueStatus(status: string): string {
  if (status === 'accepted' || status === 'rejected') {
    return 'ready'
  }
  return status
}

function summarizeText(value: unknown, fallback: string, maxLength = 160): string {
  const text =
    typeof value === 'string'
      ? value.trim()
      : value == null
        ? ''
        : String(value).trim()
  if (!text) {
    return fallback
  }
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text
}

function formatDateTime(value?: string): string {
  if (!value) {
    return '-'
  }
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function purposeLabel(value?: string): string {
  const purpose = String(value ?? '').trim()
  if (!purpose) {
    return 'unknown'
  }
  if (purpose === 'face_detail') return '面部細節'
  if (purpose === 'tpose') return 'T型體'
  if (purpose === 'age_span') return '年齡軸 1–80'
  if (purpose === 'identity') return '身份'
  if (purpose === 'outfit') return '服裝'
  if (purpose === 'expression') return '表情'
  if (purpose === 'thumb') return '縮圖'
  return purpose
}

function branchTypeLabel(kind?: string, purpose?: string): string {
  const normalizedKind = String(kind ?? '').trim()
  if (normalizedKind === 'image_gen') {
    return `生圖分支 / ${purposeLabel(purpose)}`
  }
  return normalizedKind || 'branch'
}

function branchKindBadgeClass(kind?: string): string {
  const normalizedKind = String(kind ?? '').trim().toLowerCase()
  if (normalizedKind === 'image_gen') return 'pill branch-kind-image-gen'
  if (normalizedKind === 'history') return 'pill branch-kind-history'
  return 'pill pill-ghost'
}

function statusLabel(value?: string, reviewStatus?: string): string {
  const status = normalizeStatus(value)
  const review = normalizeStatus(reviewStatus)
  if (status === 'accepted' || review === 'accepted' || status === 'ready') return '已入庫'
  if (status === 'rejected' || review === 'rejected') return '已拒絕'
  if (status === 'failed' || review === 'failed') return '失敗'
  if (status === 'pending') return '等待生成'
  if (status === 'waiting') return '排隊中'
  return status || '未知'
}

function statusBadgeClass(value?: string): string {
  const status = normalizeStatus(value)
  return STATUS_BADGE_CLASS[status] ?? 'status-badge neutral'
}

function statusDisplay(value?: string): string {
  const status = normalizeStatus(value)
  if (!status) {
    return statusLabel(value)
  }
  return `${statusLabel(status)} · ${status}`
}

function branchSummaryFields(branch: VersionBranchItem): Record<string, unknown> {
  return asRecord(branch.summary_fields)
}

function branchPurpose(branch: VersionBranchItem): string {
  const summaryFields = branchSummaryFields(branch)
  return firstNonEmptyString(branch.purpose, branch.purpose_summary, summaryFields.purpose)
}

function branchHeroAssetPath(branch: VersionBranchItem): string {
  const summaryFields = branchSummaryFields(branch)
  return firstNonEmptyString(
    branch.face_detail_asset_path,
    branch.hero_asset_path,
    branch.thumbnail_asset_path,
    summaryFields.face_detail_asset_path,
    summaryFields.hero_asset_path,
    summaryFields.thumbnail_asset_path,
  )
}

function angleSortValue(angle?: string): number {
  const normalized = String(angle ?? '').trim()
  const index = PREFERRED_ANGLE_ORDER.indexOf(normalized)
  return index >= 0 ? index : PREFERRED_ANGLE_ORDER.length + 1
}

function sortAngles(angles: string[]): string[] {
  return [...angles].sort((left, right) => {
    const sortDelta = angleSortValue(left) - angleSortValue(right)
    if (sortDelta !== 0) {
      return sortDelta
    }
    return left.localeCompare(right)
  })
}

function branchSortValue(branch: VersionBranchItem): number {
  const purpose = branchPurpose(branch)
  if (purpose === 'face_detail') {
    return 0
  }
  const angles = branch.angles ?? []
  if (angles.includes('face_detail')) {
    return 1
  }
  if (branchHeroAssetPath(branch) || branch.has_face_detail || (branch.face_detail_count ?? 0) > 0) {
    return 2
  }
  return 3
}

function reviewSortValue(status?: string): number {
  const normalized = normalizeStatus(status)
  if (normalized === 'pending') return 0
  if (normalized === 'ready') return 1
  if (normalized === 'accepted') return 2
  if (normalized === 'rejected') return 3
  if (normalized === 'failed') return 4
  return 5
}

function taskImageRequest(task: QueueTask): Record<string, unknown> {
  return asRecord(asRecord(task.evolution_params)._image_request)
}

function taskPurpose(task: QueueTask): string {
  const imageGen = taskImageGeneration(task)
  const imageRequest = taskImageRequest(task)
  return firstNonEmptyString(
    task.purpose,
    asRecord(task.result_metadata).purpose,
    imageGen.purpose,
    imageRequest.purpose,
  )
}

function taskAge(task: QueueTask): string {
  const params = asRecord(task.evolution_params)
  const imageRequest = taskImageRequest(task)
  const age = params.age_override ?? imageRequest.age
  return age == null || String(age).trim() === '' ? '' : String(age)
}

function branchSummary(branch: VersionBranchItem): string {
  const summaryFields = branchSummaryFields(branch)
  const parts: string[] = []
  const purpose = branchPurpose(branch)
  if (purpose) {
    parts.push(`${purposeLabel(purpose)} 分支`)
  }
  const faceDetailSummary = firstNonEmptyString(
    branch.face_detail_summary,
    String(summaryFields.face_detail_summary ?? ''),
  )
  if (faceDetailSummary) {
    parts.push(faceDetailSummary)
  }
  const sortedAngles = sortAngles((branch.angles ?? []).map((item) => String(item)))
  if (sortedAngles.length) {
    parts.push(sortedAngles.join(', '))
  }
  if (branch.image_count != null) {
    parts.push(`${branch.image_count} 張圖`)
  } else if (branch.asset_paths?.length) {
    parts.push(`${branch.asset_paths.length} 張圖`)
  }
  const reviewLabel = firstNonEmptyString(
    branch.review_label,
    String(summaryFields.review_label ?? ''),
    branch.review_status,
  )
  if (reviewLabel) {
    parts.push(reviewStatusLabelFromStatus(reviewLabel) ?? reviewLabel)
  }
  if (parts.length) {
    return parts.join(' · ')
  }
  const fallback = firstNonEmptyString(branch.summary, summaryFields.summary, summaryFields.status_summary)
  return summarizeText(fallback, '尚無額外摘要', 180)
}

function branchMetaSummary(branch: VersionBranchItem): string {
  const parts: string[] = []
  if (branch.effective_status || branch.review_status || branch.status) {
    parts.push(statusDisplay(branchEffectiveStatus(branch)))
  }
  if (branch.job_id) {
    parts.push(`job ${String(branch.job_id).slice(0, 8)}`)
  }
  if (branch.image_count != null) {
    parts.push(`${branch.image_count} 張`)
  } else if (branch.asset_paths?.length) {
    parts.push(`${branch.asset_paths.length} 張`)
  }
  if (branch.result_url) {
    parts.push('有結果')
  }
  return parts.join(' · ') || '等待更多分支資料'
}

function branchShortSummary(branch: VersionBranchItem): string {
  const parts = [branchTypeLabel(branch.kind, branch.purpose), branchSummary(branch), branchMetaSummary(branch)].filter(Boolean)
  return summarizeText(parts.join(' · '), '等待更多分支資料', 180)
}

function branchOverviewLines(branch: VersionBranchItem, branchStatus: string, branchAngles: string[]): string[] {
  const purpose = branchPurpose(branch)
  return [
    purpose ? `${purposeLabel(purpose)} 分支` : '',
    branchTypeLabel(branch.kind, purpose),
    branchAngles.length ? `角度 ${branchAngles.join(', ')}` : '',
    branch.image_count != null
      ? `${branch.image_count} 張圖片`
      : branch.asset_paths?.length
        ? `${branch.asset_paths.length} 張圖片`
        : '',
    `狀態 ${statusLabel(branchStatus, branchReviewStatus(branch))}`,
  ].filter(Boolean)
}

function responseSummary(task: QueueTask): string {
  const imageGen = taskImageGeneration(task)
  const reviewStatus = taskReviewStatus(task)
  const provider = firstNonEmptyString(imageGen.provider)
  const model = firstNonEmptyString(imageGen.model)
  const purpose = firstNonEmptyString(taskTopLevelString(task, 'purpose'), imageGen.purpose)
  const imageCount =
    task.image_count ??
    (taskDetailImages('', task).length || queueImageCollections(imageGen, reviewStatus).length)
  const faceDetailCount = task.face_detail_count ?? 0
  const parts = [
    purpose ? `用途 ${purpose}` : '',
    faceDetailCount > 0 || task.has_face_detail ? `face_detail 優先 · ${faceDetailCount || 1} 張` : '',
    provider ? `provider ${provider}` : '',
    model ? `model ${model}` : '',
    imageCount ? `${imageCount} 張輸出` : '',
  ].filter(Boolean)
  return parts.join(' · ') || '目前沒有回應摘要'
}

function parseAnglesSummary(value?: string): string[] {
  return String(value ?? '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function detailImageGroups(images: TaskImageDetail[]): { faceDetail: TaskImageDetail[]; otherAngles: TaskImageDetail[] } {
  return {
    faceDetail: images.filter((item) => item.angle === 'face_detail'),
    otherAngles: images.filter((item) => item.angle !== 'face_detail'),
  }
}

function taskDetailImages(apiBase: string, task: QueueTask): TaskImageDetail[] {
  const imageGen = taskImagePayload(task)
  const reviewStatus = taskReviewStatus(task)
  const bucket = new Map<string, TaskImageDetail>()

  const registerImage = (source: unknown, forcedAngle?: string) => {
    const item = asRecord(source)
    const assetPath = previewAssetPath(item, reviewStatus)
    const rawUrl = imageRemoteUrl(item)
    if (!assetPath && !rawUrl) {
      return
    }
    const angle = String(forcedAngle ?? item.angle ?? '').trim() || undefined
    const key = `${assetPath || rawUrl}::${angle || ''}`
    if (bucket.has(key)) {
      return
    }
    bucket.set(key, {
      path: assetPath,
      uri: rawUrl || undefined,
      angle,
      note: String(imageGen.purpose ?? 'identity'),
      src: assetPath ? assetUrlFromPath(apiBase, task.core_id, assetPath) : rawUrl,
      summary: imageSummary(item),
    })
  }

  for (const image of mergedQueueImages(imageGen, reviewStatus)) {
    registerImage(image)
  }

  return [...bucket.values()].sort((left, right) => {
    const sortDelta = angleSortValue(left.angle) - angleSortValue(right.angle)
    if (sortDelta !== 0) {
      return sortDelta
    }
    return String(left.path || left.uri).localeCompare(String(right.path || right.uri))
  })
}

function taskHeroImage(apiBase: string, task: QueueTask, detailImages: TaskImageDetail[]): TaskImageDetail | null {
  const firstFaceDetail = detailImages.find((item) => item.angle === 'face_detail')
  if (firstFaceDetail) {
    return firstFaceDetail
  }
  const imageGen = taskImagePayload(task)
  const faceDetailAssetPath = String(
    firstNonEmptyString(
      task.face_detail_asset_path,
      imageGen.face_detail_asset_path,
      asRecord(task.result_metadata).face_detail_asset_path,
    ),
  ).trim()
  if (!faceDetailAssetPath) {
    return null
  }
  return {
    path: faceDetailAssetPath,
    angle: 'face_detail',
    note: String(imageGen.purpose ?? 'identity'),
    src: assetUrlFromPath(apiBase, task.core_id, faceDetailAssetPath),
  }
}

function taskThumbnailSrc(
  apiBase: string,
  task: QueueTask,
  detailImages: TaskImageDetail[],
  fallbackSummary?: CharacterSummary,
): string {
  const imageGen = taskImagePayload(task)
  const taskPreview = taskPreviewMetadata(task)
  const reviewStatus = taskReviewStatus(task)
  const thumbnailAssetPath = firstNonEmptyString(
    taskPreview.face_detail_asset_path,
    taskPreview.thumbnail_asset_path,
    task.face_detail_asset_path,
    task.thumbnail_asset_path,
    task.representative_asset_path,
    imageGen.face_detail_asset_path,
    imageGen.thumbnail_asset_path,
    previewAssetPath(asRecord(imageGen.thumbnail_image), reviewStatus),
    detailImages[0]?.path,
    asRecord(fallbackSummary?.metadata).face_detail_asset_path,
    asRecord(fallbackSummary?.metadata).thumbnail_asset_path,
  )
  return thumbnailAssetPath ? assetUrlFromPath(apiBase, task.core_id, thumbnailAssetPath) : ''
}

function branchHeroImage(apiBase: string, characterId: string, branch: VersionBranchItem, detailImages: TaskImageDetail[]): TaskImageDetail | null {
  const firstFaceDetail = detailImages.find((item) => item.angle === 'face_detail')
  if (firstFaceDetail) {
    return firstFaceDetail
  }
  const heroPath = branchHeroAssetPath(branch)
  if (!heroPath) {
    return null
  }
  return {
    path: heroPath,
    angle: heroPath === firstNonEmptyString(branch.face_detail_asset_path, String(branchSummaryFields(branch).face_detail_asset_path ?? '')) ? 'face_detail' : undefined,
    note: branchPurpose(branch) || branch.kind,
    src: assetUrlFromPath(apiBase, characterId, heroPath),
  }
}

function branchDetailImages(apiBase: string, characterId: string, branch: VersionBranchItem): TaskImageDetail[] {
  const imagesByAngle = asRecord(branch.images_by_angle)
  const reviewStatus = branchReviewStatus(branch)
  const bucket = new Map<string, TaskImageDetail>()

  const registerImage = (source: unknown, forcedAngle?: string) => {
    const item = asRecord(source)
    const assetPath = previewAssetPath(item, reviewStatus)
    if (!assetPath) {
      return
    }
    const angle = String(forcedAngle ?? item.angle ?? '').trim() || undefined
    const key = `${assetPath}::${angle || ''}`
    if (bucket.has(key)) {
      return
    }
    bucket.set(key, {
      path: assetPath,
      angle,
      note: branchPurpose(branch) || branch.kind,
      src: assetUrlFromPath(apiBase, characterId, assetPath),
      summary: imageSummary(item, 72),
    })
  }

  for (const [angle, value] of Object.entries(imagesByAngle)) {
    for (const image of asArray(value)) {
      registerImage(image, angle)
    }
  }
  for (const assetPath of branch.asset_paths ?? []) {
    const normalized = String(assetPath).trim()
    if (!normalized) {
      continue
    }
    registerImage({ asset_path: normalized }, normalized === branch.face_detail_asset_path ? 'face_detail' : undefined)
  }
  if (branch.face_detail_asset_path) {
    registerImage({ asset_path: branch.face_detail_asset_path }, 'face_detail')
  }
  const fallbackHeroAssetPath = firstNonEmptyString(branch.hero_asset_path, String(branchSummaryFields(branch).hero_asset_path ?? ''))
  if (fallbackHeroAssetPath) {
    registerImage({ asset_path: fallbackHeroAssetPath }, fallbackHeroAssetPath === branch.face_detail_asset_path ? 'face_detail' : undefined)
  }

  return [...bucket.values()].sort((left, right) => {
    const sortDelta = angleSortValue(left.angle) - angleSortValue(right.angle)
    if (sortDelta !== 0) {
      return sortDelta
    }
    return String(left.path).localeCompare(String(right.path))
  })
}

function branchDetailSections(branch: VersionBranchItem, detailImages: TaskImageDetail[]): string[] {
  const sections: string[] = []
  if (detailImages.some((item) => item.angle === 'face_detail')) sections.push('face_detail')
  if (detailImages.some((item) => item.angle !== 'face_detail')) sections.push('angles')
  if (branchPromptText(branch)) sections.push('Prompt')
  if (branchNegativePromptText(branch)) sections.push('Negative')
  if (Object.keys(branchEvolutionParams(branch)).length) sections.push('參數')
  if (branch.asset_paths?.length) sections.push('資產')
  if (branch.result_url) sections.push('結果')
  return sections
}

function branchPromptText(branch: VersionBranchItem): string {
  const rawBranch = asRecord(branch as unknown)
  const request = asRecord(rawBranch.request)
  const response = asRecord(rawBranch.response)
  const summaryFields = branchSummaryFields(branch)
  return firstNonEmptyString(
    branch.prompt,
    branch.final_prompt,
    branch.revised_prompt,
    summaryFields.prompt,
    summaryFields.final_prompt,
    summaryFields.revised_prompt,
    request.prompt,
    request.final_prompt,
    request.revised_prompt,
    response.prompt,
    response.final_prompt,
    response.revised_prompt,
  )
}

function branchNegativePromptText(branch: VersionBranchItem): string {
  const rawBranch = asRecord(branch as unknown)
  const request = asRecord(rawBranch.request)
  const response = asRecord(rawBranch.response)
  const summaryFields = branchSummaryFields(branch)
  return firstNonEmptyString(
    branch.negative_prompt,
    summaryFields.negative_prompt,
    request.negative_prompt,
    response.negative_prompt,
  )
}

function branchEvolutionParams(branch: VersionBranchItem): Record<string, unknown> {
  const rawBranch = asRecord(branch as unknown)
  const request = asRecord(rawBranch.request)
  const response = asRecord(rawBranch.response)
  const summaryFields = branchSummaryFields(branch)
  const candidates = [
    branch.evolution_params,
    asRecord(summaryFields.evolution_params),
    asRecord(summaryFields.params),
    asRecord(rawBranch.params),
    asRecord(rawBranch.request_params),
    asRecord(request.evolution_params),
    asRecord(request.params),
    asRecord(response.evolution_params),
    asRecord(response.params),
  ]
  for (const candidate of candidates) {
    const record = asRecord(candidate)
    if (Object.keys(record).length) {
      return record
    }
  }
  return {}
}

function deriveAngles(candidates: Array<string | undefined | null>): string[] {
  const unique = new Set<string>()
  for (const value of candidates) {
    const normalized = String(value ?? '').trim()
    if (normalized) {
      unique.add(normalized)
    }
  }
  return sortAngles([...unique])
}

function branchAngleList(branch: VersionBranchItem, detailImages: TaskImageDetail[]): string[] {
  const summaryFields = branchSummaryFields(branch)
  return deriveAngles([
    ...(branch.angles ?? []).map((item) => String(item)),
    ...parseAnglesSummary(branch.angles_summary),
    ...parseAnglesSummary(String(summaryFields.angles_summary ?? '')),
    ...detailImages.map((item) => item.angle),
  ])
}

function branchThumbnailSrc(
  apiBase: string,
  characterId: string,
  branch: VersionBranchItem,
  branchHero: TaskImageDetail | null,
  branchImages: TaskImageDetail[],
): string {
  const thumbnailPath = firstNonEmptyString(
    branch.face_detail_asset_path,
    branch.hero_asset_path,
    branch.thumbnail_asset_path,
    String(branchSummaryFields(branch).face_detail_asset_path ?? ''),
    String(branchSummaryFields(branch).hero_asset_path ?? ''),
    String(branchSummaryFields(branch).thumbnail_asset_path ?? ''),
    branchHero?.path,
    branchImages[0]?.path,
  )
  if (thumbnailPath) {
    return assetUrlFromPath(apiBase, characterId, thumbnailPath)
  }
  return branchHero?.src ?? ''
}

function asImageRefList(value: unknown): ImageRefItem[] {
  return asArray(value)
    .map((item) => asRecord(item))
    .map((item) => ({
      path: String(item.path ?? '').trim(),
      uri: String(item.uri ?? '').trim() || undefined,
      angle: String(item.angle ?? '').trim() || undefined,
      note: String(item.note ?? '').trim() || undefined,
    }))
    .filter((item) => item.path || item.uri)
}

function ageSpanBucketItems(draft: Record<string, unknown>, bucket: 'faces' | 'tposes'): ImageRefItem[] {
  const imageGen = asRecord(asRecord(draft._extensions).image_gen)
  const ageSpan = asRecord(imageGen.age_span)
  const bucketData = asRecord(ageSpan[bucket])
  const ages = Object.keys(bucketData).sort((left, right) => Number(left) - Number(right))
  const items: ImageRefItem[] = []
  for (const age of ages) {
    for (const raw of asArray(bucketData[age])) {
      const item = asRecord(raw)
      const path = String(item.path ?? '').trim()
      const uri = String(item.uri ?? '').trim()
      if (!path && !uri) {
        continue
      }
      items.push({
        path,
        uri: uri || undefined,
        angle: String(item.angle ?? bucket).trim() || bucket,
        note: `${age} 歲`,
      })
    }
  }
  return items
}

function assetUrl(apiBase: string, characterId: string, item: ImageRefItem): string {
  if (item.uri && /^https?:\/\//i.test(item.uri)) {
    return item.uri
  }
  const source = item.path || item.uri || ''
  const cleanPath = source.replace(/^\/+/, '')
  return `${apiBase}/api/v1/characters/${characterId}/assets/${cleanPath}`
}

function assetUrlFromPath(apiBase: string, characterId: string | number, assetPath: string): string {
  const cleanPath = String(assetPath || '').replace(/^\/+/, '')
  return `${apiBase}/api/v1/characters/${characterId}/assets/${cleanPath}`
}

function taskWorkflowLabel(task: QueueTask): string {
  const queueStatus = normalizeStatus(task.status)
  const effectiveStatus = effectiveTaskStatus(task)
  const reviewStatus = taskReviewStatus(task)
  if (queueStatus === 'failed' || effectiveStatus === 'failed') {
    return '生成失敗'
  }
  if (reviewStatus === 'accepted' || effectiveStatus === 'accepted' || queueStatus === 'ready') {
    return reviewStatusLabelFromStatus('accepted') ?? '已入庫'
  }
  if (reviewStatus === 'rejected' || effectiveStatus === 'rejected') {
    return reviewStatusLabelFromStatus('rejected') ?? '已拒絕'
  }
  if (queueStatus === 'waiting' || effectiveStatus === 'waiting') {
    return '排隊中'
  }
  if (queueStatus === 'pending' || effectiveStatus === 'pending') {
    return '等待生成'
  }
  return statusLabel(effectiveStatus)
}

function taskWorkflowHint(task: QueueTask): string {
  const queueStatus = normalizeStatus(task.status)
  const effectiveStatus = effectiveTaskStatus(task)
  const reviewStatus = taskReviewStatus(task)
  if (queueStatus === 'failed' || effectiveStatus === 'failed') {
    return '後端處理失敗，可先檢查錯誤訊息與參數。'
  }
  if (reviewStatus === 'accepted' || effectiveStatus === 'accepted' || queueStatus === 'ready') {
    return '生圖已完成並自動寫入角色護照。'
  }
  if (reviewStatus === 'rejected' || effectiveStatus === 'rejected') {
    return '這批圖片被標記為拒絕，不會寫回角色護照。'
  }
  if (queueStatus === 'waiting' || effectiveStatus === 'waiting') {
    return '前置步驟完成並入庫後，系統會自動開放這一步。'
  }
  if (queueStatus === 'pending' || effectiveStatus === 'pending') {
    return '這是目前唯一開放的步驟；完成後會自動接下一筆。'
  }
  return '目前無需額外操作。'
}

function branchWorkflowLabel(branch: VersionBranchItem): string {
  const effectiveStatus = branchEffectiveStatus(branch)
  const reviewStatus = branchReviewStatus(branch) || normalizeStatus(branch.review_status)
  if (effectiveStatus === 'failed') {
    return '分支生成失敗'
  }
  if (reviewStatus === 'accepted' || effectiveStatus === 'accepted' || effectiveStatus === 'ready') {
    return reviewStatusLabelFromStatus('accepted') ?? '已入庫'
  }
  if (reviewStatus === 'rejected' || effectiveStatus === 'rejected') {
    return reviewStatusLabelFromStatus('rejected') ?? '已拒絕'
  }
  if (effectiveStatus === 'pending') {
    return '等待生成'
  }
  return statusLabel(effectiveStatus)
}

function branchWorkflowHint(branch: VersionBranchItem): string {
  const effectiveStatus = branchEffectiveStatus(branch)
  const reviewStatus = branchReviewStatus(branch) || normalizeStatus(branch.review_status)
  if (effectiveStatus === 'failed') {
    return '分支生成失敗，可回頭檢查輸出與後端記錄。'
  }
  if (reviewStatus === 'accepted' || effectiveStatus === 'accepted' || effectiveStatus === 'ready') {
    return '這個分支已自動寫入，可視為目前有效結果。'
  }
  if (reviewStatus === 'rejected' || effectiveStatus === 'rejected') {
    return '這個分支已被標記拒絕，保留作記錄但不建議採用。'
  }
  if (effectiveStatus === 'pending') {
    return '分支仍在等待後端生成，尚未產出可檢視圖片。'
  }
  return '目前無需額外操作。'
}

function entityCharpass(entity: CharacterCard): Record<string, unknown> {
  return asRecord(asRecord(entity.payload).charpass)
}

function charpassImageMetadata(charpass: Record<string, unknown>): Record<string, string> {
  const meta = asRecord(charpass._meta)
  const identity = asRecord(charpass._identity)
  const refs = asImageRefList(identity.ref_images)
  const faceDetail = refs.find((item) => item.angle === 'face_detail')
  const thumbnail =
    String(meta.thumbnail ?? '').trim() ||
    String(faceDetail?.path ?? '').trim() ||
    String(refs[0]?.path ?? '').trim()

  const result: Record<string, string> = {}
  if (thumbnail) {
    result.thumbnail_asset_path = thumbnail
  }
  if (faceDetail?.path) {
    result.face_detail_asset_path = faceDetail.path
  }
  return result
}

function payloadThumbnailItem(entity: CharacterCard): ImageRefItem | null {
  const payload = asRecord(entity.payload)
  const faceDetail = String(payload.face_detail_asset_path ?? '').trim()
  if (faceDetail) {
    return { path: faceDetail, note: 'face_detail' }
  }
  const thumbnail = String(payload.thumbnail_asset_path ?? '').trim()
  if (thumbnail) {
    return { path: thumbnail, note: 'thumbnail' }
  }
  return null
}

function findThumbnailItem(charpass: Record<string, unknown>): ImageRefItem | null {
  const meta = asRecord(charpass._meta)
  const identity = asRecord(charpass._identity)
  const identityRefs = asImageRefList(identity.ref_images)
  const directThumb = String(meta.thumbnail ?? '').trim()
  if (directThumb) {
    return { path: directThumb, note: 'thumbnail' }
  }
  const preferredAngles = ['face_detail', 'front', 'three_quarter', 'left', 'right', 'back', 'top', 'bottom']
  for (const angle of preferredAngles) {
    const match = identityRefs.find((item) => item.angle === angle)
    if (match) {
      return match
    }
  }
  return identityRefs[0] ?? null
}

function characterThumbnail(
  apiBase: string,
  entity: CharacterCard,
  summary?: CharacterSummary,
): CharacterThumbnail | null {
  const summaryMetadata = asRecord(summary?.metadata)
  const summaryFaceDetail = String(summaryMetadata.face_detail_asset_path ?? '').trim()
  if (summaryFaceDetail) {
    return {
      src: assetUrlFromPath(apiBase, entity.id, summaryFaceDetail),
      label: 'face_detail',
    }
  }
  const summaryThumb = String(summaryMetadata.thumbnail_asset_path ?? '').trim()
  if (summaryThumb) {
    return {
      src: assetUrlFromPath(apiBase, entity.id, summaryThumb),
      label: 'thumbnail',
    }
  }
  const payloadThumb = payloadThumbnailItem(entity)
  if (payloadThumb) {
    return {
      src: assetUrl(apiBase, entity.id, payloadThumb),
      label: payloadThumb.note || 'thumbnail',
    }
  }
  const charpass = entityCharpass(entity)
  if (!Object.keys(charpass).length) {
    return null
  }
  const item = findThumbnailItem(charpass)
  if (!item) {
    return null
  }
  return {
    src: assetUrl(apiBase, entity.id, item),
    label: item.angle || item.note || 'thumbnail',
  }
}

function nestedNumber(source: Record<string, unknown>, layer: string, key: string, fallback: number): number {
  const raw = asRecord(source[layer])[key]
  return typeof raw === 'number' ? raw : fallback
}

function setNestedNumber(
  source: Record<string, unknown>,
  layer: string,
  key: string,
  value: number,
): Record<string, unknown> {
  return {
    ...source,
    [layer]: {
      ...asRecord(source[layer]),
      [key]: value,
    },
  }
}

interface CharpassPanelProps {
  apiBase: string
  projectId?: string
  persist: boolean
  characters: CharacterCard[]
  selectedCharacter?: CharacterCard
  onSelect: (id: string) => void
  onPatchEntity: (entityId: string, charpass: Record<string, unknown>, extra?: Record<string, unknown>) => void
  onError: (message: string | null) => void
}

export function CharpassPanel(props: CharpassPanelProps) {
  const { apiBase, projectId, persist, characters, selectedCharacter, onSelect, onPatchEntity, onError } = props
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const [characterSummaries, setCharacterSummaries] = useState<Record<string, CharacterSummary>>({})
  const [queueData, setQueueData] = useState<QueueTaskListResponse | null>(null)
  const [versionSummary, setVersionSummary] = useState<CharacterVersionSummary | null>(null)
  const [queueBusy, setQueueBusy] = useState(false)
  const [imageBusy, setImageBusy] = useState(false)
  const [lastGeneratedPrompt, setLastGeneratedPrompt] = useState('')
  const [purpose, setPurpose] = useState('age_span')
  const [provider, setProvider] = useState('wan')
  const [model, setModel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [extraPrompt, setExtraPrompt] = useState('')
  const [queueStatusFilter, setQueueStatusFilter] = useState('')
  const [queueOnlySelected, setQueueOnlySelected] = useState(true)
  const [queueAutoRun, setQueueAutoRun] = useState(false)
  const [workerStatus, setWorkerStatus] = useState<QueueWorkerStatus | null>(null)
  const [ageSpanStatus, setAgeSpanStatus] = useState<AgeSpanPipelineStatus | null>(null)
  const [pipelineMessage, setPipelineMessage] = useState<string | null>(null)
  const [showFullTaskList, setShowFullTaskList] = useState(false)
  const [showQueueForm, setShowQueueForm] = useState(false)
  const [ageSpanPhaseTab, setAgeSpanPhaseTab] = useState<AgeSpanPhaseTab>('face_detail')
  const [pinnedTaskId, setPinnedTaskId] = useState<number | null>(null)
  const [autoContinue, setAutoContinue] = useState(() => {
    try {
      const stored = localStorage.getItem(AUTO_CONTINUE_STORAGE_KEY)
      return stored == null ? true : stored === '1'
    } catch {
      return true
    }
  })
  const queueAutoRunRef = useRef(false)
  const autoResumeAttemptedRef = useRef(false)
  const focusTaskRef = useRef<QueueTask | null>(null)
  const [layer, setLayer] = useState<CharpassLayer>('_identity')
  const [conflictStrategy, setConflictStrategy] = useState<ConflictStrategy>('merge')
  const [focused, setFocused] = useState(false)
  const [busy, setBusy] = useState(false)
  const importInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    queueAutoRunRef.current = queueAutoRun
  }, [queueAutoRun])

  function setAutoContinueEnabled(enabled: boolean) {
    setAutoContinue(enabled)
    try {
      localStorage.setItem(AUTO_CONTINUE_STORAGE_KEY, enabled ? '1' : '0')
    } catch {
      // ignore storage failures
    }
  }

  function queueCoreIdParam(): string | null {
    if (!queueOnlySelected || !selectedCharacter?.id) {
      return null
    }
    return selectedCharacter.id
  }

  const loadCharacterSummaries = useCallback(async () => {
    const response = await fetch(`${apiBase}/api/v1/characters?limit=100`)
    if (!response.ok) {
      throw new Error((await response.text()) || `HTTP ${response.status}`)
    }
    const body = (await response.json()) as Array<Record<string, unknown>>
    if (!Array.isArray(body)) {
      return
    }
    const next: Record<string, CharacterSummary> = {}
    for (const item of body) {
      const id = String(item.id ?? '').trim()
      if (!id) {
        continue
      }
      next[id] = {
        id,
        name: String(item.name ?? '').trim() || undefined,
        metadata: asRecord(item.metadata),
      }
    }
    setCharacterSummaries(next)
  }, [apiBase])

  const patchCharacterSummaryFromCharpass = useCallback(
    (characterId: string, charpass: Record<string, unknown>) => {
      const metadataPatch = charpassImageMetadata(charpass)
      const fallbackName =
        String(asRecord(charpass._identity).name ?? '').trim() ||
        String(asRecord(charpass._meta).character_name ?? '').trim() ||
        undefined
      setCharacterSummaries((prev) => ({
        ...prev,
        [characterId]: {
          id: characterId,
          name: prev[characterId]?.name || fallbackName,
          metadata: {
            ...asRecord(prev[characterId]?.metadata),
            ...metadataPatch,
          },
        },
      }))
    },
    [],
  )

  const patchCharacterSummariesFromTasks = useCallback((tasks: QueueTask[]) => {
    const previewSummaries = mergeTaskPreviewSummaries(tasks)
    if (!Object.keys(previewSummaries).length) {
      return
    }
    setCharacterSummaries((prev) => {
      const next = { ...prev }
      for (const [characterId, summary] of Object.entries(previewSummaries)) {
        next[characterId] = {
          id: characterId,
          name: summary.name || prev[characterId]?.name,
          metadata: {
            ...asRecord(prev[characterId]?.metadata),
            ...asRecord(summary.metadata),
          },
        }
      }
      return next
    })
  }, [])

  useEffect(() => {
    if (!selectedCharacter) {
      setDraft({})
      setVersionSummary(null)
      return
    }
    const local = entityCharpass(selectedCharacter)
    setDraft(local)
    if (!persist) {
      return
    }
    let cancelled = false
    Promise.all([
      fetch(`${apiBase}/api/v1/characters/${selectedCharacter.id}/charpass`),
      fetch(`${apiBase}/api/v1/characters/${selectedCharacter.id}/versions`),
    ])
      .then(async ([charpassResponse, versionResponse]) => {
        if (charpassResponse.ok) {
          const body = (await charpassResponse.json()) as { charpass?: Record<string, unknown> }
          if (!cancelled && body.charpass) {
            setDraft(body.charpass)
            patchCharacterSummaryFromCharpass(selectedCharacter.id, body.charpass)
          }
        }
        if (versionResponse.ok) {
          const body = (await versionResponse.json()) as CharacterVersionSummary
          if (!cancelled) {
            setVersionSummary(body)
          }
        }
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [apiBase, persist, selectedCharacter?.id])

  useEffect(() => {
    void loadCharacterSummaries().catch(() => undefined)
  }, [loadCharacterSummaries, characters.length])

  async function reloadCharacterCharpass(characterId: string) {
    const [charpassResponse, versionResponse] = await Promise.all([
      fetch(`${apiBase}/api/v1/characters/${characterId}/charpass`),
      fetch(`${apiBase}/api/v1/characters/${characterId}/versions`),
    ])
    if (!charpassResponse.ok) {
      throw new Error((await charpassResponse.text()) || `HTTP ${charpassResponse.status}`)
    }
    const body = (await charpassResponse.json()) as { charpass?: Record<string, unknown> }
    const next = body.charpass ?? {}
    setDraft(next)
    patchCharacterSummaryFromCharpass(characterId, next)
    onPatchEntity(characterId, next)
    if (versionResponse.ok) {
      const versionBody = (await versionResponse.json()) as CharacterVersionSummary
      setVersionSummary(versionBody)
    }
  }

  async function loadQueueTasks(options?: { keepError?: boolean }) {
    setQueueBusy(true)
    if (!options?.keepError) {
      onError(null)
    }
    try {
      const params = new URLSearchParams()
      params.set('limit', '400')
      if (queueStatusFilter) {
        params.set('status', serverQueueStatus(normalizeStatus(queueStatusFilter)))
      }
      if (queueOnlySelected && selectedCharacter?.id) {
        params.set('core_id', selectedCharacter.id)
      }
      const response = await fetch(`${apiBase}/api/v1/admin/queue-tasks?${params.toString()}`)
      if (!response.ok) {
        throw new Error((await response.text()) || `HTTP ${response.status}`)
      }
      const body = (await response.json()) as QueueTaskListResponse
      setQueueData(body)
      patchCharacterSummariesFromTasks(body.tasks ?? [])
      const latestWithPrompt = (body.tasks || []).find((task) => {
        const imageGen = asRecord(asRecord(task.result_metadata).image_generation)
        return typeof imageGen.prompt === 'string' && imageGen.prompt.trim()
      })
      if (latestWithPrompt) {
        setLastGeneratedPrompt(String(asRecord(asRecord(latestWithPrompt.result_metadata).image_generation).prompt))
      }
      await loadAgeSpanStatus()
      await loadWorkerStatus()
    } catch (queueError) {
      onError(queueError instanceof Error ? queueError.message : '載入佇列失敗')
    } finally {
      setQueueBusy(false)
    }
  }

  async function loadAgeSpanStatus(): Promise<AgeSpanPipelineStatus | null> {
    const coreId = queueCoreIdParam()
    const params = new URLSearchParams()
    if (coreId) {
      params.set('core_id', coreId)
    }
    try {
      const response = await fetch(`${apiBase}/api/v1/admin/queue-tasks/age-span-status?${params.toString()}`)
      if (response.status === 404) {
        setAgeSpanStatus(null)
        return null
      }
      if (!response.ok) {
        return null
      }
      const body = (await response.json()) as AgeSpanPipelineStatus
      setAgeSpanStatus(body)
      return body
    } catch {
      setAgeSpanStatus(null)
      return null
    }
  }

  async function loadWorkerStatus(): Promise<QueueWorkerStatus | null> {
    try {
      const response = await fetch(`${apiBase}/api/v1/admin/queue-worker`)
      if (!response.ok) {
        return null
      }
      const body = (await response.json()) as QueueWorkerStatus
      setWorkerStatus(body)
      setQueueAutoRun(Boolean(body.auto_run || body.busy))
      queueAutoRunRef.current = Boolean(body.auto_run || body.busy)
      return body
    } catch {
      return null
    }
  }

  async function resetFailedTasks(fromId?: number): Promise<number> {
    onError(null)
    try {
      const params = new URLSearchParams()
      const coreId = queueCoreIdParam()
      if (coreId) {
        params.set('core_id', coreId)
      }
      if (fromId && fromId > 0) {
        params.set('from_id', String(fromId))
      }
      const response = await fetch(`${apiBase}/api/v1/admin/queue-tasks/reset-failed?${params.toString()}`, {
        method: 'POST',
      })
      if (!response.ok) {
        throw new Error((await response.text()) || `HTTP ${response.status}`)
      }
      const body = (await response.json()) as { reset?: number }
      await loadQueueTasks({ keepError: true })
      return Number(body.reset ?? 0)
    } catch (taskError) {
      onError(taskError instanceof Error ? taskError.message : '重設 failed 任務失敗')
      return 0
    }
  }

  async function startAutoPipeline(options?: { resetFailed?: boolean; fromId?: number }) {
    onError(null)
    try {
      if (options?.resetFailed) {
        const resetCount = await resetFailedTasks(options.fromId)
        if (resetCount > 0) {
          setPipelineMessage(`已重設 ${resetCount} 筆失敗任務，後端繼續逐步生圖…`)
        }
      }
      const response = await fetch(`${apiBase}/api/v1/admin/queue-worker/start`, { method: 'POST' })
      if (!response.ok) {
        throw new Error((await response.text()) || `HTTP ${response.status}`)
      }
      const body = (await response.json()) as QueueWorkerStatus
      setWorkerStatus(body)
      setQueueAutoRun(true)
      queueAutoRunRef.current = true
      setPipelineMessage('後端正在逐步生圖：一次一張，完成後自動入庫並接下一筆。')
      await loadQueueTasks({ keepError: true })
    } catch (taskError) {
      onError(taskError instanceof Error ? taskError.message : '啟動自動生圖失敗')
    }
  }

  async function stopAutoPipeline() {
    try {
      const response = await fetch(`${apiBase}/api/v1/admin/queue-worker/pause`, { method: 'POST' })
      if (response.ok) {
        const body = (await response.json()) as QueueWorkerStatus
        setWorkerStatus(body)
      }
    } catch {
      // ignore
    }
    setQueueAutoRun(false)
    queueAutoRunRef.current = false
    setPipelineMessage('已暫停後端 worker。目前正在生成的那一張仍會跑完。')
  }

  useEffect(() => {
    void loadQueueTasks({ keepError: true })
  }, [apiBase, selectedCharacter?.id, queueStatusFilter, queueOnlySelected])

  useEffect(() => {
    const shouldPoll = queueAutoRun || Boolean(ageSpanStatus?.has_open_pipeline)
    if (!shouldPoll) {
      return
    }
    const timer = window.setInterval(() => {
      void loadQueueTasks({ keepError: true })
    }, 4000)
    return () => window.clearInterval(timer)
  }, [queueAutoRun, ageSpanStatus?.has_open_pipeline, apiBase, selectedCharacter?.id, queueStatusFilter, queueOnlySelected])

  useEffect(() => {
    if (!selectedCharacter?.id || !workerStatus?.last_task_id) {
      return
    }
    if (workerStatus.last_status === 'ready' || workerStatus.last_status === 'failed') {
      void reloadCharacterCharpass(selectedCharacter.id)
      void loadCharacterSummaries()
    }
  }, [selectedCharacter?.id, workerStatus?.last_task_id, workerStatus?.last_status])

  const sliderValues = useMemo(
    () => ({
      ipAdapter: nestedNumber(draft, '_style', 'ip_adapter_weight', 0.7),
      gender: nestedNumber(draft, '_identity', 'gender_spectrum', 0.5),
      face: nestedNumber(draft, '_identity', 'face_threshold', 0.7),
      tilt: nestedNumber(draft, '_pose', 'head_tilt', 0),
    }),
    [draft],
  )

  const imageSections = useMemo(() => {
    if (!selectedCharacter) {
      return []
    }
    const identity = asRecord(draft._identity)
    const style = asRecord(draft._style)
    const outfit = asRecord(style.outfit)
    const meta = asRecord(draft._meta)
    const identityRefs = asImageRefList(identity.ref_images)
    const faceDetails = identityRefs.filter((item) => item.angle === 'face_detail')
    const turnaroundRefs = identityRefs.filter((item) => item.angle !== 'face_detail')
    const thumbnailPath = String(meta.thumbnail ?? '').trim()
    const sections = [
      {
        key: 'identity',
        title: '身份參考圖',
        items: turnaroundRefs,
      },
      {
        key: 'face-detail',
        title: '面部細節圖',
        items: faceDetails,
      },
      {
        key: 'age-faces',
        title: '年齡軸面部 1–80',
        items: ageSpanBucketItems(draft, 'faces'),
      },
      {
        key: 'age-tposes',
        title: '年齡軸 T 型 1–80',
        items: ageSpanBucketItems(draft, 'tposes'),
      },
      {
        key: 'outfit',
        title: '服裝參考圖',
        items: asImageRefList(outfit.ref_images),
      },
      {
        key: 'style',
        title: '風格參考圖',
        items: asImageRefList(style.reference_images),
      },
      {
        key: 'thumb',
        title: '縮圖預覽',
        items: thumbnailPath ? [{ path: thumbnailPath, note: 'thumbnail' }] : [],
      },
    ]
    return sections
      .map((section) => ({
        ...section,
        items: section.items.map((item) => ({
          ...item,
          src: assetUrl(apiBase, selectedCharacter.id, item),
        })),
      }))
      .filter((section) => section.items.length > 0)
  }, [apiBase, draft, selectedCharacter])

  const filteredQueueTasks = useMemo(() => {
    const tasks = queueData?.tasks ?? []
    if (!queueStatusFilter) {
      return tasks
    }
    const status = normalizeStatus(queueStatusFilter)
    return tasks.filter((task) => effectiveTaskStatus(task) === status)
  }, [queueData, queueStatusFilter])

  const focusTask = useMemo(() => {
    const tasks = queueData?.tasks ?? []
    if (!tasks.length) {
      return null
    }
    if (pinnedTaskId != null) {
      const pinned = tasks.find((task) => task.id === pinnedTaskId)
      if (pinned) {
        return pinned
      }
    }
    if (ageSpanStatus?.next_runnable_task_id) {
      const next = tasks.find((task) => task.id === ageSpanStatus.next_runnable_task_id)
      if (next) {
        return next
      }
    }
    const failed = tasks.find((task) => normalizeStatus(task.status) === 'failed')
    if (failed) {
      return failed
    }
    const pending = tasks.find((task) => normalizeStatus(task.status) === 'pending')
    if (pending) {
      return pending
    }
    return tasks[0] ?? null
  }, [queueData, ageSpanStatus, pinnedTaskId])

  useEffect(() => {
    focusTaskRef.current = focusTask
  }, [focusTask])

  const workflowSnapshot = useMemo(
    () => deriveWorkflowSnapshot(queueData, ageSpanStatus, queueAutoRun),
    [queueData, ageSpanStatus, queueAutoRun],
  )

  useEffect(() => {
    autoResumeAttemptedRef.current = false
  }, [selectedCharacter?.id, queueData?.tasks?.length])

  useEffect(() => {
    if (!autoContinue || queueAutoRun || autoResumeAttemptedRef.current) {
      return
    }
    if (!queueData?.tasks?.length) {
      return
    }
    const pendingCount = queueData.stats.total_pending ?? 0
    const waitingCount = queueData.stats.total_waiting ?? 0
    if (pendingCount > 0 || waitingCount > 0) {
      autoResumeAttemptedRef.current = true
      void startAutoPipeline({ resetFailed: false })
    }
  }, [autoContinue, queueAutoRun, queueData])

  const ageSpanSteps = ageSpanStatus?.steps ?? []

  const ageSpanPhaseSteps = useMemo(
    () => ageSpanStepsForPhase(ageSpanSteps, ageSpanPhaseTab),
    [ageSpanSteps, ageSpanPhaseTab],
  )

  const recentCompactTasks = useMemo(() => {
    const tasks = filteredQueueTasks
    return [...tasks]
      .sort((left, right) => {
        const leftTime = Date.parse(String(left.updated_at || left.created_at || '')) || 0
        const rightTime = Date.parse(String(right.updated_at || right.created_at || '')) || 0
        return rightTime - leftTime
      })
      .slice(0, 8)
  }, [filteredQueueTasks])

  const pipelineProgress = useMemo(() => {
    if (!ageSpanStatus?.has_open_pipeline || !ageSpanStatus.total_steps) {
      return null
    }
    const percent = Math.round((ageSpanStatus.accepted_count / ageSpanStatus.total_steps) * 100)
    return {
      percent: Math.min(100, Math.max(0, percent)),
      label: `${ageSpanStatus.accepted_count} / ${ageSpanStatus.total_steps}`,
    }
  }, [ageSpanStatus])


  const queuePreviewItems = useMemo(() => {
    if (!queueData) {
      return []
    }
    const items: GeneratedImageItem[] = []
    for (const task of filteredQueueTasks) {
      const imageGen = taskImageGeneration(task)
      const detailImages = taskDetailImages(apiBase, task)
      for (const image of detailImages) {
        items.push({
          path: image.path,
          uri: image.uri,
          angle: image.angle,
          note: `${String(imageGen.purpose ?? 'identity')} · ${task.character_name || task.core_id}`,
          src: image.src,
        })
      }
    }
    return items
  }, [apiBase, filteredQueueTasks, queueData])

  const sortedBranches = useMemo(() => {
    if (!versionSummary?.branches?.length) {
      return []
    }
    return [...versionSummary.branches].sort((left, right) => {
      const explicitSortDelta = (left.sort_order ?? Number.MAX_SAFE_INTEGER) - (right.sort_order ?? Number.MAX_SAFE_INTEGER)
      if (Number.isFinite(explicitSortDelta) && explicitSortDelta !== 0) {
        return explicitSortDelta
      }
      const branchDelta = branchSortValue(left) - branchSortValue(right)
      if (branchDelta !== 0) {
        return branchDelta
      }
      const statusDelta = reviewSortValue(branchEffectiveStatus(left)) - reviewSortValue(branchEffectiveStatus(right))
      if (statusDelta !== 0) {
        return statusDelta
      }
      return String(right.updated_at ?? '').localeCompare(String(left.updated_at ?? ''))
    })
  }, [versionSummary])

  async function queueImageGeneration(purposeOverride?: string) {
    if (!selectedCharacter) {
      return
    }
    const queuedPurpose = purposeOverride || purpose
    setImageBusy(true)
    onError(null)
    try {
      const response = await fetch(`${apiBase}/api/v1/characters/${selectedCharacter.id}/image-queue`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CharacterOS-Panel': 'enabled',
        },
        body: JSON.stringify({
          purpose: queuedPurpose,
          provider: provider || null,
          model: model || null,
          base_url: baseUrl || null,
          extra: extraPrompt,
          multi_angle: queuedPurpose !== 'age_span' && queuedPurpose !== 'tpose' && queuedPurpose !== 'face_detail',
          persist: true,
          priority: 0,
          age_start: 1,
          age_end: 80,
        }),
      })
      if (!response.ok) {
        throw new Error((await response.text()) || `HTTP ${response.status}`)
      }
      await loadQueueTasks()
      await loadCharacterSummaries()
      setPinnedTaskId(null)
      if (queuedPurpose === 'age_span') {
        setAgeSpanPhaseTab('face_detail')
        setPipelineMessage('已排入年齡軸，自動開始逐步生圖並直接入庫…')
      } else {
        setPipelineMessage('已排入生圖任務，自動開始執行並直接入庫…')
      }
      void startAutoPipeline({ resetFailed: false })
    } catch (queueError) {
      onError(queueError instanceof Error ? queueError.message : '建立生圖佇列任務失敗')
    } finally {
      setImageBusy(false)
    }
  }

  async function clearQueueTasks(onlySelected: boolean) {
    const scopeLabel = onlySelected && selectedCharacter ? `角色 ${selectedCharacter.id}` : '全部'
    if (!window.confirm(`確定要清空${scopeLabel}的佇列任務？此操作無法復原。`)) {
      return
    }
    setQueueBusy(true)
    onError(null)
    stopAutoPipeline()
    try {
      const params = new URLSearchParams()
      if (onlySelected && selectedCharacter?.id) {
        params.set('core_id', selectedCharacter.id)
      }
      const response = await fetch(`${apiBase}/api/v1/admin/queue-tasks/clear?${params.toString()}`, {
        method: 'POST',
      })
      if (!response.ok) {
        throw new Error((await response.text()) || `HTTP ${response.status}`)
      }
      const body = (await response.json()) as { cleared?: number }
      setPipelineMessage(`已清空 ${body.cleared ?? 0} 筆任務。`)
      setAgeSpanStatus(null)
      setPinnedTaskId(null)
      autoResumeAttemptedRef.current = false
      await loadQueueTasks({ keepError: true })
    } catch (taskError) {
      onError(taskError instanceof Error ? taskError.message : '清空佇列失敗')
    } finally {
      setQueueBusy(false)
    }
  }

  async function copyPrompt() {
    if (!lastGeneratedPrompt) {
      return
    }
    await navigator.clipboard.writeText(lastGeneratedPrompt)
  }

  async function saveDraft() {
    if (!selectedCharacter) {
      return
    }
    setBusy(true)
    onError(null)
    try {
      const response = await fetch(`${apiBase}/api/v1/characters/${selectedCharacter.id}/charpass`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ charpass: draft }),
      })
      if (!response.ok) {
        throw new Error((await response.text()) || `HTTP ${response.status}`)
      }
      const body = (await response.json()) as { charpass?: Record<string, unknown> }
      const next = body.charpass ?? draft
      setDraft(next)
      patchCharacterSummaryFromCharpass(selectedCharacter.id, next)
      onPatchEntity(selectedCharacter.id, next)
      await reloadCharacterCharpass(selectedCharacter.id)
    } catch (saveError) {
      onError(saveError instanceof Error ? saveError.message : '儲存角色護照失敗')
    } finally {
      setBusy(false)
    }
  }

  async function exportCharpass() {
    if (!selectedCharacter) {
      return
    }
    setBusy(true)
    onError(null)
    try {
      const response = await fetch(`${apiBase}/api/v1/characters/${selectedCharacter.id}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ format: 'charpass', mode: 'full', include_assets: true }),
      })
      if (!response.ok) {
        throw new Error((await response.text()) || `HTTP ${response.status}`)
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      const headerName = response.headers.get('content-disposition')
      const match = headerName?.match(/filename="([^"]+)"/)
      link.href = url
      link.download = match?.[1] ?? `${selectedCharacter.name ?? selectedCharacter.id}.charpass`
      link.click()
      URL.revokeObjectURL(url)
    } catch (exportError) {
      onError(exportError instanceof Error ? exportError.message : '導出角色護照失敗')
    } finally {
      setBusy(false)
    }
  }

  async function importCharpass(file: File) {
    if (!projectId) {
      onError('請先選擇專案再導入角色護照')
      return
    }
    setBusy(true)
    onError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('conflict_strategy', conflictStrategy)
      form.append('confirm', conflictStrategy === 'overwrite' ? 'true' : 'false')
      const response = await fetch(`${apiBase}/api/v1/projects/${projectId}/characters/import`, {
        method: 'POST',
        body: form,
      })
      if (!response.ok) {
        throw new Error((await response.text()) || `HTTP ${response.status}`)
      }
      const body = (await response.json()) as {
        entity_id: string
        name?: string
        charpass?: Record<string, unknown>
        note?: string
        continuity_tokens?: string[]
      }
      const lite = await fetch(`${apiBase}/api/v1/characters/${body.entity_id}/charpass`)
      const liteBody = lite.ok ? ((await lite.json()) as { charpass?: Record<string, unknown> }) : {}
      patchCharacterSummaryFromCharpass(body.entity_id, liteBody.charpass ?? {})
      onPatchEntity(body.entity_id, liteBody.charpass ?? {}, {
        name: body.name ?? body.entity_id,
        note: body.note,
        continuity_tokens: body.continuity_tokens,
      })
      onSelect(body.entity_id)
    } catch (importError) {
      onError(importError instanceof Error ? importError.message : '導入角色護照失敗')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (!focused) {
      return
    }
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null
      const tag = target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
        if ((target as HTMLInputElement).type !== 'range') {
          return
        }
      }
      if (event.key === 's' || event.key === 'S') {
        event.preventDefault()
        void saveDraft()
      } else if (event.key === 'e' || event.key === 'E') {
        event.preventDefault()
        void exportCharpass()
      } else if (event.key === 'i' || event.key === 'I') {
        event.preventDefault()
        importInputRef.current?.click()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [focused, draft, selectedCharacter, conflictStrategy, projectId])

  return (
    <div
      className="panel inset-panel charpass-panel"
      tabIndex={0}
      onFocus={() => setFocused(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setFocused(false)
        }
      }}
    >
      <div className="section-header">
        <div>
          <h3>角色檢視</h3>
          <p>Dashboard 子面板。快捷鍵（聚焦此區）：S 儲存、E 導出、I 導入。</p>
        </div>
        <span className="pill">{characters.length} characters</span>
      </div>

      {characters.length === 0 ? (
        <div className="empty-state small">尚無角色。先在 Pad 執行 Parse。</div>
      ) : (
        <>
          <div className="character-card-grid">
            {characters.map((character) => {
              const thumb = characterThumbnail(apiBase, character, characterSummaries[character.id])
              return (
                <button
                  key={character.id}
                  className={`list-item ${selectedCharacter?.id === character.id ? 'active' : ''}`}
                  onClick={() => onSelect(character.id)}
                >
                  {thumb ? (
                    <div className="character-list-thumb">
                      <img src={thumb.src} alt={thumb.label} loading="lazy" />
                    </div>
                  ) : null}
                  <strong>{character.name || character.id}</strong>
                  <span>{character.id}</span>
                </button>
              )
            })}
          </div>

          <section className="queue-panel queue-console">
            <div className="queue-dashboard">
              <div className="section-header compact">
                <div>
                  <h4>AI 生圖控制台</h4>
                  <p className="queue-console-subtitle">
                    {selectedCharacter
                      ? `${selectedCharacter.name || selectedCharacter.id} · 自動逐步生圖並直接入庫`
                      : '請先選擇角色'}
                  </p>
                </div>
                <div className="status-strip">
                  <span className="pill">
                    {queueData?.storage_mode === 'database' ? 'PostgreSQL' : queueData?.storage_mode === 'local' ? '本機 JSON' : '未載入'}
                  </span>
                </div>
              </div>

              <QueueStatGrid stats={queueData?.stats} ageSpanStatus={ageSpanStatus} queueAutoRun={queueAutoRun} />

              {workflowSnapshot.isEmpty && selectedCharacter ? (
                <>
                  <QueueEmptyHero
                    characterName={selectedCharacter.name || selectedCharacter.id}
                    disabled={imageBusy || queueBusy}
                    onStart={() => {
                      setPurpose('age_span')
                      void queueImageGeneration('age_span')
                    }}
                  />
                  <div className="queue-secondary-actions queue-secondary-actions--empty">
                    <button className="ghost" onClick={() => void loadQueueTasks()} disabled={queueBusy}>
                      刷新
                    </button>
                  </div>
                  <div className="workflow-preferences">
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={autoContinue}
                        onChange={(event) => setAutoContinueEnabled(event.target.checked)}
                      />
                      <span>刷新頁面後，若仍有待處理任務就喚醒後端 worker</span>
                    </label>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={queueOnlySelected}
                        onChange={(event) => setQueueOnlySelected(event.target.checked)}
                      />
                      <span>只看目前角色</span>
                    </label>
                  </div>
                </>
              ) : (
                <>
                  <WorkflowStepper phase={workflowSnapshot.phase} />

                  <div
                    className={`workflow-status-card${queueAutoRun ? ' workflow-status-card--busy' : ''}`}
                  >
                    <div className="workflow-status-card-header">
                      <strong>{workflowSnapshot.title}</strong>
                      {queueAutoRun ? <span className="queue-spinner" aria-hidden="true" /> : null}
                    </div>
                    <p>{pipelineMessage || workflowSnapshot.hint}</p>
                  </div>

                  <QueueKeyboardHints visible={queueAutoRun} />

                  {pipelineProgress ? (
                    <div className="pipeline-progress-card">
                      <div className="pipeline-progress-header">
                        <strong>
                          年齡軸 · {ageSpanStatus?.character_name || `角色 #${ageSpanStatus?.core_id ?? '?'}`}
                        </strong>
                        <span>{pipelineProgress.label} 步已完成</span>
                      </div>
                      <div className="pipeline-progress-bar" aria-hidden="true">
                        <div className="pipeline-progress-fill" style={{ width: `${pipelineProgress.percent}%` }} />
                      </div>
                      <div className="pipeline-progress-stats">
                        <span>已完成 {ageSpanStatus?.accepted_count ?? 0}</span>
                        <span>進行中 {ageSpanStatus?.pending_count ?? 0}</span>
                        <span>尚未開始 {ageSpanStatus?.waiting_count ?? 0}</span>
                        {ageSpanStatus?.failed_count ? (
                          <span className="warn">失敗 {ageSpanStatus.failed_count}</span>
                        ) : null}
                        {ageSpanStatus?.next_runnable_task_id ? (
                          <span>
                            下一步 #{ageSpanStatus.next_runnable_task_id}
                            {ageSpanStatus.next_age != null ? ` · ${ageSpanStatus.next_age} 歲` : ''}
                          </span>
                        ) : null}
                      </div>
                      {ageSpanStatus?.blocking_reason ? (
                        <p className="pipeline-blocking-reason">{ageSpanStatus.blocking_reason}</p>
                      ) : null}
                    </div>
                  ) : null}

                  {ageSpanSteps.length ? <QueuePhaseProgress ageSpanSteps={ageSpanSteps} /> : null}

                  <div className="queue-action-bar">
                    <div className="queue-primary-actions workflow-primary-actions">
                      {queueAutoRun ? (
                        <button className="secondary workflow-cta" onClick={() => stopAutoPipeline()} disabled={queueBusy}>
                          暫停後端生圖
                        </button>
                      ) : workflowSnapshot.canAutoRun ? (
                        <button
                          className="primary workflow-cta"
                          onClick={() => void startAutoPipeline({ resetFailed: false })}
                          disabled={queueBusy}
                        >
                          繼續後端生圖
                        </button>
                      ) : workflowSnapshot.isComplete && !workflowSnapshot.isEmpty ? (
                        <button className="secondary workflow-cta" disabled>
                          流程已完成
                        </button>
                      ) : null}
                      {workflowSnapshot.hasFailed && !queueAutoRun ? (
                        <button
                          className="secondary"
                          onClick={() => void startAutoPipeline({ resetFailed: true })}
                          disabled={queueBusy || queueAutoRun}
                        >
                          重設失敗並繼續
                        </button>
                      ) : null}
                    </div>
                    <div className="queue-secondary-actions">
                      <button className="ghost" onClick={() => void loadQueueTasks()} disabled={queueBusy}>
                        刷新
                      </button>
                      <button
                        className="ghost queue-danger-btn"
                        onClick={() => void clearQueueTasks(queueOnlySelected)}
                        disabled={queueBusy}
                      >
                        清空佇列
                      </button>
                    </div>
                  </div>

                  <div className="workflow-preferences">
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={autoContinue}
                        onChange={(event) => setAutoContinueEnabled(event.target.checked)}
                      />
                      <span>刷新頁面後，若仍有待處理任務就喚醒後端 worker</span>
                    </label>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={queueOnlySelected}
                        onChange={(event) => setQueueOnlySelected(event.target.checked)}
                      />
                      <span>只看目前角色</span>
                    </label>
                  </div>
                </>
              )}

              {focusTask && !workflowSnapshot.isEmpty ? (
                <div className={`queue-focus-card status-panel-${effectiveTaskStatus(focusTask)}`}>
                  {(() => {
                    const task = focusTask
                    const detailImages = taskDetailImages(apiBase, task)
                    const heroImage = taskHeroImage(apiBase, task, detailImages)
                    const characterSummary = characterSummaries[String(task.core_id)]
                    const characterName = task.character_name || characterSummary?.name || `角色 ${task.core_id}`
                    const reviewStatus = taskReviewStatus(task)
                    const effectiveStatus = effectiveTaskStatus(task)
                    const thumbSrc =
                      heroImage?.src ||
                      taskThumbnailSrc(apiBase, task, detailImages, characterSummary) ||
                      ''
                    return (
                      <>
                        <div className="queue-focus-header">
                          <div>
                            <strong className="queue-focus-title">
                              目前步驟 · #{task.id} · {purposeLabel(taskPurpose(task) || 'identity')}
                              {taskAge(task) ? ` · ${taskAge(task)} 歲` : ''}
                            </strong>
                            <p className="queue-focus-subtitle">{taskWorkflowHint(task)}</p>
                          </div>
                          <div className="task-status-group">
                            <span className={statusBadgeClass(effectiveStatus)}>
                              {statusLabel(effectiveStatus, reviewStatus)}
                            </span>
                            <span className={purposeBadgeClass(taskPurpose(task) || 'identity')}>
                              {purposeLabel(taskPurpose(task) || 'identity')}
                            </span>
                          </div>
                        </div>
                        <div className="queue-focus-body">
                          {thumbSrc ? (
                            <a className="queue-focus-preview" href={thumbSrc} target="_blank" rel="noreferrer">
                              <img src={thumbSrc} alt={characterName} loading="lazy" />
                            </a>
                          ) : (
                            <div className="queue-focus-preview queue-focus-preview--empty">
                              <span>{normalizeStatus(task.status) === 'pending' ? '等待生圖…' : '尚無預覽'}</span>
                            </div>
                          )}
                          <div className="queue-focus-meta">
                            <div className="queue-focus-meta-row">
                              <span>角色</span>
                              <strong>{characterName}</strong>
                            </div>
                            <div className="queue-focus-meta-row">
                              <span>狀態</span>
                              <strong>{taskWorkflowLabel(task)}</strong>
                            </div>
                            <div className="queue-focus-meta-row">
                              <span>摘要</span>
                              <strong>{responseSummary(task)}</strong>
                            </div>
                            {task.error_message ? (
                              <div className="error-banner">{task.error_message}</div>
                            ) : null}
                            <div className="queue-focus-actions">
                              {queueAutoRun && normalizeStatus(task.status) === 'pending' ? (
                                <span className="pill purpose-age-span">自動生圖中…</span>
                              ) : null}
                              {task.result_url ? (
                                <a
                                  className="ghost link-button"
                                  href={`${apiBase}${task.result_url}`}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  查看結果
                                </a>
                              ) : null}
                            </div>
                          </div>
                        </div>
                      </>
                    )
                  })()}
                </div>
              ) : null}

              {ageSpanSteps.length ? (
                <div className="age-span-timeline">
                  <div className="age-span-timeline-header">
                    <strong>年齡軸時間軸</strong>
                    <div className="age-span-phase-tabs">
                      <button
                        type="button"
                        className={`ghost ${ageSpanPhaseTab === 'face_detail' ? 'active' : ''}`}
                        onClick={() => setAgeSpanPhaseTab('face_detail')}
                      >
                        面部細緻
                        <span className="pill purpose-face-detail">
                          {countStepsByStatus(ageSpanStepsForPhase(ageSpanSteps, 'face_detail'), 'accepted')}/80
                        </span>
                      </button>
                      <button
                        type="button"
                        className={`ghost ${ageSpanPhaseTab === 'tpose' ? 'active' : ''}`}
                        onClick={() => setAgeSpanPhaseTab('tpose')}
                      >
                        T 型外觀
                        <span className="pill purpose-tpose">
                          {countStepsByStatus(ageSpanStepsForPhase(ageSpanSteps, 'tpose'), 'accepted')}/80
                        </span>
                      </button>
                    </div>
                  </div>
                  <div className="age-span-step-legend">
                    <span className="legend-item status-accepted">已入庫</span>
                    <span className="legend-item status-pending">排隊中</span>
                    <span className="legend-item status-failed">失敗</span>
                    <span className="legend-item status-missing">未開始</span>
                  </div>
                  <div className="age-span-step-grid">
                    {ageSpanPhaseSteps.map((step) => {
                      const normalized = normalizeStatus(step.status)
                      const isCurrent =
                        focusTask?.id === step.task_id ||
                        ageSpanStatus?.blocking_task_id === step.task_id ||
                        ageSpanStatus?.next_runnable_task_id === step.task_id
                      return (
                        <button
                          key={`${step.phase}-${step.age}-${step.step_index}`}
                          type="button"
                          className={`age-span-step-cell status-${normalized || 'missing'}${isCurrent ? ' is-current' : ''}`}
                          title={
                            step.error_message ||
                            `${step.age} 歲 · ${ageSpanStepStatusLabel(step.status)}`
                          }
                          onClick={() => {
                            if (step.task_id) {
                              setPinnedTaskId(step.task_id)
                            }
                          }}
                          disabled={!step.task_id}
                        >
                          <span className="age-span-step-age">{step.age}</span>
                        </button>
                      )
                    })}
                  </div>
                  <p className="age-span-timeline-hint">點選年齡格子可切換上方「目前步驟」預覽；綠色代表已入庫。</p>
                </div>
              ) : null}

              <details
                className="queue-advanced"
                open={showQueueForm}
                onToggle={(event) => setShowQueueForm((event.target as HTMLDetailsElement).open)}
              >
                <summary className="queue-advanced-summary">
                  生圖設定（進階）
                  <span className="subtle">Provider / Model / 單次用途</span>
                </summary>
                <div className="inline-grid queue-form-grid">
                  <label className="field">
                    <span>用途</span>
                    <select value={purpose} onChange={(event) => setPurpose(event.target.value)}>
                      <option value="identity">identity</option>
                      <option value="face_detail">face_detail</option>
                      <option value="tpose">tpose</option>
                      <option value="age_span">age_span（新人物 1–80）</option>
                      <option value="outfit">outfit</option>
                      <option value="expression">expression</option>
                      <option value="thumb">thumb</option>
                    </select>
                  </label>
                  <label className="field">
                    <span>Provider</span>
                    <input value={provider} onChange={(event) => setProvider(event.target.value)} placeholder="wan" />
                  </label>
                  <label className="field">
                    <span>Model</span>
                    <input value={model} onChange={(event) => setModel(event.target.value)} placeholder="沿用後端預設" />
                  </label>
                  <label className="field">
                    <span>Base URL</span>
                    <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="沿用後端預設" />
                  </label>
                </div>
                <label className="field">
                  <span>額外提示詞</span>
                  <textarea
                    value={extraPrompt}
                    onChange={(event) => setExtraPrompt(event.target.value)}
                    placeholder="可補充服裝、鏡頭、材質、風格等要求"
                  />
                </label>
                <div className="button-row compact">
                  <button className="primary" onClick={() => void queueImageGeneration()} disabled={!selectedCharacter || imageBusy}>
                    {purpose === 'age_span' ? '排入 1–80 歲面部 + T型體' : '排入生圖任務'}
                  </button>
                  <button className="ghost" onClick={() => void copyPrompt()} disabled={!lastGeneratedPrompt}>
                    複製最新提示詞
                  </button>
                </div>
              </details>

              <details
                className="queue-advanced"
                open={showFullTaskList}
                onToggle={(event) => setShowFullTaskList((event.target as HTMLDetailsElement).open)}
              >
                <summary className="queue-advanced-summary">
                  技術紀錄（選用）
                  <span className="pill">{recentCompactTasks.length}</span>
                  <span className="subtle">任務 ID、狀態明細</span>
                </summary>
                <div className="queue-toolbar">
                  <label className="field">
                    <span>狀態過濾</span>
                    <select value={queueStatusFilter} onChange={(event) => setQueueStatusFilter(event.target.value)}>
                      <option value="">全部</option>
                      <option value="pending">pending</option>
                      <option value="accepted">accepted</option>
                      <option value="rejected">rejected</option>
                      <option value="ready">ready</option>
                      <option value="failed">failed</option>
                    </select>
                  </label>
                </div>
                {recentCompactTasks.length ? (
                  <div className="queue-recent-list">
                    {recentCompactTasks.map((task) => {
                      const reviewStatus = taskReviewStatus(task)
                      const effectiveStatus = effectiveTaskStatus(task)
                      return (
                        <button
                          key={task.id}
                          type="button"
                          className={`queue-recent-row status-panel-${effectiveStatus}${pinnedTaskId === task.id ? ' is-pinned' : ''}`}
                          onClick={() => setPinnedTaskId(task.id)}
                        >
                          <span className="queue-recent-id">#{task.id}</span>
                          <span className="queue-recent-main">
                            {purposeLabel(taskPurpose(task) || 'identity')}
                            {taskAge(task) ? ` · ${taskAge(task)} 歲` : ''}
                          </span>
                          <span className={statusBadgeClass(effectiveStatus)}>
                            {statusLabel(effectiveStatus, reviewStatus)}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                ) : (
                  <div className="empty-state small">目前沒有符合條件的任務。</div>
                )}
              </details>

              {!ageSpanSteps.length ? (
                <div className="image-sections">
                  {queuePreviewItems.length === 0 ? (
                    <div className="empty-state small">任務產出的圖片會顯示在這裡，包含面部細節圖。</div>
                  ) : (
                    <section className="image-section">
                      <div className="section-header compact">
                        <h4>任務圖片預覽</h4>
                        <span className="pill">{queuePreviewItems.length}</span>
                      </div>
                      <div className="image-grid">
                        {queuePreviewItems.slice(0, 12).map((item, index) => (
                          <a
                            key={`${item.path}-${index}`}
                            className="image-card"
                            href={item.src}
                            target="_blank"
                            rel="noreferrer"
                          >
                            <img src={item.src} alt={item.angle || item.note || `queue-image-${index + 1}`} loading="lazy" />
                            <div className="image-meta">
                              <strong>{item.angle === 'face_detail' ? 'face_detail' : item.angle || item.note || `image-${index + 1}`}</strong>
                              <span>{item.path}</span>
                            </div>
                          </a>
                        ))}
                      </div>
                    </section>
                  )}
                </div>
              ) : null}
            </div>
          </section>

          <div className="layer-tabs">
            {LAYERS.map((item) => (
              <button
                key={item}
                className={`ghost ${layer === item ? 'active' : ''}`}
                onClick={() => setLayer(item)}
              >
                {item}
              </button>
            ))}
          </div>

          <div className="image-sections">
            {imageSections.length === 0 ? (
              <div className="empty-state small">目前還沒有可顯示的圖片。先生成並寫回角色護照。</div>
            ) : (
              imageSections.map((section) => (
                <section key={section.key} className="image-section">
                  <div className="section-header compact">
                    <h4>{section.title}</h4>
                    <span className="pill">{section.items.length}</span>
                  </div>
                  <div className="image-grid">
                    {section.items.map((item, index) => (
                      <a
                        key={`${section.key}-${item.path || item.uri || index}`}
                        className="image-card"
                        href={item.src}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <img src={item.src} alt={item.angle || item.note || section.title} loading="lazy" />
                        <div className="image-meta">
                          <strong>{item.angle || item.note || `image-${index + 1}`}</strong>
                          <span>{item.path || item.uri}</span>
                        </div>
                      </a>
                    ))}
                  </div>
                </section>
              ))
            )}
          </div>

          <section className="queue-panel">
            <div className="section-header compact">
              <h4>版本分支</h4>
              <div className="status-strip">
                <span className="pill">{versionSummary?.entity_id || '未載入'}</span>
                <span className="pill">history {versionSummary?.history.length ?? 0}</span>
                <span className="pill">branches {versionSummary?.branches.length ?? 0}</span>
              </div>
            </div>
            {!versionSummary ? (
              <div className="empty-state small">選擇角色後會顯示 `current.charpass`、歷史快照與衍生分支。</div>
            ) : (
              <>
                <div className="queue-task-list">
                  {versionSummary.history.map((item) => (
                    <div key={`${item.kind}-${item.path}`} className="queue-task-card">
                      <div className="queue-task-header">
                        <div>
                          <strong>{item.name}</strong>
                          <div className="queue-task-meta">
                            <span>{item.kind}</span>
                            <span>{item.is_binary ? 'binary' : 'readable'}</span>
                          </div>
                        </div>
                      </div>
                      <div className="queue-task-meta">
                        <span>{item.path}</span>
                      </div>
                    </div>
                  ))}
                </div>
                {sortedBranches.length ? (
                  <div className="queue-task-list">
                    {sortedBranches.map((branch) => {
                      const branchPurposeValue = branchPurpose(branch)
                      const branchImages = selectedCharacter
                        ? branchDetailImages(apiBase, selectedCharacter.id, branch)
                        : []
                      const branchHero = selectedCharacter
                        ? branchHeroImage(apiBase, selectedCharacter.id, branch, branchImages)
                        : null
                      const branchGalleryImages = branchImages.filter(
                        (item) =>
                          `${item.path || ''}::${item.angle || ''}` !==
                          `${branchHero?.path || ''}::${branchHero?.angle || ''}`,
                      )
                      const branchImageGroups = detailImageGroups(branchGalleryImages)
                      const branchStatus = branchEffectiveStatus(branch)
                      const branchReviewStatus = normalizeStatus(branch.review_status)
                      const branchReviewLabel = branchReviewStatusLabel(branch)
                      const branchWorkflow = branchWorkflowLabel(branch)
                      const branchWorkflowDescription = branchWorkflowHint(branch)
                      const branchAngles = branchAngleList(branch, branchImages)
                      const branchSectionLabels = branchDetailSections(branch, branchImages)
                      const branchPrompt = branchPromptText(branch)
                      const branchNegativePrompt = branchNegativePromptText(branch)
                      const branchParams = branchEvolutionParams(branch)
                      const branchThumbnail = selectedCharacter
                        ? branchThumbnailSrc(apiBase, selectedCharacter.id, branch, branchHero, branchImages)
                        : ''
                      return (
                      <details
                        key={`${branch.kind}-${branch.branch_id}`}
                        className={`queue-task-card task-disclosure version-branch-card status-panel-${branchStatus} version-branch-purpose-${normalizeStatus(branchPurposeValue) || 'unknown'}`}
                      >
                        <summary className="task-summary">
                          <div className="task-summary-layout">
                            {branchThumbnail ? (
                              <a
                                className="task-summary-thumb task-summary-thumb--branch"
                                href={branchThumbnail}
                                target="_blank"
                                rel="noreferrer"
                                onClick={stopSummaryToggle}
                                onMouseDown={(event) => event.stopPropagation()}
                              >
                                <img src={branchThumbnail} alt={branch.label} loading="lazy" />
                              </a>
                            ) : null}
                            <div className="task-summary-main">
                              <div className="task-summary-title-row">
                                <div className="task-summary-heading">
                                  <strong>{branch.label}</strong>
                                  <span className="task-summary-subtitle">{branchTypeLabel(branch.kind, branch.purpose)}</span>
                                </div>
                                <div className="task-status-group">
                                  <span className={statusBadgeClass(branchStatus)}>{statusLabel(branchStatus, branchReviewStatus)}</span>
                                  {branchReviewLabel ? (
                                    <span className={statusBadgeClass(branchReviewStatus || 'ready')}>審核 {branchReviewLabel}</span>
                                  ) : null}
                                  {branchPurposeValue ? (
                                    <span className={purposeBadgeClass(branchPurposeValue)}>{purposeLabel(branchPurposeValue)}</span>
                                  ) : null}
                                  <span className={branchKindBadgeClass(branch.kind)}>{branch.kind || 'branch'}</span>
                                </div>
                              </div>
                              <div className="queue-task-meta">
                                <span>branch {branch.branch_id.slice(0, 8)}</span>
                                {branch.updated_at ? <span>{formatDateTime(branch.updated_at)}</span> : null}
                              </div>
                              <p className="task-inline-summary">{branchShortSummary(branch)}</p>
                              <div className="task-summary-overview">
                                {[branchWorkflow, ...branchOverviewLines(branch, branchStatus, branchAngles)].map((line) => (
                                  <span key={`${branch.branch_id}-${line}`} className="summary-outline-pill">
                                    {line}
                                  </span>
                                ))}
                              </div>
                              <p className="task-inline-summary subtle">
                                {branchImageGroups.faceDetail.length || branchHero?.angle === 'face_detail'
                                  ? 'face_detail 優先'
                                  : '一般分支'}
                                {` · ${branchWorkflowDescription}`}
                                {branchSectionLabels.length ? ` · 詳情含 ${branchSectionLabels.join(' / ')}` : ''}
                              </p>
                              {branchAngles.length ? (
                                <div className="task-chip-row task-chip-row-tight">
                                  {branchAngles.map((angle) => (
                                    <span
                                      key={`${branch.branch_id}-summary-${angle}`}
                                      className={angle === 'face_detail' ? 'pill purpose-face-detail' : 'pill pill-ghost'}
                                    >
                                      {angle}
                                    </span>
                                  ))}
                                </div>
                              ) : null}
                            </div>
                          </div>
                        </summary>
                        <div className="task-detail-content">
                          {branchHero ? (
                            <section className="task-detail-section">
                              <div className="section-header compact">
                                <h4>面部細節首圖</h4>
                                <span className="pill purpose-face-detail">
                                  {branchHero.angle === 'face_detail' ? '固定首圖' : '縮圖回退'}
                                </span>
                              </div>
                              <a
                                className={`image-card task-hero-image ${
                                  branchHero.angle === 'face_detail' ? 'face-detail-priority' : ''
                                }`}
                                href={branchHero.src}
                                target="_blank"
                                rel="noreferrer"
                              >
                                <img src={branchHero.src} alt={branchHero.angle || branchHero.note || branch.label} loading="lazy" />
                                <div className="image-meta">
                                  <strong>{branchHero.angle || branchHero.note || 'branch-image'}</strong>
                                  <span>{branchHero.summary || branchHero.path || branchHero.uri}</span>
                                </div>
                              </a>
                            </section>
                          ) : null}
                          {selectedCharacter ? (
                            <section className="task-detail-section">
                              <div className="section-header compact">
                                <h4>人物關聯</h4>
                              </div>
                              <div className="task-character-card">
                                {branchThumbnail ? (
                                  <a className="task-character-thumb" href={branchThumbnail} target="_blank" rel="noreferrer">
                                    <img src={branchThumbnail} alt={selectedCharacter.name || selectedCharacter.id} loading="lazy" />
                                  </a>
                                ) : null}
                                <div className="task-character-meta">
                                  <strong>{selectedCharacter.name || selectedCharacter.id}</strong>
                                  <div className="queue-task-meta">
                                    <span>角色 #{selectedCharacter.id}</span>
                                    <span>分支 {branch.branch_id.slice(0, 8)}</span>
                                    <span>{branchTypeLabel(branch.kind, branchPurposeValue)}</span>
                                  </div>
                                  <div className="task-chip-row">
                                    {branchPurposeValue ? (
                                      <span className={purposeBadgeClass(branchPurposeValue)}>{purposeLabel(branchPurposeValue)}</span>
                                    ) : null}
                                    <span className={statusBadgeClass(branchStatus)}>{statusDisplay(branchStatus)}</span>
                                    {branchAngles.map((angle) => (
                                      <span
                                        key={`${branch.branch_id}-character-${angle}`}
                                        className={angle === 'face_detail' ? 'pill purpose-face-detail' : 'pill pill-ghost'}
                                      >
                                        {angle}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              </div>
                            </section>
                          ) : null}
                          <div className="task-chip-row detail-chip-row">
                            {branchAngles.map((angle) => (
                              <span
                                key={`${branch.branch_id}-${angle}`}
                                className={angle === 'face_detail' ? 'pill purpose-face-detail' : 'pill pill-ghost'}
                              >
                                {angle}
                              </span>
                            ))}
                          </div>
                          {branchImageGroups.faceDetail.length ? (
                            <section className="task-detail-section">
                              <div className="section-header compact">
                                <h4>面部細節圖</h4>
                                <span className="pill">{branchImageGroups.faceDetail.length}</span>
                              </div>
                              <div className="image-grid task-detail-image-grid">
                                {branchImageGroups.faceDetail.map((item, index) => (
                                  <a
                                    key={`${branch.branch_id}-${item.path || index}`}
                                    className={`image-card ${item.angle === 'face_detail' ? 'face-detail-priority' : ''}`}
                                    href={item.src}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    <img src={item.src} alt={item.angle || item.note || `branch-image-${index + 1}`} loading="lazy" />
                                    <div className="image-meta">
                                      <strong>{item.angle || item.note || `image-${index + 1}`}</strong>
                                      <span>{item.summary || item.path}</span>
                                    </div>
                                  </a>
                                ))}
                              </div>
                            </section>
                          ) : null}
                          {branchImageGroups.otherAngles.length ? (
                            <section className="task-detail-section">
                              <div className="section-header compact">
                                <h4>其他角度圖</h4>
                                <span className="pill">{branchImageGroups.otherAngles.length}</span>
                              </div>
                              <div className="image-grid task-detail-image-grid">
                                {branchImageGroups.otherAngles.map((item, index) => (
                                  <a
                                    key={`${branch.branch_id}-other-${item.path || index}`}
                                    className="image-card"
                                    href={item.src}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    <img src={item.src} alt={item.angle || item.note || `branch-image-${index + 1}`} loading="lazy" />
                                    <div className="image-meta">
                                      <strong>{item.angle || item.note || `image-${index + 1}`}</strong>
                                      <span>{item.summary || item.path}</span>
                                    </div>
                                  </a>
                                ))}
                              </div>
                            </section>
                          ) : null}
                          {branchPrompt || branchNegativePrompt ? (
                            <div className="task-detail-grid">
                              {branchPrompt ? (
                                <section className="task-detail-section">
                                  <div className="section-header compact">
                                    <h4>Prompt</h4>
                                  </div>
                                  <pre className="layer-preview queue-preview-block">{branchPrompt}</pre>
                                </section>
                              ) : null}
                              {branchNegativePrompt ? (
                                <section className="task-detail-section">
                                  <div className="section-header compact">
                                    <h4>Negative Prompt</h4>
                                  </div>
                                  <pre className="layer-preview queue-preview-block">{branchNegativePrompt}</pre>
                                </section>
                              ) : null}
                            </div>
                          ) : null}
                          {Object.keys(branchParams).length ? (
                            <section className="task-detail-section">
                              <div className="section-header compact">
                                <h4>演化參數</h4>
                              </div>
                              <pre className="layer-preview queue-preview-block">{safeJson(branchParams)}</pre>
                            </section>
                          ) : null}
                          <div className="task-detail-grid task-detail-grid--meta">
                            <section className="task-detail-section">
                              <div className="section-header compact">
                                <h4>分支摘要</h4>
                              </div>
                              <div className="task-meta-stack">
                                <div className="task-meta-row">
                                  <span>分支類型</span>
                                  <strong>{branchTypeLabel(branch.kind, branchPurposeValue)}</strong>
                                </div>
                                <div className="task-meta-row">
                                  <span>狀態</span>
                                  <strong>{statusDisplay(branchStatus)}</strong>
                                </div>
                                <div className="task-meta-row">
                                  <span>工作流</span>
                                  <strong>{branchWorkflow}</strong>
                                </div>
                                <div className="task-meta-row task-meta-row-block">
                                  <span>說明</span>
                                  <strong>{branchWorkflowDescription}</strong>
                                </div>
                                <div className="task-meta-row">
                                  <span>角度</span>
                                  <strong>{branchAngles.join(', ') || '-'}</strong>
                                </div>
                                <div className="task-meta-row">
                                  <span>最後更新</span>
                                  <strong>{formatDateTime(branch.updated_at)}</strong>
                                </div>
                                <div className="task-meta-row task-meta-row-block">
                                  <span>簡要摘要</span>
                                  <strong>{branchSummary(branch)}</strong>
                                </div>
                                {branch.purpose_summary ? (
                                  <div className="task-meta-row task-meta-row-block">
                                    <span>用途摘要</span>
                                    <strong>{branch.purpose_summary}</strong>
                                  </div>
                                ) : null}
                              </div>
                            </section>
                            <section className="task-detail-section">
                              <div className="section-header compact">
                                <h4>分支路徑</h4>
                              </div>
                              <div className="task-meta-stack">
                                {branch.record_path ? (
                                  <div className="task-meta-row">
                                    <span>record</span>
                                    <strong>{branch.record_path}</strong>
                                  </div>
                                ) : null}
                                {branch.images_index_path ? (
                                  <div className="task-meta-row">
                                    <span>images index</span>
                                    <strong>{branch.images_index_path}</strong>
                                  </div>
                                ) : null}
                                {branch.response_path ? (
                                  <div className="task-meta-row">
                                    <span>response</span>
                                    <strong>{branch.response_path}</strong>
                                  </div>
                                ) : null}
                                {branch.manifest_path ? (
                                  <div className="task-meta-row">
                                    <span>manifest</span>
                                    <strong>{branch.manifest_path}</strong>
                                  </div>
                                ) : null}
                              </div>
                            </section>
                          </div>
                          {branch.result_url ? (
                            <div className="button-row compact">
                              <a className="ghost link-button" href={`${apiBase}${branch.result_url}`} target="_blank" rel="noreferrer">
                                查看結果
                              </a>
                            </div>
                          ) : null}
                          {branch.asset_paths?.length ? (
                            <section className="task-detail-section">
                              <div className="section-header compact">
                                <h4>資產清單</h4>
                              </div>
                              <pre className="layer-preview queue-preview-block">{safeJson(branch.asset_paths)}</pre>
                            </section>
                          ) : null}
                        </div>
                      </details>
                      )
                    })}
                  </div>
                ) : (
                  <div className="empty-state small">目前還沒有衍生分支。</div>
                )}
              </>
            )}
          </section>

          <pre className="layer-preview">{JSON.stringify(asRecord(draft[layer]), null, 2)}</pre>

          <label className="slider-field">
            <span>IP-Adapter weight：{sliderValues.ipAdapter.toFixed(2)}</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={sliderValues.ipAdapter}
              onChange={(event) =>
                setDraft(setNestedNumber(draft, '_style', 'ip_adapter_weight', Number(event.target.value)))
              }
            />
          </label>
          <label className="slider-field">
            <span>gender_spectrum：{sliderValues.gender.toFixed(2)}</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={sliderValues.gender}
              onChange={(event) =>
                setDraft(setNestedNumber(draft, '_identity', 'gender_spectrum', Number(event.target.value)))
              }
            />
          </label>
          <label className="slider-field">
            <span>face threshold：{sliderValues.face.toFixed(2)}</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={sliderValues.face}
              onChange={(event) =>
                setDraft(setNestedNumber(draft, '_identity', 'face_threshold', Number(event.target.value)))
              }
            />
          </label>
          <label className="slider-field">
            <span>head_tilt：{sliderValues.tilt.toFixed(2)}</span>
            <input
              type="range"
              min={-1}
              max={1}
              step={0.01}
              value={sliderValues.tilt}
              onChange={(event) => setDraft(setNestedNumber(draft, '_pose', 'head_tilt', Number(event.target.value)))}
            />
          </label>

          <label className="field">
            <span>衝突策略</span>
            <select value={conflictStrategy} onChange={(event) => setConflictStrategy(event.target.value as ConflictStrategy)}>
              <option value="create_new">create_new</option>
              <option value="merge">merge</option>
              <option value="overwrite">overwrite</option>
            </select>
          </label>

          <div className="button-row compact">
            <button className="primary" onClick={() => void saveDraft()} disabled={!selectedCharacter || busy}>
              儲存護照
            </button>
            <button className="secondary" onClick={() => void exportCharpass()} disabled={!selectedCharacter || busy}>
              導出 .charpass
            </button>
            <button className="ghost" onClick={() => importInputRef.current?.click()} disabled={busy}>
              導入 .charpass
            </button>
          </div>
          <input
            ref={importInputRef}
            type="file"
            accept=".charpass,application/x-narratron-charpass"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) {
                void importCharpass(file)
              }
              event.target.value = ''
            }}
          />
        </>
      )}
    </div>
  )
}
