export interface TaskRewriteHistory {
  rewrite_id: string
  original_task: string
  rewritten_task: string
  model: string
  custom_prompt: string | null
  created_at: string
  metadata: Record<string, any>
}

export interface TaskRewriteRequest {
  task: string
  model?: string
  custom_prompt?: string
}

export interface TaskRewriteResponse {
  rewrite_id: string
  original_task: string
  rewritten_task: string
  model: string
  created_at: string
}

export interface TaskRewriteHistoryList {
  rewrites: TaskRewriteHistory[]
  total: number
  limit: number
  offset: number
}

