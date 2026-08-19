import { useEffect, useMemo, useRef, useState } from 'react'

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

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function entityCharpass(entity: CharacterCard): Record<string, unknown> {
  return asRecord(asRecord(entity.payload).charpass)
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
  const [layer, setLayer] = useState<CharpassLayer>('_identity')
  const [conflictStrategy, setConflictStrategy] = useState<ConflictStrategy>('merge')
  const [focused, setFocused] = useState(false)
  const [busy, setBusy] = useState(false)
  const importInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (!selectedCharacter) {
      setDraft({})
      return
    }
    const local = entityCharpass(selectedCharacter)
    setDraft(local)
    if (!persist) {
      return
    }
    let cancelled = false
    fetch(`${apiBase}/api/v1/characters/${selectedCharacter.id}/charpass`)
      .then(async (response) => {
        if (!response.ok) {
          return
        }
        const body = (await response.json()) as { charpass?: Record<string, unknown> }
        if (!cancelled && body.charpass) {
          setDraft(body.charpass)
        }
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [apiBase, persist, selectedCharacter?.id])

  const sliderValues = useMemo(
    () => ({
      ipAdapter: nestedNumber(draft, '_style', 'ip_adapter_weight', 0.7),
      gender: nestedNumber(draft, '_identity', 'gender_spectrum', 0.5),
      face: nestedNumber(draft, '_identity', 'face_threshold', 0.7),
      tilt: nestedNumber(draft, '_pose', 'head_tilt', 0),
    }),
    [draft],
  )

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
      onPatchEntity(selectedCharacter.id, next)
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
            {characters.map((character) => (
              <button
                key={character.id}
                className={`list-item ${selectedCharacter?.id === character.id ? 'active' : ''}`}
                onClick={() => onSelect(character.id)}
              >
                <strong>{character.name || character.id}</strong>
                <span>{character.id}</span>
              </button>
            ))}
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
