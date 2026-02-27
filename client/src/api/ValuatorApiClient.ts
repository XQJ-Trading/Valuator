import type {
  ValuatorFinalDocument,
  ValuatorSessionSummary,
  ValuatorSnapshot,
  ValuatorTaskDetail
} from '../types/Valuator'

interface SessionsResponse {
  sessions?: ValuatorSessionSummary[]
}

interface HistoryResponse {
  sessions?: Array<{
    session_id: string
    query: string
    timestamp?: string
    success?: boolean
  }>
}

interface FinalResponse {
  session_id?: string
  markdown?: string
  content?: string
}

interface TaskDetailResponse {
  session_id?: string
  task_id?: string
  execution_markdown?: string
  aggregation_markdown?: string
  execution?: string
  aggregation?: string
  output_metadata?: Record<string, string>
}

export class ValuatorApiClient {
  private readonly apiBase: string

  constructor(apiBase: string = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000') {
    this.apiBase = apiBase
  }

  async getSessions(limit: number = 20, offset: number = 0): Promise<ValuatorSessionSummary[]> {
    const query = `limit=${limit}&offset=${offset}`

    try {
      const data = await this.fetchJson<SessionsResponse>(`/api/v1/sessions?scope=all&${query}`)
      return data.sessions || []
    } catch {
      const history = await this.fetchJson<HistoryResponse>(`/api/v1/history?${query}`)
      const sessions = history.sessions || []

      return sessions.map((session) => ({
        session_id: session.session_id,
        query: session.query,
        status: session.success ? 'completed' : 'failed',
        timestamp: session.timestamp,
        success: session.success
      }))
    }
  }

  async getSnapshot(sessionId: string): Promise<ValuatorSnapshot> {
    return this.fetchJson<ValuatorSnapshot>(`/api/v1/sessions/${sessionId}/valuator/snapshot`)
  }

  async getTaskDetail(sessionId: string, taskId: string): Promise<ValuatorTaskDetail> {
    const data = await this.fetchJson<TaskDetailResponse>(
      `/api/v1/sessions/${sessionId}/valuator/tasks/${taskId}`
    )

    return {
      session_id: data.session_id || sessionId,
      task_id: data.task_id || taskId,
      execution_markdown: data.execution_markdown || data.execution || '',
      aggregation_markdown: data.aggregation_markdown || data.aggregation || '',
      output_metadata: data.output_metadata
    }
  }

  async getFinal(sessionId: string): Promise<ValuatorFinalDocument> {
    const data = await this.fetchJson<FinalResponse>(`/api/v1/sessions/${sessionId}/valuator/final`)

    return {
      session_id: data.session_id || sessionId,
      markdown: data.markdown || data.content || ''
    }
  }

  private async fetchJson<T>(path: string): Promise<T> {
    const response = await fetch(`${this.apiBase}${path}`)
    if (!response.ok) {
      const error = new Error(`Request failed: ${response.status}`) as Error & { status?: number }
      error.status = response.status
      throw error
    }
    return response.json() as Promise<T>
  }
}
