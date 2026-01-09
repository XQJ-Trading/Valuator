<template>
  <Teleport to="body">
    <div v-if="show" class="modal-overlay" @click="handleClose">
      <div class="modal-container" @click.stop>
        <!-- 헤더 -->
        <div class="modal-header">
          <h2>📚 Session History</h2>
          <button @click="handleClose" class="btn-close">✕</button>
        </div>


        <!-- 재생 모드 -->
        <div v-if="replayMode" class="replay-container">
          <div class="replay-header">
            <button @click="stopReplay" class="btn-back">← 목록으로</button>
            <div class="replay-controls">
              <span class="replay-status">{{ replayStatus }}</span>
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
        <div v-if="!replayMode && sessions.length > 0" class="modal-footer">
          <button
            @click="loadMore"
            :disabled="loading"
            class="btn-load-more"
          >
            {{ loading ? '로딩중...' : '더 보기' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useHistory } from '../../composables/useHistory'
import SessionCard from './SessionCard.vue'
import MessagesContainer from '../MessagesContainer.vue'
import type { Message } from '../../types/Message'

interface Props {
  show: boolean
}

interface Emits {
  (e: 'close'): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

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
let cleanupReplay: (() => void) | null = null

// 모달 열릴 때 세션 로드
watch(() => props.show, (newVal) => {
  if (newVal) {
    fetchSessions()
  } else {
    // 모달 닫힐 때 재생 중지
    if (replayMode.value) {
      stopReplay()
    }
  }
})

onMounted(() => {
  if (props.show) {
    fetchSessions()
  }
})

function handleClose() {
  if (replayMode.value) {
    stopReplay()
  }
  emit('close')
}

function loadMore() {
  currentOffset.value += 10
  fetchSessions(10, currentOffset.value)
}

async function handleReplay(sessionId: string) {
  replayMode.value = true
  replayMessages.value = []
  replayStatus.value = '재생 중...'

  try {
    cleanupReplay = await replaySession(
      sessionId,
      (event) => {
        // 이벤트를 Message 형식으로 변환
        const messageType = event.type === 'review' ? 'observation' : event.type
        const message: Message = {
          type: messageType as Message['type'],
          content: event.content || '',
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
        
        // 상태 업데이트
        if (event.type === 'thought') {
          replayStatus.value = '🧠 사고중...'
        } else if (event.type === 'action') {
          replayStatus.value = `⚡ ${event.tool || '도구'} 실행중...`
        } else if (event.type === 'observation' || event.type === 'review') {
          replayStatus.value = '👁️ 결과 분석중...'
        } else if (event.type === 'end') {
          replayStatus.value = '재생 완료'
        }
      },
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
}

async function handleDelete(sessionId: string) {
  if (!confirm('이 세션을 삭제하시겠습니까?')) {
    return
  }

  const result = await deleteSession(sessionId)
  if (result) {
    // 성공적으로 삭제됨
    console.log('Session deleted:', sessionId)
  }
}


</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  justify-content: flex-end;
  z-index: 1000;
  animation: fadeIn 0.3s ease-out;
}

.modal-container {
  background: var(--bg-primary);
  width: 600px;
  max-width: 90vw;
  height: 100vh;
  display: flex;
  flex-direction: column;
  animation: slideInRight 0.3s ease-out;
  box-shadow: -4px 0 20px rgba(0, 0, 0, 0.3);
}

/* 헤더 */
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.modal-header h2 {
  margin: 0;
  font-size: 1.5rem;
  color: var(--text-primary);
}

.btn-close {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: var(--text-secondary);
  padding: 0.25rem;
  border-radius: 4px;
  transition: var(--transition);
}

.btn-close:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

/* 세션 컨테이너 */
.sessions-container {
  flex: 1;
  overflow-y: auto;
  padding: 1rem 1.5rem;
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
  overflow: hidden;
}

.replay-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
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
  padding: 3rem;
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
.modal-footer {
  padding: 1rem 1.5rem;
  border-top: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.btn-load-more {
  width: 100%;
  padding: 0.75rem;
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
}

.btn-load-more:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 애니메이션 */
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideInRight {
  from {
    transform: translateX(100%);
  }
  to {
    transform: translateX(0);
  }
}

/* 반응형 */
@media (max-width: 768px) {
  .modal-container {
    width: 100vw;
    max-width: 100vw;
  }
}
</style>
