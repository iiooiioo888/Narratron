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
  priority: number
  error_message?: string | null
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

function imageAssetPath(source: unknown): string {
  const item = asRecord(source)
  return firstNonEmptyString(item.final_asset_path, item.asset_path, item.path)
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
  if (Object.keys(imageGeneration).length) {
    return imageGeneration
  }
  return resultMetadata
}

function mergedQueueImages(payload: Record<string, unknown>): unknown[] {
  const bucket = new Map<string, unknown>()

  const register = (source: unknown, forcedAngle?: string) => {
    const item = asRecord(source)
    const assetPath = imageAssetPath(item)
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

function queueImageCollections(payload: Record<string, unknown>): unknown[] {
  return mergedQueueImages(payload)
}

function taskPreviewMetadata(task: QueueTask): Record<string, string> {
  const imageGen = taskImagePayload(task)
  const detailImages = taskDetailImages('', task)
  const detailPaths = detailImages.map((item) => item.path).filter(Boolean)
  const faceDetailByAngle = asArray(asRecord(imageGen.images_by_angle).face_detail)
  const faceDetailAssetPath = firstNonEmptyString(
    imageGen.face_detail_asset_path,
    asRecord(faceDetailByAngle[0]).final_asset_path,
    asRecord(faceDetailByAngle[0]).asset_path,
    asRecord(asArray(imageGen.face_detail_images)[0]).final_asset_path,
    asRecord(asArray(imageGen.face_detail_images)[0]).asset_path,
    detailImages.find((item) => item.angle === 'face_detail')?.path,
    detailPaths.find((path) => path.includes('face_detail')),
  )
  const thumbnailAssetPath = firstNonEmptyString(
    faceDetailAssetPath,
    imageGen.thumbnail_asset_path,
    asRecord(imageGen.thumbnail_image).final_asset_path,
    asRecord(imageGen.thumbnail_image).asset_path,
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
    if (reviewStatus === 'accepted') return 0
    if (reviewStatus === 'pending') return 1
    if (effectiveTaskStatus(task) === 'ready') return 2
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
    if (taskReviewStatus(task) === 'rejected') {
      continue
    }
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

function hasPendingAccept(task: QueueTask): boolean {
  return normalizeStatus(task.status) === 'ready' && taskReviewStatus(task) === 'pending'
}

function stopSummaryToggle(event: React.MouseEvent<HTMLElement>) {
  event.preventDefault()
  event.stopPropagation()
}

function reviewStatusLabel(task: QueueTask): string | null {
  const status = taskReviewStatus(task)
  if (!status) {
    return null
  }
  if (status === 'pending') return '待接受'
  if (status === 'accepted') return '已接受'
  if (status === 'rejected') return '已拒絕'
  return status
}

interface QueueStats {
  total_pending: number
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
      review.status ??
        imageGen.review_status ??
        asRecord(task.result_metadata).review_status ??
        task.review_status ??
        '',
    ),
  )
}

function effectiveTaskStatus(task: QueueTask): string {
  const explicit = normalizeStatus(firstNonEmptyString(task.effective_status))
  if (explicit) {
    return explicit
  }
  const reviewStatus = taskReviewStatus(task)
  if (reviewStatus === 'accepted' || reviewStatus === 'rejected') {
    return reviewStatus
  }
  return normalizeStatus(task.status) || reviewStatus || 'pending'
}

function branchEffectiveStatus(branch: VersionBranchItem): string {
  const explicit = normalizeStatus(firstNonEmptyString(branch.effective_status))
  if (explicit) {
    return explicit
  }
  const reviewStatus = normalizeStatus(branch.review_status)
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

function statusLabel(value?: string): string {
  const status = normalizeStatus(value)
  if (status === 'pending') return '待處理'
  if (status === 'accepted') return '已接受'
  if (status === 'rejected') return '已拒絕'
  if (status === 'failed') return '失敗'
  if (status === 'ready') return '待審核'
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

function branchSummary(branch: VersionBranchItem): string {
  if (branch.summary) {
    return summarizeText(branch.summary, '尚無額外摘要', 180)
  }
  const summaryFields = branchSummaryFields(branch)
  const inlineSummary = firstNonEmptyString(summaryFields.summary, summaryFields.status_summary, summaryFields.purpose)
  if (inlineSummary) {
    return summarizeText(inlineSummary, '尚無額外摘要', 180)
  }
  const parts: string[] = []
  const purpose = branchPurpose(branch)
  if (purpose) {
    parts.push(`${purposeLabel(purpose)} 分支`)
  }
  const sortedAngles = sortAngles((branch.angles ?? []).map((item) => String(item)))
  if (sortedAngles.length) {
    parts.push(sortedAngles.join(', '))
  }
  if (branch.asset_paths?.length) {
    parts.push(`${branch.asset_paths.length} 張圖`)
  }
  if (branch.job_id) {
    parts.push(`job ${String(branch.job_id).slice(0, 8)}`)
  }
  return parts.join(' · ') || '尚無額外摘要'
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
    `狀態 ${statusLabel(branchStatus)}`,
  ].filter(Boolean)
}

function responseSummary(task: QueueTask): string {
  const imageGen = taskImageGeneration(task)
  const provider = firstNonEmptyString(imageGen.provider)
  const model = firstNonEmptyString(imageGen.model)
  const purpose = firstNonEmptyString(imageGen.purpose)
  const imageCount = queueImageCollections(imageGen).length
  const parts = [
    purpose ? `用途 ${purpose}` : '',
    provider ? `provider ${provider}` : '',
    model ? `model ${model}` : '',
    imageCount ? `${imageCount} 張輸出` : '',
  ].filter(Boolean)
  return parts.join(' · ') || '目前沒有回應摘要'
}

function responseDetailSummary(task: QueueTask): string {
  const imageGen = taskImageGeneration(task)
  const review = asRecord(imageGen.review)
  const revisedPrompt = summarizeText(imageGen.revised_prompt, '', 120)
  const detailSummary = summarizeText(imageGen.summary, '', 120)
  const parts = [
    responseSummary(task),
    review.status ? `review ${String(review.status).trim()}` : '',
    revisedPrompt ? `revised ${revisedPrompt}` : '',
    detailSummary || '',
  ].filter(Boolean)
  return parts.join(' · ') || '目前沒有更詳細的回應摘要'
}

function responseSummaryRows(task: QueueTask): Array<{ label: string; value: string }> {
  const imageGen = taskImageGeneration(task)
  const review = asRecord(imageGen.review)
  return [
    { label: '摘要', value: responseDetailSummary(task) },
    { label: 'Provider', value: firstNonEmptyString(imageGen.provider) || '-' },
    { label: 'Model', value: firstNonEmptyString(imageGen.model) || '-' },
    { label: '用途', value: firstNonEmptyString(imageGen.purpose) || '-' },
    { label: 'Review', value: firstNonEmptyString(review.status, imageGen.review_status) || '-' },
    {
      label: '輸出數',
      value: String(taskDetailImages('', task).length || queueImageCollections(imageGen).length || 0),
    },
  ]
}

function taskParamSummary(task: QueueTask): string {
  const params = asRecord(task.evolution_params)
  const parts = [
    params.seed != null ? `seed ${String(params.seed)}` : '',
    params.steps != null ? `${String(params.steps)} steps` : '',
    params.guidance_scale != null ? `cfg ${String(params.guidance_scale)}` : '',
    params.width != null && params.height != null ? `${String(params.width)}x${String(params.height)}` : '',
  ].filter(Boolean)
  return parts.join(' · ') || '使用預設參數'
}

function taskDetailSections(task: QueueTask): string[] {
  const sections: string[] = []
  const detailImages = taskDetailImages('', task)
  if (taskHeroImage('', task, detailImages)) sections.push('面部細節圖')
  if (detailImages.some((item) => item.angle !== 'face_detail')) sections.push('其他角度圖')
  if (promptText(task)) sections.push('Prompt')
  if (negativePromptText(task)) sections.push('Negative')
  if (Object.keys(asRecord(task.evolution_params)).length) sections.push('參數')
  if (task.error_message) sections.push('錯誤')
  sections.push('回應摘要')
  return sections
}

function parseAnglesSummary(value?: string): string[] {
  return String(value ?? '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function promptText(task: QueueTask): string {
  const imageGen = taskImageGeneration(task)
  return firstNonEmptyString(
    imageGen.prompt,
    imageGen.final_prompt,
    imageGen.revised_prompt,
    asRecord(task.result_metadata).prompt,
  )
}

function negativePromptText(task: QueueTask): string {
  const imageGen = taskImageGeneration(task)
  return firstNonEmptyString(imageGen.negative_prompt, asRecord(task.result_metadata).negative_prompt)
}

function detailImageGroups(images: TaskImageDetail[]): { faceDetail: TaskImageDetail[]; otherAngles: TaskImageDetail[] } {
  return {
    faceDetail: images.filter((item) => item.angle === 'face_detail'),
    otherAngles: images.filter((item) => item.angle !== 'face_detail'),
  }
}

function taskDetailImages(apiBase: string, task: QueueTask): TaskImageDetail[] {
  const imageGen = taskImageGeneration(task)
  const bucket = new Map<string, TaskImageDetail>()

  const registerImage = (source: unknown, forcedAngle?: string) => {
    const item = asRecord(source)
    const assetPath = imageAssetPath(item)
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

  for (const image of mergedQueueImages(imageGen)) {
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
  const imageGen = taskImageGeneration(task)
  const faceDetailAssetPath = String(
    firstNonEmptyString(
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
  const imageGen = taskImageGeneration(task)
  const taskPreview = taskPreviewMetadata(task)
  const thumbnailAssetPath = firstNonEmptyString(
    taskPreview.face_detail_asset_path,
    taskPreview.thumbnail_asset_path,
    imageGen.face_detail_asset_path,
    imageGen.thumbnail_asset_path,
    asRecord(imageGen.thumbnail_image).final_asset_path,
    asRecord(imageGen.thumbnail_image).asset_path,
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
  const bucket = new Map<string, TaskImageDetail>()

  const registerImage = (source: unknown, forcedAngle?: string) => {
    const item = asRecord(source)
    const assetPath = imageAssetPath(item)
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

function taskAngleList(task: QueueTask, detailImages: TaskImageDetail[]): string[] {
  const imageGen = taskImageGeneration(task)
  const imagesByAngle = asRecord(imageGen.images_by_angle)
  const nestedAngles = Object.keys(imagesByAngle)
  const faceDetailImages = asArray(imageGen.face_detail_images)
  const directAngles = asArray(imageGen.angles).map((item) => String(item))
  return deriveAngles([
    ...directAngles,
    ...nestedAngles,
    ...(faceDetailImages.length ? ['face_detail'] : []),
    ...detailImages.map((item) => item.angle),
  ])
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
  const effectiveStatus = effectiveTaskStatus(task)
  const reviewStatus = taskReviewStatus(task)
  if (effectiveStatus === 'pending') {
    return '等待生成'
  }
  if (effectiveStatus === 'failed') {
    return '生成失敗'
  }
  if (effectiveStatus === 'accepted') {
    return '已接受並入庫'
  }
  if (effectiveStatus === 'rejected') {
    return '已拒絕，不入庫'
  }
  if (effectiveStatus === 'ready' && reviewStatus === 'pending') {
    return '待審核決定是否入庫'
  }
  if (effectiveStatus === 'ready') {
    return '候選圖已就緒'
  }
  return statusLabel(effectiveStatus)
}

function taskWorkflowHint(task: QueueTask): string {
  const effectiveStatus = effectiveTaskStatus(task)
  const reviewStatus = taskReviewStatus(task)
  if (effectiveStatus === 'pending') {
    return '任務仍在佇列中，尚未產出候選圖片。'
  }
  if (effectiveStatus === 'failed') {
    return '後端處理失敗，可先檢查錯誤訊息與參數。'
  }
  if (effectiveStatus === 'accepted') {
    return '這批圖片已確認採用，角色護照應已同步更新。'
  }
  if (effectiveStatus === 'rejected') {
    return '這批圖片被標記為拒絕，不會寫回角色護照。'
  }
  if (effectiveStatus === 'ready' && reviewStatus === 'pending') {
    return '圖片已生成完成，但還需要人工接受或拒絕。'
  }
  if (effectiveStatus === 'ready') {
    return '圖片可供檢視，目前無需額外操作。'
  }
  return '目前無需額外操作。'
}

function branchWorkflowLabel(branch: VersionBranchItem): string {
  const effectiveStatus = branchEffectiveStatus(branch)
  const reviewStatus = normalizeStatus(branch.review_status)
  if (effectiveStatus === 'pending') {
    return '等待生成'
  }
  if (effectiveStatus === 'failed') {
    return '分支生成失敗'
  }
  if (effectiveStatus === 'accepted') {
    return '分支已接受'
  }
  if (effectiveStatus === 'rejected') {
    return '分支已拒絕'
  }
  if (effectiveStatus === 'ready' && reviewStatus === 'pending') {
    return '待審核決定是否採用'
  }
  if (effectiveStatus === 'ready') {
    return '候選分支已就緒'
  }
  return statusLabel(effectiveStatus)
}

function branchWorkflowHint(branch: VersionBranchItem): string {
  const effectiveStatus = branchEffectiveStatus(branch)
  const reviewStatus = normalizeStatus(branch.review_status)
  if (effectiveStatus === 'pending') {
    return '分支仍在等待後端生成，尚未產出可檢視圖片。'
  }
  if (effectiveStatus === 'failed') {
    return '分支生成失敗，可回頭檢查輸出與後端記錄。'
  }
  if (effectiveStatus === 'accepted') {
    return '這個分支已被採用，可視為目前有效候選結果。'
  }
  if (effectiveStatus === 'rejected') {
    return '這個分支已被標記拒絕，保留作記錄但不建議採用。'
  }
  if (effectiveStatus === 'ready' && reviewStatus === 'pending') {
    return '圖片已生成完成，但仍待人工審核是否接受。'
  }
  if (effectiveStatus === 'ready') {
    return '候選分支可直接檢視，目前沒有額外待辦。'
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
  const [purpose, setPurpose] = useState('identity')
  const [provider, setProvider] = useState('wan')
  const [model, setModel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [extraPrompt, setExtraPrompt] = useState('')
  const [queueStatusFilter, setQueueStatusFilter] = useState('')
  const [queueOnlySelected, setQueueOnlySelected] = useState(true)
  const [layer, setLayer] = useState<CharpassLayer>('_identity')
  const [conflictStrategy, setConflictStrategy] = useState<ConflictStrategy>('merge')
  const [focused, setFocused] = useState(false)
  const [busy, setBusy] = useState(false)
  const importInputRef = useRef<HTMLInputElement | null>(null)

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
      params.set('limit', '100')
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
    } catch (queueError) {
      onError(queueError instanceof Error ? queueError.message : '載入佇列失敗')
    } finally {
      setQueueBusy(false)
    }
  }

  useEffect(() => {
    void loadQueueTasks({ keepError: true })
  }, [apiBase, selectedCharacter?.id, queueStatusFilter, queueOnlySelected])

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

  async function queueImageGeneration() {
    if (!selectedCharacter) {
      return
    }
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
          purpose,
          provider: provider || null,
          model: model || null,
          base_url: baseUrl || null,
          extra: extraPrompt,
          multi_angle: true,
          persist: true,
          priority: 0,
        }),
      })
      if (!response.ok) {
        throw new Error((await response.text()) || `HTTP ${response.status}`)
      }
      await loadQueueTasks()
      await loadCharacterSummaries()
    } catch (queueError) {
      onError(queueError instanceof Error ? queueError.message : '建立生圖佇列任務失敗')
    } finally {
      setImageBusy(false)
    }
  }

  async function processTask(taskId: number) {
    setQueueBusy(true)
    onError(null)
    try {
      const response = await fetch(`${apiBase}/api/v1/admin/queue-tasks/${taskId}/process`, {
        method: 'POST',
      })
      if (!response.ok) {
        throw new Error((await response.text()) || `HTTP ${response.status}`)
      }
      const body = (await response.json()) as { task?: QueueTask }
      const task = body.task
      if (task && selectedCharacter && String(task.core_id) === selectedCharacter.id) {
        await reloadCharacterCharpass(selectedCharacter.id)
      }
      await loadQueueTasks({ keepError: true })
      await loadCharacterSummaries()
    } catch (taskError) {
      onError(taskError instanceof Error ? taskError.message : '處理任務失敗')
    } finally {
      setQueueBusy(false)
    }
  }

  async function reviewTask(taskId: number, accepted: boolean) {
    setQueueBusy(true)
    onError(null)
    try {
      const action = accepted ? 'accept' : 'reject'
      const response = await fetch(`${apiBase}/api/v1/admin/queue-tasks/${taskId}/${action}`, {
        method: 'POST',
      })
      if (!response.ok) {
        throw new Error((await response.text()) || `HTTP ${response.status}`)
      }
      const body = (await response.json()) as { task?: QueueTask }
      const task = body.task
      if (task && selectedCharacter && String(task.core_id) === selectedCharacter.id) {
        await reloadCharacterCharpass(selectedCharacter.id)
      }
      await loadQueueTasks({ keepError: true })
      await loadCharacterSummaries()
    } catch (taskError) {
      onError(taskError instanceof Error ? taskError.message : '審核任務失敗')
    } finally {
      setQueueBusy(false)
    }
  }

  async function processNextTask() {
    setQueueBusy(true)
    onError(null)
    try {
      const response = await fetch(`${apiBase}/api/v1/admin/queue-tasks/process-next`, {
        method: 'POST',
      })
      if (!response.ok) {
        throw new Error((await response.text()) || `HTTP ${response.status}`)
      }
      const body = (await response.json()) as { task?: QueueTask | null }
      const task = body.task
      if (task && selectedCharacter && String(task.core_id) === selectedCharacter.id) {
        await reloadCharacterCharpass(selectedCharacter.id)
      }
      await loadQueueTasks({ keepError: true })
      await loadCharacterSummaries()
    } catch (taskError) {
      onError(taskError instanceof Error ? taskError.message : '處理下一筆任務失敗')
    } finally {
      setQueueBusy(false)
    }
  }

  async function processAllTasks() {
    setQueueBusy(true)
    onError(null)
    try {
      const response = await fetch(`${apiBase}/api/v1/admin/queue-tasks/process-all?limit=100`, {
        method: 'POST',
      })
      if (!response.ok) {
        throw new Error((await response.text()) || `HTTP ${response.status}`)
      }
      const body = (await response.json()) as { tasks?: QueueTask[] }
      const touchedCurrent = Boolean(
        selectedCharacter &&
          (body.tasks || []).some((task) => String(task.core_id) === selectedCharacter.id),
      )
      if (touchedCurrent && selectedCharacter) {
        await reloadCharacterCharpass(selectedCharacter.id)
      }
      await loadQueueTasks({ keepError: true })
      await loadCharacterSummaries()
    } catch (taskError) {
      onError(taskError instanceof Error ? taskError.message : '批次處理任務失敗')
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

          <div className="inset-panel image-queue-panel">
            <div className="section-header compact">
              <h4>AI 生圖佇列</h4>
              <span className="pill">{selectedCharacter ? `角色 #${selectedCharacter.id}` : '未選角色'}</span>
            </div>
            <div className="inline-grid queue-form-grid">
              <label className="field">
                <span>用途</span>
                <select value={purpose} onChange={(event) => setPurpose(event.target.value)}>
                  <option value="identity">identity</option>
                  <option value="face_detail">face_detail</option>
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
                排入生圖任務
              </button>
              <button className="ghost" onClick={() => void copyPrompt()} disabled={!lastGeneratedPrompt}>
                複製最新提示詞
              </button>
            </div>
          </div>

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
                      const branchReviewLabel =
                        branchReviewStatus === 'pending'
                          ? '待接受'
                          : branchReviewStatus === 'accepted'
                            ? '已接受'
                            : branchReviewStatus === 'rejected'
                              ? '已拒絕'
                              : branchReviewStatus || ''
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
                                  <span className={statusBadgeClass(branchStatus)}>{statusLabel(branchStatus)}</span>
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

          <section className="queue-panel">
            <div className="section-header compact">
              <h4>任務面板</h4>
              <div className="status-strip">
                <span className="pill">
                  {queueData?.storage_mode === 'database' ? 'PostgreSQL' : queueData?.storage_mode === 'local' ? '本機 JSON' : '未載入'}
                </span>
                <span className="pill">pending {queueData?.stats.total_pending ?? 0}</span>
                <span className="pill">ready {queueData?.stats.total_ready ?? 0}</span>
                <span className="pill">failed {queueData?.stats.total_failed ?? 0}</span>
                <span className="pill">shown {filteredQueueTasks.length}</span>
              </div>
            </div>
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
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={queueOnlySelected}
                  onChange={(event) => setQueueOnlySelected(event.target.checked)}
                />
                <span>只看目前角色</span>
              </label>
              <div className="button-row compact">
                <button className="ghost" onClick={() => void loadQueueTasks()} disabled={queueBusy}>
                  刷新
                </button>
                <button className="secondary" onClick={() => void processNextTask()} disabled={queueBusy}>
                  生成下一筆候選圖（未入庫）
                </button>
                <button className="primary" onClick={() => void processAllTasks()} disabled={queueBusy}>
                  批次生成候選圖（未入庫）
                </button>
              </div>
            </div>
            <p className="task-inline-summary subtle queue-toolbar-note">
              `生成` 只會產出候選圖片、暫存資產與待審核分支；只有 `接受入庫` 才會正式寫回角色護照與角色清單縮圖。
            </p>
            {filteredQueueTasks.length ? (
              <div className="queue-task-list">
                {filteredQueueTasks.map((task) => {
                  const imageGen = taskImageGeneration(task)
                  const detailImages = taskDetailImages(apiBase, task)
                  const angleList = taskAngleList(task, detailImages)
                  const heroImage = taskHeroImage(apiBase, task, detailImages)
                  const galleryImages = detailImages.filter(
                    (item) =>
                      `${item.path || item.uri}::${item.angle || ''}` !==
                      `${heroImage?.path || heroImage?.uri || ''}::${heroImage?.angle || ''}`,
                  )
                  const imageGroups = detailImageGroups(galleryImages)
                  const assetPaths = [...new Set(detailImages.map((item) => item.path).filter(Boolean))]
                  const reviewLabel = reviewStatusLabel(task)
                  const reviewStatus = taskReviewStatus(task)
                  const effectiveStatus = effectiveTaskStatus(task)
                  const workflowLabel = taskWorkflowLabel(task)
                  const workflowHint = taskWorkflowHint(task)
                  const detailSectionLabels = taskDetailSections(task)
                  const characterSummary = characterSummaries[String(task.core_id)]
                  const characterName = task.character_name || characterSummary?.name || `角色 ${task.core_id}`
                  const characterThumbnailSrc = taskThumbnailSrc(apiBase, task, detailImages, characterSummary)
                  const headline = `${purposeLabel(String(imageGen.purpose ?? '').trim() || task.status)} · ${
                    characterName
                  }`
                  return (
                    <details key={task.id} className={`queue-task-card task-disclosure status-panel-${effectiveStatus}`}>
                      <summary className="task-summary">
                        <div className="task-summary-layout">
                          {characterThumbnailSrc ? (
                            <a
                              className="task-summary-thumb"
                              href={characterThumbnailSrc}
                              target="_blank"
                              rel="noreferrer"
                              onClick={stopSummaryToggle}
                              onMouseDown={(event) => event.stopPropagation()}
                            >
                              <img src={characterThumbnailSrc} alt={characterName} loading="lazy" />
                            </a>
                          ) : null}
                          <div className="task-summary-main">
                            <div className="task-summary-title-row">
                              <div className="task-summary-heading">
                                <strong>#{task.id} · {headline}</strong>
                                <span className="task-summary-subtitle">{workflowLabel}</span>
                              </div>
                              <div className="task-status-group">
                                <span className={statusBadgeClass(effectiveStatus)}>{statusLabel(effectiveStatus)}</span>
                                <span className={purposeBadgeClass(String(imageGen.purpose ?? '').trim() || 'identity')}>
                                  {purposeLabel(String(imageGen.purpose ?? '').trim() || 'identity')}
                                </span>
                                {reviewLabel ? (
                                  <span className={statusBadgeClass(reviewStatus || 'ready')}>審核 {reviewLabel}</span>
                                ) : null}
                              </div>
                            </div>
                            <div className="queue-task-meta">
                              <span>priority {task.priority}</span>
                              <span>{formatDateTime(task.created_at)}</span>
                              <span>hash {(task.variant_hash || '').slice(0, 16)}...</span>
                            </div>
                            <p className="task-inline-summary">
                              {detailImages.length
                                ? `${heroImage?.angle === 'face_detail' ? 'face_detail 優先' : '已含圖片'} · ${detailImages.length} 張`
                                : responseSummary(task)}
                              {angleList.length ? ` · ${angleList.join(', ')}` : ''}
                            </p>
                            <div className="task-summary-overview">
                              <span className="summary-outline-pill">{taskParamSummary(task)}</span>
                              <span className="summary-outline-pill">{workflowHint}</span>
                              {detailSectionLabels.length ? (
                                <span className="summary-outline-pill">詳情含 {detailSectionLabels.join(' / ')}</span>
                              ) : null}
                            </div>
                            {angleList.length ? (
                              <div className="task-chip-row task-chip-row-tight">
                                {angleList.map((angle) => (
                                  <span
                                    key={`${task.id}-summary-angle-${angle}`}
                                    className={angle === 'face_detail' ? 'pill purpose-face-detail' : 'pill pill-ghost'}
                                  >
                                    {angle}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                          </div>
                          <div className="task-summary-actions" onClick={(event) => event.stopPropagation()}>
                            {task.status === 'pending' ? (
                              <button
                                className="secondary"
                                onClick={(event) => {
                                  stopSummaryToggle(event)
                                  void processTask(task.id)
                                }}
                                onMouseDown={(event) => event.stopPropagation()}
                                disabled={queueBusy}
                              >
                                生成候選圖（未入庫）
                              </button>
                            ) : null}
                            {task.result_url ? (
                              <a
                                className="ghost link-button"
                                href={`${apiBase}${task.result_url}`}
                                target="_blank"
                                rel="noreferrer"
                                onClick={stopSummaryToggle}
                                onMouseDown={(event) => event.stopPropagation()}
                              >
                                查看結果
                              </a>
                            ) : null}
                            {hasPendingAccept(task) ? (
                              <>
                                <button
                                  className="primary"
                                  onClick={(event) => {
                                    stopSummaryToggle(event)
                                    void reviewTask(task.id, true)
                                  }}
                                  onMouseDown={(event) => event.stopPropagation()}
                                  disabled={queueBusy}
                                >
                                  接受入庫
                                </button>
                                <button
                                  className="ghost"
                                  onClick={(event) => {
                                    stopSummaryToggle(event)
                                    void reviewTask(task.id, false)
                                  }}
                                  onMouseDown={(event) => event.stopPropagation()}
                                  disabled={queueBusy}
                                >
                                  拒絕
                                </button>
                              </>
                            ) : null}
                          </div>
                        </div>
                      </summary>
                      <div className="task-detail-content">
                        {heroImage ? (
                          <section className="task-detail-section">
                            <div className="section-header compact">
                              <h4>面部細節圖</h4>
                              <span className="pill purpose-face-detail">固定首圖</span>
                            </div>
                            <a
                              className="image-card task-hero-image face-detail-priority"
                              href={heroImage.src}
                              target="_blank"
                              rel="noreferrer"
                            >
                              <img src={heroImage.src} alt={heroImage.angle || heroImage.note || 'face_detail'} loading="lazy" />
                              <div className="image-meta">
                                <strong>{heroImage.angle || heroImage.note || 'face_detail'}</strong>
                                <span>{heroImage.summary || heroImage.path || heroImage.uri}</span>
                              </div>
                            </a>
                          </section>
                        ) : null}
                        {imageGroups.faceDetail.length ? (
                          <section className="task-detail-section">
                            <div className="section-header compact">
                              <h4>更多 face_detail 圖</h4>
                              <span className="pill purpose-face-detail">{imageGroups.faceDetail.length}</span>
                            </div>
                            <div className="image-grid task-detail-image-grid">
                              {imageGroups.faceDetail.map((item, index) => (
                                <a
                                  key={`${task.id}-face-detail-${item.path || item.uri || index}`}
                                  className="image-card face-detail-priority"
                                  href={item.src}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  <img src={item.src} alt={item.angle || item.note || `task-face-detail-${index + 1}`} loading="lazy" />
                                  <div className="image-meta">
                                    <strong>{item.angle || item.note || `face-detail-${index + 1}`}</strong>
                                    <span>{item.summary || item.path || item.uri}</span>
                                  </div>
                                </a>
                              ))}
                            </div>
                          </section>
                        ) : null}
                        {imageGroups.otherAngles.length ? (
                          <section className="task-detail-section">
                            <div className="section-header compact">
                              <h4>其他角度圖</h4>
                              <span className="pill">{imageGroups.otherAngles.length}</span>
                            </div>
                            <div className="image-grid task-detail-image-grid">
                              {imageGroups.otherAngles.map((item, index) => (
                                <a
                                  key={`${task.id}-${item.path || item.uri || index}`}
                                  className="image-card"
                                  href={item.src}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  <img src={item.src} alt={item.angle || item.note || `task-image-${index + 1}`} loading="lazy" />
                                  <div className="image-meta">
                                    <strong>{item.angle || item.note || `image-${index + 1}`}</strong>
                                    <span>{item.summary || item.path || item.uri}</span>
                                  </div>
                                </a>
                              ))}
                            </div>
                          </section>
                        ) : null}
                        {promptText(task) || negativePromptText(task) ? (
                          <div className="task-detail-grid">
                            {promptText(task) ? (
                              <section className="task-detail-section">
                                <div className="section-header compact">
                                  <h4>Prompt</h4>
                                </div>
                                <pre className="layer-preview queue-preview-block">{promptText(task)}</pre>
                              </section>
                            ) : null}
                            {negativePromptText(task) ? (
                              <section className="task-detail-section">
                                <div className="section-header compact">
                                  <h4>Negative Prompt</h4>
                                </div>
                                <pre className="layer-preview queue-preview-block">{negativePromptText(task)}</pre>
                              </section>
                            ) : null}
                          </div>
                        ) : null}
                        <section className="task-detail-section">
                          <div className="section-header compact">
                            <h4>演化參數</h4>
                          </div>
                          <pre className="layer-preview queue-preview-block">{safeJson(task.evolution_params ?? {})}</pre>
                        </section>
                        {task.error_message ? (
                          <section className="task-detail-section">
                            <div className="section-header compact">
                              <h4>錯誤</h4>
                            </div>
                            <div className="error-banner">{task.error_message}</div>
                          </section>
                        ) : null}
                        <section className="task-detail-section">
                          <div className="section-header compact">
                            <h4>回應摘要</h4>
                          </div>
                          <div className="task-meta-stack">
                            {responseSummaryRows(task).map((row) => (
                              <div
                                key={`${task.id}-response-${row.label}`}
                                className={`task-meta-row ${row.label === '摘要' ? 'task-meta-row-block' : ''}`}
                              >
                                <span>{row.label}</span>
                                <strong>{row.value}</strong>
                              </div>
                            ))}
                          </div>
                          <pre className="layer-preview queue-preview-block">{safeJson(imageGen)}</pre>
                        </section>
                        <section className="task-detail-section">
                          <div className="section-header compact">
                            <h4>人物關聯</h4>
                            <span className="pill">{selectedCharacter?.id === String(task.core_id) ? '目前角色' : '跨角色任務'}</span>
                          </div>
                          <div className="task-character-card">
                            {characterThumbnailSrc ? (
                              <a className="task-character-thumb" href={characterThumbnailSrc} target="_blank" rel="noreferrer">
                                <img src={characterThumbnailSrc} alt={characterName} loading="lazy" />
                              </a>
                            ) : null}
                            <div className="task-character-meta">
                              <strong>{characterName}</strong>
                              <div className="queue-task-meta">
                                <span>角色 #{task.core_id}</span>
                                {selectedCharacter?.id === String(task.core_id) ? <span>目前選中</span> : null}
                                <span>{purposeLabel(String(imageGen.purpose ?? '').trim() || 'identity')}</span>
                              </div>
                              <div className="task-chip-row">
                                <span className={purposeBadgeClass(String(imageGen.purpose ?? '').trim() || 'identity')}>
                                  {purposeLabel(String(imageGen.purpose ?? '').trim() || 'identity')}
                                </span>
                                {angleList.map((angle) => (
                                  <span key={`${task.id}-angle-${angle}`} className="pill pill-ghost">
                                    {angle}
                                  </span>
                                ))}
                              </div>
                            </div>
                          </div>
                        </section>
                        <div className="task-detail-grid task-detail-grid--meta">
                          <section className="task-detail-section">
                            <div className="section-header compact">
                              <h4>任務摘要</h4>
                            </div>
                            <div className="task-meta-stack">
                              <div className="task-meta-row">
                                <span>工作流</span>
                                <strong>{workflowLabel}</strong>
                              </div>
                              <div className="task-meta-row task-meta-row-block">
                                <span>說明</span>
                                <strong>{workflowHint}</strong>
                              </div>
                              <div className="task-meta-row">
                                <span>狀態</span>
                                <strong>{statusLabel(effectiveStatus)}</strong>
                              </div>
                              <div className="task-meta-row">
                                <span>審核</span>
                                <strong>{reviewLabel ? `審核 ${reviewLabel}` : '尚未進入審核'}</strong>
                              </div>
                              <div className="task-meta-row">
                                <span>建立時間</span>
                                <strong>{formatDateTime(task.created_at)}</strong>
                              </div>
                              <div className="task-meta-row">
                                <span>更新時間</span>
                                <strong>{formatDateTime(task.updated_at)}</strong>
                              </div>
                              <div className="task-meta-row">
                                <span>Provider / Model</span>
                                <strong>{summarizeText(`${imageGen.provider ?? '-'} / ${imageGen.model ?? '-'}`, '-', 80)}</strong>
                              </div>
                            </div>
                          </section>
                          <section className="task-detail-section">
                            <div className="section-header compact">
                              <h4>資產與回寫</h4>
                            </div>
                            <div className="task-meta-stack">
                              <div className="task-meta-row">
                                <span>圖片數</span>
                                <strong>{detailImages.length || queueImageCollections(imageGen).length || 0}</strong>
                              </div>
                              <div className="task-meta-row">
                                <span>用途</span>
                                <strong>{purposeLabel(String(imageGen.purpose ?? '').trim() || 'identity')}</strong>
                              </div>
                              <div className="task-meta-row">
                                <span>face_detail</span>
                                <strong>{detailImages.some((item) => item.angle === 'face_detail') ? '有' : '無'}</strong>
                              </div>
                              <div className="task-meta-row">
                                <span>代表縮圖</span>
                                <strong>
                                  {firstNonEmptyString(
                                    asRecord(task.result_metadata).face_detail_asset_path,
                                    asRecord(task.result_metadata).thumbnail_asset_path,
                                    imageGen.face_detail_asset_path,
                                    imageGen.thumbnail_asset_path,
                                  ) || '-'}
                                </strong>
                              </div>
                              <div className="task-meta-row">
                                <span>寫回實體</span>
                                <strong>{String(asRecord(task.result_metadata).persist_entity_id ?? task.core_id)}</strong>
                              </div>
                              <div className="task-meta-row">
                                <span>入庫條件</span>
                                <strong>
                                  {hasPendingAccept(task)
                                    ? '待接受後才入庫'
                                    : reviewStatus === 'accepted'
                                      ? '已接受並入庫'
                                      : reviewStatus === 'rejected'
                                        ? '已拒絕，不入庫'
                                        : '尚未入庫'}
                                </strong>
                              </div>
                              <div className="task-meta-row">
                                <span>結果連結</span>
                                <strong>{task.result_url ? '可開啟' : '尚無'}</strong>
                              </div>
                            </div>
                          </section>
                        </div>
                        <section className="task-detail-section">
                          <div className="section-header compact">
                            <h4>資產路徑</h4>
                          </div>
                          <pre className="layer-preview queue-preview-block">{safeJson(assetPaths)}</pre>
                        </section>
                      </div>
                    </details>
                  )
                })}
              </div>
            ) : (
              <div className="empty-state small">目前沒有符合條件的任務。</div>
            )}

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
                    {queuePreviewItems.map((item, index) => (
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
