/**
 * Session 관련 타입 정의
 */

export interface Session {
  session_id: string
  query: string
  status: 'running' | 'completed' | 'failed'
  created_at: string
  completed_at?: string
  event_count: number
  error?: string
}

export interface SessionEvent {
  type: string
  content: string
  metadata?: any
  timestamp?: string
}

export interface StreamEventData {
  type: 'start' | 'thought' | 'action' | 'observation' | 'final_answer' | 'end' | 'error' | 'token'
  content?: string
  message?: string
  tool?: string
  tool_input?: any
  tool_result?: any
  tool_output?: any
  error?: string
  query?: string
  metadata?: any
}

export interface ConnectionState {
  connected: boolean
  reconnecting: boolean
  reconnectAttempts: number
  lastError?: string
}
