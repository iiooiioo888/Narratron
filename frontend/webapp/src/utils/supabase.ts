import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY

if (!supabaseUrl || !supabaseKey) {
  console.warn('[Supabase] Missing VITE_SUPABASE_URL or VITE_SUPABASE_PUBLISHABLE_KEY')
}

export const supabase = createClient(supabaseUrl ?? '', supabaseKey ?? '')

// ============================================
// Types
// ============================================

export interface UserProfile {
  id: string
  display_name: string | null
  avatar_url: string | null
  role: string
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface CharacterCore {
  id: number
  uuid: string
  user_id: string | null
  name: string
  codename: string | null
  gender_spectrum: number | null
  base_age: number
  identity_anchor: Record<string, unknown>
  tags: string[]
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface CharacterProfile {
  id: number
  core_id: number
  version: number
  is_active: boolean
  project_name: string | null
  manifest: Record<string, unknown>
  style_preset: string | null
  outfit_config: Record<string, unknown>
  created_by: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface CharacterVariant {
  id: number
  core_id: number
  profile_id: number | null
  variant_hash: string
  evolution_params: Record<string, unknown>
  status: string
  priority: number
  result_url: string | null
  result_metadata: Record<string, unknown>
  error_message: string | null
  retry_count: number
  max_retries: number
  queue_wait_ms: number | null
  generation_duration_ms: number | null
  review_status: string | null
  effective_status: string | null
  created_at: string
  updated_at: string
  started_at: string | null
}

// ============================================
// Auth helpers
// ============================================

export async function signUp(email: string, password: string, displayName?: string) {
  return supabase.auth.signUp({
    email,
    password,
    options: { data: { display_name: displayName } },
  })
}

export async function signIn(email: string, password: string) {
  return supabase.auth.signInWithPassword({ email, password })
}

export async function signOut() {
  return supabase.auth.signOut()
}

export async function getCurrentUser() {
  const { data: { user } } = await supabase.auth.getUser()
  return user
}

export async function getSession() {
  const { data: { session } } = await supabase.auth.getSession()
  return session
}

// ============================================
// Characters
// ============================================

export async function listCharacters(userId?: string) {
  let query = supabase
    .from('character_cores')
    .select('*')
    .order('created_at', { ascending: false })
  if (userId) {
    query = query.eq('user_id', userId)
  }
  return query
}

export async function getCharacter(id: number) {
  return supabase
    .from('character_cores')
    .select('*, character_profiles(*), character_variants(*)')
    .eq('id', id)
    .single()
}

export async function createCharacter(data: Partial<CharacterCore>) {
  return supabase
    .from('character_cores')
    .insert(data)
    .select()
    .single()
}

export async function updateCharacter(id: number, data: Partial<CharacterCore>) {
  return supabase
    .from('character_cores')
    .update(data)
    .eq('id', id)
    .select()
    .single()
}

export async function deleteCharacter(id: number) {
  return supabase
    .from('character_cores')
    .delete()
    .eq('id', id)
}

// ============================================
// Profiles
// ============================================

export async function getActiveProfile(coreId: number) {
  return supabase
    .from('character_profiles')
    .select('*')
    .eq('core_id', coreId)
    .eq('is_active', true)
    .order('version', { ascending: false })
    .limit(1)
    .single()
}

export async function createProfile(data: Partial<CharacterProfile>) {
  return supabase
    .from('character_profiles')
    .insert(data)
    .select()
    .single()
}

// ============================================
// Variants (Queue)
// ============================================

export async function listVariants(coreId: number, status?: string) {
  let query = supabase
    .from('character_variants')
    .select('*')
    .eq('core_id', coreId)
    .order('created_at', { ascending: false })
  if (status) {
    query = query.eq('status', status)
  }
  return query
}

export async function getQueueStats() {
  const { data, error } = await supabase
    .from('character_variants')
    .select('status')
  if (error) return { error }
  const counts: Record<string, number> = {}
  for (const row of data ?? []) {
    counts[row.status] = (counts[row.status] ?? 0) + 1
  }
  return {
    data: {
      total_pending: counts.pending ?? 0,
      total_waiting: counts.waiting ?? 0,
      total_running: counts.running ?? 0,
      total_ready: counts.ready ?? 0,
      total_failed: counts.failed ?? 0,
    },
  }
}

export async function createVariant(data: Partial<CharacterVariant>) {
  return supabase
    .from('character_variants')
    .insert(data)
    .select()
    .single()
}

export async function updateVariant(id: number, data: Partial<CharacterVariant>) {
  return supabase
    .from('character_variants')
    .update(data)
    .eq('id', id)
    .select()
    .single()
}

export async function resetFailedVariants(coreId?: number) {
  let query = supabase
    .from('character_variants')
    .update({ status: 'pending', error_message: null })
    .eq('status', 'failed')
  if (coreId) query = query.eq('core_id', coreId)
  return query.select()
}

// ============================================
// User Profile
// ============================================

export async function getProfile(userId: string) {
  return supabase
    .from('user_profiles')
    .select('*')
    .eq('id', userId)
    .single()
}

export async function updateProfile(userId: string, data: Partial<UserProfile>) {
  return supabase
    .from('user_profiles')
    .update(data)
    .eq('id', userId)
    .select()
    .single()
}
