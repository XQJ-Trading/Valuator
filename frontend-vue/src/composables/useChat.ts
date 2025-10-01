import { ref } from 'vue'
import type { Message } from '../types/Message'

export function useChat() {
  const query = ref('')
  const rule = ref('')
  const status = ref('준비완료')
  const loading = ref(false)
  const messages = ref<Message[]>([])

  const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

  function clearAll() {
    messages.value = []
    query.value = ''
    rule.value = ''
    status.value = '준비완료'
  }

  function buildQueryWithRule() {
    if (!rule.value.trim()) {
      return query.value
    }
    return `${query.value}<rule>${rule.value}</rule>`
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
      const res = await fetch(`${API_BASE}/api/v1/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: queryWithRule }),
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
      const url = new URL(`${API_BASE}/api/v1/chat/stream`)
      url.searchParams.set('query', queryWithRule)

      const es = new EventSource(url.toString())
      let closed = false

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          
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
          } else {
            currentTokenMessage = null
            addMessage(data.type, data.content, {
              tool: data.tool,
              error: data.error,
              message: data.message
            })
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
          console.warn('메시지 파싱 오류:', err)
        }
      }

      es.addEventListener('end', () => {
        status.value = '완료'
        query.value = ''
        rule.value = ''
        if (!closed) { es.close(); closed = true }
        loading.value = false
      })

      es.onerror = () => {
        status.value = '스트림 오류'
        addMessage('error', '스트리밍 연결에 문제가 발생했습니다.')
        if (!closed) { es.close(); closed = true }
        loading.value = false
      }
    } catch (e: any) {
      status.value = '오류 발생'
      addMessage('error', `스트리밍 오류: ${String(e)}`)
      loading.value = false
    }
  }

  return {
    query,
    rule,
    status,
    loading,
    messages,
    clearAll,
    send,
    stream
  }
}
