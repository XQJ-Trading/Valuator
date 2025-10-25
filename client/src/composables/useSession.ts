import { ref, computed } from 'vue'
import type { Message } from '../types/Message'
import type { Session, ConnectionState, StreamEventData } from '../types/Session'

export function useSession() {
  const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
  
  // State
  const query = ref('')
  const rule = ref('')
  const status = ref('준비완료')
  const loading = ref(false)
  const messages = ref<Message[]>([])
  const selectedModel = ref<string>('')
  const availableModels = ref<string[]>([])
  
  // Session state
  const currentSessionId = ref<string | null>(null)
  const activeSession = ref<Session | null>(null)
  const connectionState = ref<ConnectionState>({
    connected: false,
    reconnecting: false,
    reconnectAttempts: 0,
    lastError: undefined
  })
  
  let eventSource: EventSource | null = null
  let reconnectTimer: number | null = null
  const MAX_RECONNECT_ATTEMPTS = 3
  const RECONNECT_DELAY = 2000 // 2초

  // localStorage 관련
  const getStoredQuery = (): string => {
    try {
      return localStorage.getItem('session_query') || ''
    } catch {
      return ''
    }
  }

  const getStoredRule = (): string => {
    try {
      return localStorage.getItem('session_rule') || ''
    } catch {
      return ''
    }
  }

  query.value = getStoredQuery()
  rule.value = getStoredRule()

  const saveToStorage = () => {
    try {
      localStorage.setItem('session_query', query.value)
      localStorage.setItem('session_rule', rule.value)
    } catch (error) {
      console.warn('localStorage 저장 실패:', error)
    }
  }

  // 지원 모델 목록 가져오기
  async function fetchAvailableModels() {
    try {
      const res = await fetch(`${API_BASE}/api/v1/models`)
      const data = await res.json()
      availableModels.value = data.models || []
      if (!selectedModel.value && data.default) {
        selectedModel.value = data.default
      }
    } catch (error) {
      console.error('모델 목록을 가져오는데 실패했습니다:', error)
      availableModels.value = ['gemini-flash-latest', 'gemini-pro-latest']
      selectedModel.value = 'gemini-flash-latest'
    }
  }

  function clearAll() {
    messages.value = []
    status.value = '준비완료'
  }

  function setModel(model: string) {
    selectedModel.value = model
  }

  function buildQueryWithRule() {
    if (!rule.value.trim()) {
      return query.value
    }
    return `${query.value}\n<rule>\n${rule.value}\n</rule>`
  }

  function addMessage(type: Message['type'], content: string, metadata?: any) {
    messages.value.push({
      type,
      content,
      metadata,
      timestamp: new Date()
    })
  }

  // 세션 생성
  async function createSession() {
    if (!query.value.trim()) return

    loading.value = true
    status.value = '세션 생성중...'

    try {
      const queryWithRule = buildQueryWithRule()
      const requestBody = {
        query: queryWithRule,
        ...(selectedModel.value && { model: selectedModel.value })
      }

      const res = await fetch(`${API_BASE}/api/v1/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody)
      })

      if (!res.ok) {
        throw new Error(`HTTP error! status: ${res.status}`)
      }

      const data = await res.json()
      currentSessionId.value = data.session_id
      activeSession.value = data.session
      
      // 메시지 추가
      addMessage('start', queryWithRule, { query: queryWithRule })
      status.value = '스트리밍 연결중...'
      
      // 스트림 구독
      await subscribeToStream(data.session_id)
      
      query.value = ''
      rule.value = ''
      saveToStorage()
    } catch (e: any) {
      status.value = '오류 발생'
      addMessage('error', `세션 생성 실패: ${String(e)}`)
      loading.value = false
    }
  }

  // SSE 스트림 구독
  function subscribeToStream(sessionId: string) {
    return new Promise((resolve, reject) => {
      try {
        const streamUrl = `${API_BASE}/api/v1/sessions/${sessionId}/stream`
        
        eventSource = new EventSource(streamUrl)
        connectionState.value.connected = true
        connectionState.value.reconnecting = false
        connectionState.value.reconnectAttempts = 0
        connectionState.value.lastError = undefined

        eventSource.onopen = () => {
          console.log('Stream connected')
          connectionState.value.connected = true
          status.value = '스트리밍중...'
        }

        eventSource.onmessage = (event) => {
          try {
            const data: StreamEventData = JSON.parse(event.data)
            handleStreamEvent(data)
          } catch (err) {
            console.warn('메시지 파싱 오류:', err)
          }
        }

        eventSource.onerror = (error) => {
          console.error('Stream error:', error)
          connectionState.value.connected = false
          connectionState.value.lastError = String(error)
          
          if (eventSource?.readyState === EventSource.CLOSED) {
            // 연결이 완전히 끊김
            handleStreamDisconnect(sessionId)
          }
        }
      } catch (err) {
        reject(err)
      }
    })
  }

  // 스트림 이벤트 처리
  function handleStreamEvent(data: StreamEventData) {
    if (data.type === 'start') {
      addMessage('start', data.query || '시작', { query: data.query })
    } else if (data.type === 'end') {
      closeStream()
      addMessage('end', '완료', {})
      status.value = '완료'
      loading.value = false
    } else if (data.type === 'error') {
      addMessage('error', data.message || data.content || '알 수 없는 오류', {
        error: data.error
      })
      status.value = '오류 발생'
      closeStream()
      loading.value = false
    } else if (data.type === 'final_answer') {
      addMessage('final_answer', data.content || '', {
        metadata: data.metadata
      })
    } else if (data.type in ['thought', 'action', 'observation']) {
      addMessage(data.type as any, data.content || '', {
        tool: data.tool,
        tool_input: data.tool_input,
        tool_result: data.tool_result,
        tool_output: data.tool_output,
        error: data.error
      })
      
      // 상태 업데이트
      if (data.type === 'thought') {
        status.value = '🧠 사고중...'
      } else if (data.type === 'action') {
        status.value = `⚡ ${data.tool || '도구'} 실행중...`
      } else if (data.type === 'observation') {
        status.value = '👁️ 결과 분석중...'
      }
    }
  }

  // 스트림 연결 해제
  function closeStream() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
      connectionState.value.connected = false
    }
  }

  // 스트림 끊김 시 처리
  function handleStreamDisconnect(sessionId: string) {
    if (connectionState.value.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      status.value = '연결 실패'
      addMessage('error', '스트림 연결이 끊어졌습니다. 재연결을 시도하세요.', {})
      loading.value = false
      return
    }

    connectionState.value.reconnecting = true
    connectionState.value.reconnectAttempts += 1
    status.value = `재연결 시도 중... (${connectionState.value.reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`

    reconnectTimer = setTimeout(() => {
      console.log('Attempting to reconnect...')
      subscribeToStream(sessionId).catch((err) => {
        console.error('Reconnection failed:', err)
        if (connectionState.value.reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
          handleStreamDisconnect(sessionId)
        }
      })
    }, RECONNECT_DELAY)
  }

  // 수동 재연결
  async function reconnect() {
    if (!currentSessionId.value) return

    closeStream()
    connectionState.value.reconnectAttempts = 0
    await subscribeToStream(currentSessionId.value)
  }

  // 세션 종료
  async function terminateSession() {
    if (!currentSessionId.value) return

    try {
      closeStream()
      const res = await fetch(`${API_BASE}/api/v1/sessions/${currentSessionId.value}`, {
        method: 'DELETE'
      })

      if (!res.ok) {
        throw new Error(`HTTP error! status: ${res.status}`)
      }

      currentSessionId.value = null
      activeSession.value = null
      status.value = '세션 종료됨'
      loading.value = false
    } catch (e: any) {
      console.error('세션 종료 실패:', e)
      addMessage('error', `세션 종료 실패: ${String(e)}`)
    }
  }

  // 활성 세션 조회
  async function fetchActiveSessions() {
    try {
      const res = await fetch(`${API_BASE}/api/v1/sessions`)
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`)
      
      const data = await res.json()
      return data.sessions || []
    } catch (err) {
      console.error('활성 세션 조회 실패:', err)
      return []
    }
  }

  // 세션 상태 조회
  async function fetchSessionStatus(sessionId: string) {
    try {
      const res = await fetch(`${API_BASE}/api/v1/sessions/${sessionId}`)
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`)
      
      const data = await res.json()
      return data
    } catch (err) {
      console.error('세션 상태 조회 실패:', err)
      return null
    }
  }

  // 기존 세션에 재연결
  async function reconnectToSession(sessionId: string) {
    loading.value = true
    status.value = '세션 복구중...'

    try {
      const sessionData = await fetchSessionStatus(sessionId)
      if (!sessionData) {
        throw new Error('세션을 찾을 수 없습니다')
      }

      currentSessionId.value = sessionId
      activeSession.value = sessionData
      messages.value = []
      
      // 스트림 구독
      await subscribeToStream(sessionId)
    } catch (e: any) {
      status.value = '오류 발생'
      addMessage('error', `세션 복구 실패: ${String(e)}`)
      loading.value = false
    }
  }

  // Computed
  const isSessionActive = computed(() => currentSessionId.value !== null && connectionState.value.connected)
  const sessionProgress = computed(() => activeSession.value?.event_count || 0)

  // 초기화
  fetchAvailableModels()

  return {
    // State
    query,
    rule,
    status,
    loading,
    messages,
    selectedModel,
    availableModels,
    currentSessionId,
    activeSession,
    connectionState,
    
    // Computed
    isSessionActive,
    sessionProgress,
    
    // Methods
    clearAll,
    setModel,
    createSession,
    subscribeToStream,
    closeStream,
    terminateSession,
    reconnect,
    fetchAvailableModels,
    fetchActiveSessions,
    fetchSessionStatus,
    reconnectToSession
  }
}
