<template>
  <div class="app-container">
    <!-- Header -->
    <header class="app-header">
      <div class="header-content">
        <h1 class="app-title">
          <span class="title-icon">🤖</span>
          AI Agent (ReAct)
        </h1>
      </div>
    </header>

    <!-- Input Section -->
    <div class="input-section">
      <div class="input-container">
        <textarea 
          v-model="query" 
          placeholder="AI에게 질문하거나 복잡한 문제를 요청해보세요..."
          class="query-input"
          @keydown.ctrl.enter="stream"
        ></textarea>
        <div class="input-controls">
          <label class="react-toggle">
            <input type="checkbox" v-model="useReact" />
            <span class="toggle-slider"></span>
            <span class="toggle-label">ReAct 모드 (단계별 사고과정)</span>
          </label>
          <div class="action-buttons">
            <button @click="send" :disabled="loading" class="btn btn-primary">
              <span v-if="loading" class="loading-spinner"></span>
              {{ loading ? '전송중...' : '전송' }}
            </button>
            <button @click="stream" :disabled="loading" class="btn btn-secondary">
              <span v-if="loading" class="loading-spinner"></span>
              {{ loading ? '스트리밍중...' : '스트림' }}
            </button>
            <button @click="clearAll" class="btn btn-outline">지우기</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Status Bar -->
    <div class="status-bar" :class="statusClass">
      <div class="status-content">
        <span class="status-icon">{{ statusIcon }}</span>
        <span class="status-text">{{ status }}</span>
        <div v-if="loading" class="progress-bar">
          <div class="progress-fill"></div>
        </div>
      </div>
    </div>

    <!-- Messages Container -->
    <div class="messages-container">
      <div v-if="messages.length === 0" class="empty-state">
        <div class="empty-icon">💭</div>
        <h3>AI Agent와 대화해보세요</h3>
        <p>복잡한 계산, 정보 검색, 코드 실행 등 다양한 작업을 요청할 수 있습니다.</p>
      </div>
      
      <div v-for="(message, index) in messages" :key="index" class="message-group">
        <div class="message-card" :class="`message-${message.type}`">
          <div class="message-header">
            <span class="message-icon">{{ getMessageIcon(message.type) }}</span>
            <span class="message-title">{{ getMessageTitle(message.type) }}</span>
            <span class="message-timestamp">{{ formatTime(message.timestamp) }}</span>
            <button @click="copyMessage(message.content)" class="copy-btn" title="복사">📋</button>
          </div>
          <div class="message-content">
            <div class="message-text" v-if="message.type === 'thought'">
              <em>"{{ message.content }}"</em>
            </div>
            <div class="message-text markdown-body" v-else-if="message.type === 'final_answer'" v-html="renderMarkdown(message.content)"></div>
            <div class="message-code" v-else-if="message.type === 'action' || message.type === 'observation'">
              <div v-if="message.metadata?.tool" class="tool-badge">{{ message.metadata.tool }}</div>
              <div v-if="message.metadata?.error" class="error-badge">오류: {{ message.metadata.error }}</div>
              <pre><code>{{ message.content }}</code></pre>
            </div>
            <div class="message-error" v-else-if="message.type === 'error'">
              {{ message.content }}
              <div v-if="message.metadata?.message" class="error-details">
                <strong>상세:</strong> {{ message.metadata.message }}
              </div>
            </div>
            <div class="message-text" v-else>
              {{ message.content }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js'

interface Message {
  type: 'thought' | 'action' | 'observation' | 'final_answer' | 'error' | 'token'
  content: string
  metadata?: any
  timestamp: Date
}

const query = ref('')
const useReact = ref(true)
const status = ref('준비완료')
const loading = ref(false)
const messages = ref<Message[]>([])

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

function clearAll() {
  messages.value = []
  status.value = '준비완료'
}


const statusClass = computed(() => {
  if (loading.value) return 'status-loading'
  if (status.value.includes('Error') || status.value.includes('오류')) return 'status-error'
  if (status.value === '완료' || status.value === 'Done') return 'status-success'
  return 'status-idle'
})

const statusIcon = computed(() => {
  if (loading.value) return '⏳'
  if (status.value.includes('Error') || status.value.includes('오류')) return '❌'
  if (status.value === '완료' || status.value === 'Done') return '✅'
  return '💤'
})

function getMessageIcon(type: string) {
  const icons = {
    thought: '🧠',
    action: '⚡',
    observation: '👁️',
    final_answer: '🎯',
    error: '❌',
    token: '💬'
  }
  return icons[type as keyof typeof icons] || '💬'
}

function getMessageTitle(type: string) {
  const titles = {
    thought: '사고과정',
    action: '도구 실행',
    observation: '실행 결과',
    final_answer: '최종 답변',
    error: '오류',
    token: '응답'
  }
  return titles[type as keyof typeof titles] || '메시지'
}

function formatTime(timestamp: Date) {
  return timestamp.toLocaleTimeString('ko-KR', { 
    hour: '2-digit', 
    minute: '2-digit',
    second: '2-digit'
  })
}

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight(code: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        const highlighted = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value
        return `<pre class="hljs"><code>${highlighted}</code></pre>`
      } catch (e) {
        /* noop */
      }
    }
    const escaped: string = code
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
    return `<pre class="hljs"><code>${escaped}</code></pre>`
  }
})

function renderMarkdown(content: string) {
  const unsafe = md.render(content || '')
  return DOMPurify.sanitize(unsafe)
}

async function copyMessage(content: string) {
  try {
    await navigator.clipboard.writeText(content)
    // TODO: 토스트 알림 추가
  } catch (err) {
    console.error('클립보드 복사 실패:', err)
  }
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
    const res = await fetch(`${API_BASE}/api/v1/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: query.value, use_react: useReact.value }),
    })
    const json = await res.json()
    
    addMessage('final_answer', json.response || '응답을 받지 못했습니다.')
    status.value = '완료'
    query.value = ''
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
    const url = new URL(`${API_BASE}/api/v1/chat/stream`)
    url.searchParams.set('query', query.value)
    url.searchParams.set('use_react', useReact.value ? 'true' : 'false')

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

</script>

<style scoped>
/* 글로벌 박스 사이징 */
*, *::before, *::after {
  box-sizing: border-box;
}

/* 글로벌 변수 */
:root {
  --primary-color: #2563eb;
  --secondary-color: #7c3aed;
  --success-color: #059669;
  --warning-color: #d97706;
  --error-color: #dc2626;
  --bg-primary: #ffffff;
  --bg-secondary: #f8fafc;
  --bg-tertiary: #f1f5f9;
  --text-primary: #1e293b;
  --text-secondary: #64748b;
  --border-color: #e2e8f0;
  --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
  --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1);
  --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1);
  --border-radius: 12px;
  --transition: all 0.2s ease-in-out;
}

/* 메인 컨테이너 */
.app-container {
  min-height: 100vh;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif;
  transition: var(--transition);
}

/* 헤더 */
.app-header {
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  padding: 1rem 0;
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(10px);
}

.header-content {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 1.5rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.app-title {
  margin: 0;
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--primary-color);
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.title-icon {
  font-size: 2rem;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}


/* 입력 섹션 */
.input-section {
  max-width: 1000px;
  margin: 0 auto;
  padding: 1.5rem 1.5rem;
}

.input-container {
  background: var(--bg-secondary);
  border: 2px solid var(--border-color);
  border-radius: var(--border-radius);
  padding: 1.5rem;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  position: relative;
  box-sizing: border-box;
}

.input-container::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, #2563eb, #7c3aed, #059669);
  border-radius: var(--border-radius) var(--border-radius) 0 0;
}


.query-input {
  width: 100%;
  min-height: 120px;
  padding: 1.25rem;
  border: 2px solid #d1d5db;
  border-radius: var(--border-radius);
  background: #ffffff;
  color: #111827;
  font-size: 1.05rem;
  line-height: 1.6;
  resize: vertical;
  transition: var(--transition);
  font-family: inherit;
  box-sizing: border-box;
  margin: 0;
  display: block;
  font-weight: 500;
}

.query-input::placeholder {
  color: #6b7280;
  font-weight: 400;
  opacity: 1;
}


.query-input:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.15);
  background: #ffffff;
}


.input-controls {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-top: 1.25rem;
  gap: 1.5rem;
  flex-wrap: wrap;
  width: 100%;
  box-sizing: border-box;
  min-height: 3rem;
}

/* ReAct 토글 */
.react-toggle {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  cursor: pointer;
  min-height: 3rem;
}

.react-toggle input[type="checkbox"] {
  display: none;
}

.toggle-slider {
  position: relative;
  width: 3rem;
  height: 1.5rem;
  background: #cbd5e1;
  border: 2px solid #e2e8f0;
  border-radius: 1rem;
  transition: var(--transition);
  cursor: pointer;
  flex-shrink: 0;
}

.toggle-slider::before {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 1.25rem;
  height: 1.25rem;
  background: white;
  border-radius: 50%;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  transition: var(--transition);
}

.react-toggle input:checked + .toggle-slider {
  background: var(--primary-color);
  border-color: var(--primary-color);
}

.react-toggle input:checked + .toggle-slider::before {
  transform: translateX(1.5rem);
  background: white;
}

.toggle-slider:hover {
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.react-toggle input:checked + .toggle-slider:hover {
  background: #1d4ed8;
}

.toggle-label {
  font-weight: 600;
  font-size: 1rem;
  color: #6b7280;
  transition: var(--transition);
  user-select: none;
  line-height: 1.5;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}

.react-toggle input:checked + .toggle-slider + .toggle-label {
  color: #1d4ed8;
  font-weight: 700;
}


/* 토글 레이블 상태 표시 */
.toggle-label::after {
  content: ' (비활성)';
  font-size: 0.8em;
  font-weight: 500;
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
  padding: 0.25rem 0.5rem;
  border-radius: 6px;
  margin-left: 0.5rem;
  vertical-align: middle;
  white-space: nowrap;
}

.react-toggle input:checked + .toggle-slider + .toggle-label::after {
  content: ' (활성)';
  color: #059669;
  background: rgba(5, 150, 105, 0.1);
  vertical-align: middle;
}


/* 버튼 스타일 */
.action-buttons {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
  align-items: center;
}

.btn {
  padding: 0.75rem 1.5rem;
  border-radius: var(--border-radius);
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
  border: 2px solid;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.95rem;
  position: relative;
  overflow: hidden;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none !important;
}

.btn::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.3), transparent);
  transition: left 0.5s ease;
}

.btn:hover:not(:disabled)::before {
  left: 100%;
}

/* 전송 버튼 (Primary) */
.btn-primary {
  background: linear-gradient(135deg, #1d4ed8 0%, #2563eb 100%);
  color: white;
  border: 2px solid #1d4ed8;
  box-shadow: 0 6px 16px rgba(29, 78, 216, 0.4);
  font-weight: 700;
}

.btn-primary:hover:not(:disabled) {
  background: linear-gradient(135deg, #1e40af 0%, #1d4ed8 100%);
  border-color: #1e40af;
  transform: translateY(-3px);
  box-shadow: 0 8px 24px rgba(29, 78, 216, 0.5);
}

.btn-primary:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
}

/* 스트림 버튼 (Secondary) */
.btn-secondary {
  background: linear-gradient(135deg, #6d28d9 0%, #8b5cf6 100%);
  color: white;
  border: 2px solid #6d28d9;
  box-shadow: 0 6px 16px rgba(109, 40, 217, 0.4);
  font-weight: 700;
}

.btn-secondary:hover:not(:disabled) {
  background: linear-gradient(135deg, #5b21b6 0%, #6d28d9 100%);
  border-color: #5b21b6;
  transform: translateY(-3px);
  box-shadow: 0 8px 24px rgba(109, 40, 217, 0.5);
}

.btn-secondary:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(124, 58, 237, 0.3);
}

/* 지우기 버튼 (Outline) */
.btn-outline {
  background: #f8fafc;
  color: #475569;
  border: 2px solid #94a3b8;
  box-shadow: 0 4px 12px rgba(71, 85, 105, 0.2);
  font-weight: 600;
}

.btn-outline:hover:not(:disabled) {
  background: #e2e8f0;
  color: #334155;
  border-color: #64748b;
  transform: translateY(-3px);
  box-shadow: 0 6px 20px rgba(71, 85, 105, 0.3);
}


.btn-outline:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
}

/* 로딩 상태 버튼 */
.btn:disabled .loading-spinner {
  margin-right: 0.5rem;
}

/* 버튼 텍스트 스타일 */
.btn-primary,
.btn-secondary {
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
}

/* 버튼 아이콘 애니메이션 */
.btn:hover:not(:disabled) {
  animation: button-glow 2s ease-in-out infinite;
}

@keyframes button-glow {
  0%, 100% { box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3); }
  50% { box-shadow: 0 6px 20px rgba(37, 99, 235, 0.5); }
}

.btn-secondary:hover:not(:disabled) {
  animation: button-glow-secondary 2s ease-in-out infinite;
}

@keyframes button-glow-secondary {
  0%, 100% { box-shadow: 0 4px 12px rgba(124, 58, 237, 0.3); }
  50% { box-shadow: 0 6px 20px rgba(124, 58, 237, 0.5); }
}

/* 로딩 스피너 */
.loading-spinner {
  width: 1rem;
  height: 1rem;
  border: 2px solid transparent;
  border-top: 2px solid currentColor;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 상태 바 */
.status-bar {
  max-width: 1000px;
  margin: 0 auto;
  padding: 0 1.5rem;
  margin-bottom: 0.75rem;
}

.status-content {
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border: 2px solid #e2e8f0;
  border-radius: var(--border-radius);
  padding: 1.25rem 1.75rem;
  display: flex;
  align-items: center;
  gap: 1rem;
  position: relative;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}


.status-bar.status-loading .status-content {
  border-color: #2563eb;
  background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
  animation: pulse-loading 2s ease-in-out infinite;
}


.status-bar.status-success .status-content {
  border-color: #10b981;
  background: linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%);
}


.status-bar.status-error .status-content {
  border-color: #ef4444;
  background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%);
  animation: shake 0.5s ease-in-out;
}


@keyframes pulse-loading {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.02); }
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-5px); }
  75% { transform: translateX(5px); }
}

.status-icon {
  font-size: 1.5rem;
  animation: icon-bounce 2s ease-in-out infinite;
}

.status-text {
  font-weight: 600;
  font-size: 1.1rem;
  color: var(--text-primary);
}

.status-bar.status-loading .status-text {
  color: #1d4ed8;
  font-weight: 700;
}

.status-bar.status-success .status-text {
  color: #065f46;
  font-weight: 700;
}

.status-bar.status-error .status-text {
  color: #dc2626;
  font-weight: 700;
}

@keyframes icon-bounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-3px); }
}

.progress-bar {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--border-color);
}

.progress-fill {
  height: 100%;
  background: var(--primary-color);
  animation: loading-progress 2s ease-in-out infinite;
}

@keyframes loading-progress {
  0% { width: 0%; }
  50% { width: 70%; }
  100% { width: 100%; }
}

/* 메시지 컨테이너 */
.messages-container {
  max-width: 1000px;
  margin: 0 auto;
  padding: 0 1.5rem 1.5rem;
}

.empty-state {
  text-align: center;
  padding: 2.5rem 2rem;
  color: var(--text-secondary);
}

.empty-icon {
  font-size: 4rem;
  margin-bottom: 1rem;
  opacity: 0.5;
}

.empty-state h3 {
  margin: 0 0 0.5rem 0;
  color: var(--text-primary);
}

.empty-state p {
  margin: 0;
  max-width: 500px;
  margin: 0 auto;
  line-height: 1.6;
}

.message-group {
  margin-bottom: 1.25rem;
  position: relative;
}

.message-group::after {
  content: '';
  position: absolute;
  bottom: -0.625rem;
  left: 50%;
  transform: translateX(-50%);
  width: 40px;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--border-color), transparent);
  opacity: 0.3;
}

.message-group:last-child::after {
  display: none;
}

/* 메시지 카드 스타일 */
.message-card {
  border-radius: var(--border-radius);
  overflow: hidden;
  box-shadow: var(--shadow-md);
  transition: var(--transition);
  border: 2px solid;
  margin-bottom: 1rem;
}

.message-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lg);
}

.message-thought:hover {
  box-shadow: 0 8px 25px rgba(59, 130, 246, 0.3);
}

.message-action:hover {
  box-shadow: 0 8px 25px rgba(245, 158, 11, 0.3);
}

.message-observation:hover {
  box-shadow: 0 8px 25px rgba(5, 150, 105, 0.3);
}

.message-final_answer:hover {
  box-shadow: 0 8px 25px rgba(124, 58, 237, 0.3);
}

.message-error:hover {
  box-shadow: 0 8px 25px rgba(220, 38, 38, 0.3);
}

.message-token:hover {
  box-shadow: 0 8px 25px rgba(100, 116, 139, 0.3);
}

.message-card .message-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  font-weight: 500;
}

.message-card .message-icon {
  font-size: 1.25rem;
}

.message-card .message-title {
  font-weight: 600;
  font-size: 0.95rem;
}

.message-card .message-timestamp {
  font-size: 0.8rem;
  color: var(--text-secondary);
  margin-left: auto;
}

.message-card .copy-btn {
  background: linear-gradient(135deg, var(--primary-color) 0%, #1d4ed8 100%);
  color: white;
  border: 1px solid var(--primary-color);
  border-radius: 8px;
  padding: 0.4rem 0.75rem;
  cursor: pointer;
  transition: var(--transition);
  font-size: 0.85rem;
  font-weight: 500;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.2);
  position: relative;
  overflow: hidden;
}

.message-card .copy-btn::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.3), transparent);
  transition: left 0.3s ease;
}

.message-card .copy-btn:hover {
  transform: scale(1.05) translateY(-1px);
  background: linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
}

.message-card .copy-btn:hover::before {
  left: 100%;
}

.message-card .copy-btn:active {
  transform: scale(0.98);
  box-shadow: 0 1px 3px rgba(37, 99, 235, 0.2);
}

.message-card .message-content {
  padding: 1.25rem;
  border-top: 1px solid var(--border-color);
}

/* 사고과정 메시지 */
.message-thought {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(59, 130, 246, 0.05) 100%);
  border-color: var(--primary-color);
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
}

.message-thought .message-header {
  background: rgba(59, 130, 246, 0.1);
  color: var(--primary-color);
}

.message-thought .message-text {
  color: var(--primary-color);
  font-style: italic;
  font-size: 1.05rem;
  line-height: 1.6;
}

/* 액션 메시지 */
.message-action {
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.1) 0%, rgba(245, 158, 11, 0.05) 100%);
  border-color: var(--warning-color);
  box-shadow: 0 4px 12px rgba(245, 158, 11, 0.2);
}

.message-action .message-header {
  background: rgba(245, 158, 11, 0.1);
  color: var(--warning-color);
}

.message-action .tool-badge {
  background: var(--warning-color);
  color: white;
  padding: 0.25rem 0.75rem;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 500;
  text-transform: uppercase;
  margin-bottom: 0.75rem;
  display: inline-block;
}

/* 관찰 메시지 */
.message-observation {
  background: linear-gradient(135deg, rgba(5, 150, 105, 0.1) 0%, rgba(5, 150, 105, 0.05) 100%);
  border-color: var(--success-color);
  box-shadow: 0 4px 12px rgba(5, 150, 105, 0.2);
}

.message-observation .message-header {
  background: rgba(5, 150, 105, 0.1);
  color: var(--success-color);
}

.message-observation .error-badge {
  background: var(--error-color);
  color: white;
  padding: 0.25rem 0.75rem;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 500;
  margin-bottom: 0.75rem;
  display: inline-block;
}

/* 최종 답변 메시지 */
.message-final_answer {
  background: linear-gradient(135deg, rgba(124, 58, 237, 0.1) 0%, rgba(124, 58, 237, 0.05) 100%);
  border-color: var(--secondary-color);
  box-shadow: 0 4px 12px rgba(124, 58, 237, 0.2);
}

.message-final_answer .message-header {
  background: rgba(124, 58, 237, 0.1);
  color: var(--secondary-color);
}

.message-final_answer .message-text {
  color: var(--secondary-color);
  font-size: 1.05rem;
  line-height: 1.7;
}

/* 오류 메시지 */
.message-error {
  background: linear-gradient(135deg, rgba(220, 38, 38, 0.1) 0%, rgba(220, 38, 38, 0.05) 100%);
  border-color: var(--error-color);
  box-shadow: 0 4px 12px rgba(220, 38, 38, 0.2);
}

.message-error .message-header {
  background: rgba(220, 38, 38, 0.1);
  color: var(--error-color);
}

.message-error .message-error {
  color: var(--error-color);
  font-weight: 500;
}

.message-error .error-details {
  margin-top: 0.75rem;
  padding: 0.75rem;
  background: rgba(220, 38, 38, 0.05);
  border-radius: 6px;
  font-size: 0.9rem;
}

/* 토큰 메시지 */
.message-token {
  background: var(--bg-secondary);
  border-color: var(--border-color);
  box-shadow: 0 4px 12px rgba(100, 116, 139, 0.2);
}

.message-token .message-header {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.message-token .message-text {
  color: var(--text-primary);
  font-size: 1rem;
  line-height: 1.7;
}

/* 코드 스타일 */
.message-code pre {
  margin: 0;
  padding: 1rem;
  background: rgba(0, 0, 0, 0.05);
  border-radius: 8px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 0.9rem;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
}

.message-code code {
  color: inherit;
  background: none;
  padding: 0;
  font-size: inherit;
}

/* Markdown rendered content */
.markdown-body {
  line-height: 1.75;
  color: var(--text-primary);
}

.markdown-body h1,
.markdown-body h2,
.markdown-body h3 {
  margin: 1rem 0 0.75rem;
  font-weight: 700;
}

.markdown-body h4,
.markdown-body h5,
.markdown-body h6 {
  margin: 0.75rem 0 0.5rem;
  font-weight: 600;
}

.markdown-body p {
  margin: 0.75rem 0;
}

.markdown-body ul,
.markdown-body ol {
  padding-left: 1.25rem;
  margin: 0.75rem 0;
}

.markdown-body li + li {
  margin-top: 0.25rem;
}

.markdown-body a {
  color: #2563eb;
  text-decoration: underline;
}

.markdown-body blockquote {
  margin: 0.75rem 0;
  padding: 0.5rem 1rem;
  border-left: 4px solid #c7d2fe;
  background: #f8fafc;
  color: #334155;
}

.markdown-body pre code {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

.markdown-body code:not(pre code) {
  background: rgba(0, 0, 0, 0.06);
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
}

/* 텍스트 스타일 */
.message-text {
  line-height: 1.6;
}

.message-text strong {
  font-weight: 600;
}

.message-text em {
  font-style: italic;
}

.message-text code {
  background: rgba(0, 0, 0, 0.1);
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.9em;
}

/* 반응형 디자인 */
@media (max-width: 768px) {
  .header-content {
    padding: 0 1rem;
  }
  
  .input-section {
    padding: 1.5rem 1rem;
  }
  
  .messages-container {
    padding: 0 1rem 2rem;
  }
  
  .input-controls {
    flex-direction: column;
    align-items: stretch;
    gap: 1rem;
  }
  
  .react-toggle {
    justify-content: center;
  }
  
  .action-buttons {
    justify-content: center;
  }
  
  .app-title {
    font-size: 1.5rem;
  }
}

@media (max-width: 480px) {
  .action-buttons {
    flex-direction: column;
  }
  
  .btn {
    justify-content: center;
  }
}
</style>


