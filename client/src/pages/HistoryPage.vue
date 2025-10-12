<template>
  <div class="history-page">
    <!-- 헤더 -->
    <div class="page-header">
      <h1>📚 Session History</h1>
    </div>


    <!-- 재생 모드 -->
    <div v-if="replayMode" class="replay-container">
      <div class="replay-header">
        <button @click="stopReplay" class="btn-back">← 목록으로</button>
        <div class="replay-controls">
          <span class="replay-status">{{ replayStatus }}</span>
          <select v-model="playbackSpeed" class="speed-selector">
            <option :value="0.5">0.5x</option>
            <option :value="1">1x</option>
            <option :value="2">2x</option>
          </select>
        </div>
      </div>
      
      <!-- 재생 메시지 컨테이너 -->
      <div class="replay-messages">
        <MessagesContainer :messages="replayMessages" />
      </div>
    </div>

    <!-- 세션 목록 -->
    <div v-else class="sessions-container">
      <div v-if="loading" class="loading">
        <div class="spinner"></div>
        <p>로딩중...</p>
      </div>

      <div v-else-if="error" class="error">
        <p>❌ {{ error }}</p>
        <button @click="fetchSessions()" class="btn-retry">다시 시도</button>
      </div>

      <div v-else-if="sessions.length === 0" class="empty">
        <p>📭 세션이 없습니다</p>
      </div>

      <div v-else class="sessions-list">
        <SessionCard
          v-for="session in sessions"
          :key="session.session_id"
          :session="session"
          @replay="handleReplay"
          @delete="handleDelete"
        />
      </div>
    </div>

    <!-- 푸터 (페이지네이션) -->
    <div v-if="!replayMode && sessions.length > 0" class="page-footer">
      <button
        @click="loadMore"
        :disabled="loading"
        class="btn-load-more"
      >
        {{ loading ? '로딩중...' : '더 보기' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useHistory } from '../composables/useHistory'
import SessionCard from '../components/history/SessionCard.vue'
import MessagesContainer from '../components/MessagesContainer.vue'
import type { Message } from '../types/Message'

interface Props {
  sessionId?: string
}

const props = defineProps<Props>()
const route = useRoute()
const router = useRouter()

const {
  sessions,
  loading,
  error,
  fetchSessions,
  replaySession,
  deleteSession
} = useHistory()

// State
const currentOffset = ref(0)
const replayMode = ref(false)
const replayMessages = ref<Message[]>([])
const replayStatus = ref('준비')
const playbackSpeed = ref(1)
let cleanupReplay: (() => void) | null = null

// 초기 로드 (이미 로딩 중이 아닐 때만)
onMounted(() => {
  if (!loading.value && sessions.value.length === 0) {
    fetchSessions()
  }
  
  // URL에 sessionId가 있으면 자동 재생
  if (props.sessionId) {
    handleReplay(props.sessionId)
  }
})

// sessionId prop 변경 감지 (중복 실행 방지)
watch(() => props.sessionId, (newId, oldId) => {
  // 새로운 ID가 있고 이전 ID와 다를 때만 실행 (초기 마운트 제외)
  if (newId && newId !== oldId && oldId !== undefined) {
    handleReplay(newId)
  } else if (!newId && replayMode.value) {
    stopReplay()
  }
})

function loadMore() {
  currentOffset.value += 10
  fetchSessions(10, currentOffset.value, true) // append: true로 추가
}

async function handleReplay(sessionId: string) {
  replayMode.value = true
  replayMessages.value = []
  replayStatus.value = '재생 중...'

  // URL 업데이트 (히스토리에 추가하지 않고 교체)
  if (route.params.sessionId !== sessionId) {
    router.replace(`/history/${sessionId}`)
  }

  try {
    cleanupReplay = await replaySession(
      sessionId,
      (event) => {
        // subtask_result 태그를 포함한 메시지인지 확인하고 별도 처리
        if (event.content && (event.type === 'thought' || event.type === 'observation')) {
          const subtaskMatch = event.content.match(/<subtask_result>(.*?)<\/subtask_result>/s)
          if (subtaskMatch) {
            const subtaskContent = subtaskMatch[1].trim()

            // 원본 메시지 추가 (subtask_result 제외)
            const originalContent = event.content.replace(/<subtask_result>.*?<\/subtask_result>/s, '').trim()
            if (originalContent) {
              const originalMessage: Message = {
                type: event.type,
                content: originalContent,
                metadata: {
                  tool: event.tool,
                  tool_input: event.tool_input,
                  tool_output: event.tool_output,
                  error: event.error,
                  tool_result: event.tool_result,
                  query: event.query
                },
                timestamp: new Date()
              }
              replayMessages.value.push(originalMessage)
            }

            // subtask_result를 별도의 메시지로 추가
            const subtaskMessage: Message = {
              type: 'subtask_result',
              content: subtaskContent,
              metadata: {
                source_type: event.type,
                original_content: originalContent
              },
              timestamp: new Date()
            }
            replayMessages.value.push(subtaskMessage)
          } else {
            // 일반 메시지 처리
            let content = event.content || ''
            const message: Message = {
              type: event.type,
              content: content,
              metadata: {
                tool: event.tool,
                tool_input: event.tool_input,
                tool_output: event.tool_output,
                error: event.error,
                tool_result: event.tool_result,
                query: event.query
              },
              timestamp: new Date()
            }
            replayMessages.value.push(message)
          }
        } else {
          // 다른 타입의 메시지 처리
          let content = event.content || ''
          
          // start 이벤트의 경우 query를 content로 사용
          if (event.type === 'start' && event.query) {
            content = event.query
          }
          
          const message: Message = {
            type: event.type,
            content: content,
            metadata: {
              tool: event.tool,
              tool_input: event.tool_input,
              tool_output: event.tool_output,
              error: event.error,
              tool_result: event.tool_result,
              query: event.query
            },
            timestamp: new Date()
          }
          replayMessages.value.push(message)
        }
        
        // 상태 업데이트
        if (event.type === 'thought') {
          replayStatus.value = '🧠 사고중...'
        } else if (event.type === 'action') {
          replayStatus.value = `⚡ ${event.tool || '도구'} 실행중...`
        } else if (event.type === 'observation') {
          replayStatus.value = '👁️ 결과 분석중...'
        } else if (event.type === 'end') {
          replayStatus.value = '재생 완료'
        }
      },
      playbackSpeed.value
    )
  } catch (e: any) {
    console.error('Replay error:', e)
    replayStatus.value = '재생 오류'
  }
}

function stopReplay() {
  if (cleanupReplay) {
    cleanupReplay()
    cleanupReplay = null
  }
  replayMode.value = false
  replayMessages.value = []
  replayStatus.value = '준비'
  
  // URL을 목록으로 복구
  router.replace('/history')
}

async function handleDelete(sessionId: string) {
  if (!confirm('이 세션을 삭제하시겠습니까?')) {
    return
  }

  const result = await deleteSession(sessionId)
  if (result) {
    console.log('Session deleted:', sessionId)
  }
}
</script>

<style scoped>
.history-page {
  min-height: calc(100vh - 80px);
  max-width: 1400px;
  margin: 0 auto;
  padding: 2rem;
  display: flex;
  flex-direction: column;
}

/* 헤더 */
.page-header {
  margin-bottom: 1.5rem;
}

.page-header h1 {
  margin: 0;
  font-size: 2rem;
  color: var(--text-primary);
}

/* 세션 컨테이너 */
.sessions-container {
  flex: 1;
  margin-bottom: 1rem;
}

.sessions-list {
  display: flex;
  flex-direction: column;
}

/* 재생 컨테이너 */
.replay-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
  border-radius: var(--border-radius);
  overflow: hidden;
}

.replay-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-tertiary);
}

.btn-back {
  background: var(--primary-color);
  color: white;
  border: none;
  padding: 0.5rem 1rem;
  border-radius: var(--border-radius);
  cursor: pointer;
  font-weight: 600;
  transition: var(--transition);
}

.btn-back:hover {
  background: #1d4ed8;
}

.replay-controls {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.replay-status {
  font-size: 0.9rem;
  color: var(--text-secondary);
}

.speed-selector {
  padding: 0.25rem 0.5rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  cursor: pointer;
}

.replay-messages {
  flex: 1;
  overflow-y: auto;
  padding: 1rem 1.5rem;
}

/* 상태 */
.loading,
.error,
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4rem 2rem;
  text-align: center;
  color: var(--text-secondary);
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--border-color);
  border-top-color: var(--primary-color);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 1rem;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.btn-retry {
  margin-top: 1rem;
  padding: 0.5rem 1rem;
  background: var(--primary-color);
  color: white;
  border: none;
  border-radius: var(--border-radius);
  cursor: pointer;
  font-weight: 600;
}

.btn-retry:hover {
  background: #1d4ed8;
}

/* 푸터 */
.page-footer {
  padding-top: 1rem;
  text-align: center;
}

.btn-load-more {
  padding: 0.75rem 2rem;
  background: var(--primary-color);
  color: white;
  border: none;
  border-radius: var(--border-radius);
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
}

.btn-load-more:hover:not(:disabled) {
  background: #1d4ed8;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4);
}

.btn-load-more:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 반응형 */
@media (max-width: 768px) {
  .history-page {
    padding: 1rem;
  }
  
  .page-header h1 {
    font-size: 1.5rem;
  }
}
</style>
