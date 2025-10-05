import { ref } from 'vue'

export interface SessionSummary {
  session_id: string
  timestamp: string
  query: string
  final_answer: string
  success: boolean
  duration: number
  step_count: number
  tools_used: string[]
}

export interface SessionDetail {
  session_id: string
  timestamp: string
  query: string
  steps: any[]
  final_answer: string
  success: boolean
  duration: number
  end_time?: string
}

// 싱글톤 상태 (모든 컴포넌트에서 공유)
const sessions = ref<SessionSummary[]>([])
const currentSession = ref<SessionDetail | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

export function useHistory() {

  /**
   * 세션 목록 조회
   */
  async function fetchSessions(limit: number = 10, offset: number = 0, append: boolean = false) {
    loading.value = true
    error.value = null

    try {
      const res = await fetch(`${API_BASE}/api/v1/history?limit=${limit}&offset=${offset}`)
      
      if (!res.ok) {
        throw new Error(`Failed to fetch sessions: ${res.statusText}`)
      }

      const data = await res.json()
      
      // append가 true면 기존 목록에 추가, false면 교체
      if (append) {
        sessions.value = [...sessions.value, ...(data.sessions || [])]
      } else {
        sessions.value = data.sessions || []
      }
      
      return data
    } catch (e: any) {
      error.value = e.message
      console.error('Error fetching sessions:', e)
      return null
    } finally {
      loading.value = false
    }
  }

  /**
   * 특정 세션 상세 조회
   */
  async function fetchSessionDetail(sessionId: string) {
    loading.value = true
    error.value = null

    try {
      const res = await fetch(`${API_BASE}/api/v1/history/${sessionId}`)
      
      if (!res.ok) {
        throw new Error(`Failed to fetch session: ${res.statusText}`)
      }

      const data = await res.json()
      currentSession.value = data
      return data
    } catch (e: any) {
      error.value = e.message
      console.error('Error fetching session detail:', e)
      return null
    } finally {
      loading.value = false
    }
  }

  /**
   * 세션 재생 (SSE 스트림)
   */
  async function replaySession(
    sessionId: string,
    onEvent: (event: any) => void,
    speedMultiplier: number = 1
  ): Promise<() => void> {
    error.value = null

    try {
      const url = `${API_BASE}/api/v1/history/${sessionId}/stream`
      const es = new EventSource(url)
      let closed = false

      // 속도 조절을 위한 딜레이
      const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms / speedMultiplier))

      es.onmessage = async (event) => {
        try {
          const data = JSON.parse(event.data)
          
          // 이벤트 전달
          onEvent(data)
          
          // 타입에 따라 딜레이 추가 (자연스러운 재생을 위해)
          if (data.type !== 'start' && data.type !== 'end') {
            await delay(300) // 기본 300ms 딜레이
          }
        } catch (err) {
          console.warn('Error parsing event:', err)
        }
      }

      es.onerror = () => {
        if (!closed) {
          error.value = '스트림 연결에 문제가 발생했습니다.'
          es.close()
          closed = true
        }
      }

      // cleanup 함수 반환
      return () => {
        if (!closed) {
          es.close()
          closed = true
        }
      }
    } catch (e: any) {
      error.value = e.message
      console.error('Error replaying session:', e)
      return () => {} // noop cleanup
    }
  }


  /**
   * 세션 삭제
   */
  async function deleteSession(sessionId: string) {
    loading.value = true
    error.value = null

    try {
      const res = await fetch(`${API_BASE}/api/v1/history/${sessionId}`, {
        method: 'DELETE'
      })
      
      if (!res.ok) {
        throw new Error(`Failed to delete session: ${res.statusText}`)
      }

      // 목록에서 제거
      sessions.value = sessions.value.filter(s => s.session_id !== sessionId)
      
      return await res.json()
    } catch (e: any) {
      error.value = e.message
      console.error('Error deleting session:', e)
      return null
    } finally {
      loading.value = false
    }
  }

  return {
    sessions,
    currentSession,
    loading,
    error,
    fetchSessions,
    fetchSessionDetail,
    replaySession,
    deleteSession
  }
}
