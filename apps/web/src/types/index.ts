export interface Run {
  id: string
  project_name: string
  status: string
  created_at: string
  duration_ms?: number
}

export interface Event {
  id: string
  run_id: string
  timestamp: string
  event_type: string
  payload: Record<string, any>
}

export interface DiffItem {
  path: string
  type: 'added' | 'removed' | 'changed'
  old_value?: any
  new_value?: any
}

export interface DiffResponse {
  run_a_id: string
  run_b_id: string
  differences_by_category: Record<string, DiffItem[]>
  total_differences: number
}