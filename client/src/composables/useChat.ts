import { ref } from 'vue'
import type { Message } from '../types/Message'

export function useChat() {
  // localStorage에서 저장된 값 불러오기
  const getStoredQuery = (): string => {
    try {
      return localStorage.getItem('chat_query') || ''
    } catch {
      return ''
    }
  }

  const getStoredRule = (): string => {
    try {
      return localStorage.getItem('chat_rule') || ''
    } catch {
      return ''
    }
  }

  const query = ref(getStoredQuery())
  const rule = ref(getStoredRule())
  const status = ref('준비완료')
  const loading = ref(false)
  const messages = ref<Message[]>([])
  const selectedModel = ref<string>('')
  const availableModels = ref<string[]>([])

  const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

  // localStorage 저장 함수
  const saveToStorage = () => {
    try {
      localStorage.setItem('chat_query', query.value)
      localStorage.setItem('chat_rule', rule.value)
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
      // 기본값 설정
      availableModels.value = ['gemini-flash-latest', 'gemini-pro-latest']
      selectedModel.value = 'gemini-flash-latest'
    }
  }

  function clearAll() {
    messages.value = []
    status.value = '준비완료'
    // query와 rule은 유지 (입력 텍스트는 남겨둠)
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

  async function send() {
    if (!query.value.trim()) return
    
    loading.value = true
    status.value = '전송중...'
    
    try {
      const queryWithRule = buildQueryWithRule()
      const requestBody = {
        query: queryWithRule,
        ...(selectedModel.value && { model: selectedModel.value })
      }
      
      const res = await fetch(`${API_BASE}/api/v1/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      })
      const json = await res.json()
      
      addMessage('final_answer', json.response || '응답을 받지 못했습니다.')
      status.value = '완료'
      query.value = ''
      rule.value = ''
    } catch (e: any) {
      status.value = '오류 발생'
      addMessage('error', `전송 오류: ${String(e)}`)
    } finally {
      loading.value = false
    }
  }

  async function stream() {
    if (!query.value.trim()) return
    
    loading.value = true
    status.value = '스트리밍중...'
    let currentTokenMessage: Message | null = null
    
    try {
      const queryWithRule = buildQueryWithRule()
      const requestBody = {
        query: queryWithRule,
        ...(selectedModel.value && { model: selectedModel.value })
      }

      const response = await fetch(`${API_BASE}/api/v1/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('스트림을 읽을 수 없습니다.')
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          console.log(line)

          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6)
            if (dataStr.trim() === '') continue
            if (dataStr.trim() === '{}') continue

            try {
              const data = JSON.parse(dataStr)

              if (data.type === 'token') {
                if (currentTokenMessage) {
                  currentTokenMessage.content += data.content
                } else {
                  currentTokenMessage = {
                    type: 'token',
                    content: data.content,
                    timestamp: new Date()
                  }
                  messages.value.push(currentTokenMessage)
                }
              } else if (data.type === 'start') {
                currentTokenMessage = null
                addMessage('start', data.query || '시작', {
                  query: data.query
                })
              } else if (data.type === 'end') {
                currentTokenMessage = null
                addMessage('end', '완료', {})
              } else {
                currentTokenMessage = null

                // subtask_result 태그를 포함한 메시지인지 확인하고 별도 처리
                if (data.content && (data.type === 'thought' || data.type === 'observation')) {
                  const subtaskMatch = data.content.match(/<subtask_result>(.*?)<\/subtask_result>/s)
                  if (subtaskMatch) {
                    const subtaskContent = subtaskMatch[1].trim()

                    // 원본 메시지 추가 (subtask_result 제외)
                    const originalContent = data.content.replace(/<subtask_result>.*?<\/subtask_result>/s, '').trim()
                    if (originalContent) {
                      addMessage(data.type, originalContent, {
                        tool: data.tool,
                        tool_input: data.tool_input,
                        tool_output: data.tool_output,
                        error: data.error,
                        message: data.message,
                        tool_result: data.tool_result
                      })
                    }

                    // subtask_result를 별도의 메시지로 추가
                    addMessage('subtask_result', subtaskContent, {
                      source_type: data.type,
                      original_content: originalContent
                    })
                  } else {
                    // 일반 메시지 처리
                    addMessage(data.type, data.content || '', {
                      tool: data.tool,
                      tool_input: data.tool_input,
                      tool_output: data.tool_output,
                      error: data.error,
                      message: data.message,
                      tool_result: data.tool_result
                    })
                  }
                } else {
                  // 다른 타입의 메시지 처리
                  addMessage(data.type, data.content || '', {
                    tool: data.tool,
                    tool_input: data.tool_input,
                    tool_output: data.tool_output,
                    error: data.error,
                    message: data.message,
                    tool_result: data.tool_result
                  })
                }
              }
              
              // 상태 업데이트
              if (data.type === 'thought') {
                status.value = '🧠 사고중...'
              } else if (data.type === 'action') {
                status.value = `⚡ ${data.tool || '도구'} 실행중...`
              } else if (data.type === 'observation') {
                status.value = '👁️ 결과 분석중...'
              }
            } catch (err) {
              console.warn('메시지 파싱 오류:', err, 'Data:', dataStr)
            }
          } else if (line.startsWith('event: end')) {
            status.value = '완료'
            // 현재 입력값을 localStorage에 저장 (다음 접속을 위해)
            saveToStorage()
            query.value = ''
            rule.value = ''
            loading.value = false
            break
          }
        }
      }
    } catch (e: any) {
      status.value = '오류 발생'
      addMessage('error', `스트리밍 오류: ${String(e)}`)
      loading.value = false
    }
  }

  // 컴포넌트가 마운트될 때 모델 목록을 가져옴
  fetchAvailableModels()

  return {
    query,
    rule,
    status,
    loading,
    messages,
    selectedModel,
    availableModels,
    clearAll,
    send,
    stream,
    setModel,
    fetchAvailableModels
  }
}
