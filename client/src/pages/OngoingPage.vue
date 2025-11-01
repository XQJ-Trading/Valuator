<template>
  <div class="ongoing-page">
    <!-- 헤더 -->
    <div class="page-header">
      <h1>🔄 Active Sessions</h1>
    </div>

    <!-- 세션 목록 -->
    <div class="sessions-container">
      <div v-if="loading" class="loading">
        <div class="spinner"></div>
        <p>로딩중...</p>
      </div>

      <div v-else-if="error" class="error">
        <p>❌ {{ error }}</p>
        <button @click="fetchActiveSessions()" class="btn-retry">다시 시도</button>
      </div>

      <div v-else-if="activeSessions.length === 0" class="empty">
        <p>📭 진행 중인 세션이 없습니다</p>
        <router-link to="/" class="btn-create">새 세션 생성</router-link>
      </div>

      <div v-else class="sessions-list">
        <div
          v-for="session in activeSessions"
          :key="session.session_id"
          class="session-card"
          @click="connectToSession(session.session_id)"
        >
          <div class="card-header">
            <div class="session-status">
              <span class="status-dot running"></span>
              <span class="status-text">진행중</span>
            </div>
            <span class="session-id">{{ session.session_id }}</span>
          </div>

          <div class="card-body">
            <div class="query-preview">
              <strong>Query:</strong>
              <p>{{ truncateText(session.query, 100) }}</p>
            </div>

            <div class="session-info">
              <span class="info-item">
                <span class="label">Events:</span>
                <span class="value">{{ session.event_count }}</span>
              </span>
              <span class="info-item">
                <span class="label">Created:</span>
                <span class="value">{{ formatTime(session.created_at) }}</span>
              </span>
            </div>
          </div>

          <div class="card-footer">
            <button class="btn-connect" @click.stop="connectToSession(session.session_id)">
              → 연결하기
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 자동 새로고침 -->
    <div class="refresh-controls">
      <label class="auto-refresh">
        <input v-model="autoRefresh" type="checkbox" />
        <span>자동 새로고침 ({{ refreshInterval }}초)</span>
      </label>
      <button @click="fetchActiveSessions()" class="btn-refresh" :disabled="loading">
        🔄 새로고침
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSession } from '../composables/useSession'
import type { Session } from '../types/Session'

interface OngoingSession extends Session {
  query: string
}

const router = useRouter()

const {
  fetchActiveSessions: fetchSessionsFromComposable
} = useSession()

const activeSessions = ref<OngoingSession[]>([])
const loading = ref(false)
const error = ref('')
const autoRefresh = ref(true)
const refreshInterval = ref(5)

let refreshTimer: number | null = null

onMounted(() => {
  fetchActiveSessions()
  startAutoRefresh()
})

onUnmounted(() => {
  stopAutoRefresh()
})

function startAutoRefresh() {
  if (autoRefresh.value) {
    refreshTimer = window.setInterval(() => {
      fetchActiveSessions()
    }, refreshInterval.value * 1000)
  }
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

watch(() => autoRefresh.value, (newVal) => {
  stopAutoRefresh()
  if (newVal) {
    startAutoRefresh()
  }
})

async function fetchActiveSessions() {
  loading.value = true
  error.value = ''

  try {
    const sessions = await fetchSessionsFromComposable()
    activeSessions.value = sessions || []
  } catch (err: any) {
    console.error('Failed to fetch active sessions:', err)
    error.value = `세션 조회 실패: ${err.message}`
  } finally {
    loading.value = false
  }
}

function connectToSession(sessionId: string) {
  // 세션 페이지로 이동 (세션 URL)
  router.push(`/session/${sessionId}`)
}

function truncateText(text: string, length: number): string {
  if (text.length > length) {
    return text.substring(0, length) + '...'
  }
  return text
}

function formatTime(dateString: string): string {
  try {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)

    if (diffMins < 1) return '방금 전'
    if (diffMins < 60) return `${diffMins}분 전`

    const diffHours = Math.floor(diffMins / 60)
    if (diffHours < 24) return `${diffHours}시간 전`

    const diffDays = Math.floor(diffHours / 24)
    return `${diffDays}일 전`
  } catch {
    return dateString
  }
}

import { watch } from 'vue'
</script>

<style scoped>
.ongoing-page {
  min-height: calc(100vh - 60px);
  max-width: 1400px;
  margin: 0 auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
}

/* 헤더 */
.page-header {
  margin-bottom: 1.5rem;
}

.page-header h1 {
  margin: 0;
  font-size: 1.5rem;
  color: var(--text-primary);
}

/* 세션 컨테이너 */
.sessions-container {
  flex: 1;
  margin-bottom: 1.5rem;
}

.sessions-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 1rem;
}

/* 세션 카드 */
.session-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  overflow: hidden;
  transition: all 0.3s ease;
  cursor: pointer;
  display: flex;
  flex-direction: column;
}

.session-card:hover {
  border-color: var(--primary-color);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2);
  transform: translateY(-2px);
}

.card-header {
  padding: 1rem;
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.1) 0%, rgba(29, 78, 216, 0.05) 100%);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.session-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 600;
  color: var(--text-primary);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.status-dot.running {
  background-color: #4ade80;
  box-shadow: 0 0 8px rgba(74, 222, 128, 0.6);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
    box-shadow: 0 0 8px rgba(74, 222, 128, 0.6);
  }
  50% {
    opacity: 0.7;
    box-shadow: 0 0 4px rgba(74, 222, 128, 0.3);
  }
}

.session-id {
  font-family: 'Courier New', monospace;
  font-size: 0.8rem;
  color: var(--text-secondary);
  background: var(--bg-tertiary);
  padding: 0.3rem 0.6rem;
  border-radius: 4px;
}

.card-body {
  padding: 1rem;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.query-preview {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.query-preview strong {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.query-preview p {
  margin: 0;
  font-size: 0.9rem;
  color: var(--text-primary);
  line-height: 1.4;
  word-break: break-word;
}

.session-info {
  display: flex;
  gap: 1rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--border-color);
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  font-size: 0.85rem;
}

.info-item .label {
  color: var(--text-secondary);
  font-weight: 600;
}

.info-item .value {
  color: var(--primary-color);
  font-weight: 600;
  font-family: 'Courier New', monospace;
}

.card-footer {
  padding: 0.75rem 1rem;
  background: var(--bg-tertiary);
  border-top: 1px solid var(--border-color);
}

.btn-connect {
  width: 100%;
  padding: 0.5rem;
  background: linear-gradient(135deg, var(--primary-color) 0%, #1d4ed8 100%);
  color: white;
  border: none;
  border-radius: 4px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 0.9rem;
}

.btn-connect:hover {
  background: linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%);
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
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
  to {
    transform: rotate(360deg);
  }
}

.btn-retry,
.btn-create {
  margin-top: 1rem;
  padding: 0.5rem 1rem;
  background: var(--primary-color);
  color: white;
  border: none;
  border-radius: var(--border-radius);
  cursor: pointer;
  font-weight: 600;
  text-decoration: none;
  display: inline-block;
  transition: all 0.2s;
}

.btn-retry:hover,
.btn-create:hover {
  background: #1d4ed8;
  transform: translateY(-1px);
}

/* 새로고침 컨트롤 */
.refresh-controls {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  background: var(--bg-secondary);
  border-radius: var(--border-radius);
  border: 1px solid var(--border-color);
}

.auto-refresh {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  font-weight: 600;
  color: var(--text-primary);
}

.auto-refresh input {
  width: 18px;
  height: 18px;
  cursor: pointer;
  accent-color: var(--primary-color);
}

.btn-refresh {
  padding: 0.5rem 1rem;
  background: var(--primary-color);
  color: white;
  border: none;
  border-radius: 4px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-refresh:hover:not(:disabled) {
  background: #1d4ed8;
  transform: translateY(-1px);
}

.btn-refresh:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 반응형 */
@media (max-width: 1024px) {
  .sessions-list {
    grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  }
}

@media (max-width: 768px) {
  .ongoing-page {
    min-height: calc(100vh - 50px);
    padding: 0.75rem;
  }

  .page-header {
    margin-bottom: 1rem;
  }

  .page-header h1 {
    font-size: 1.3rem;
  }

  .sessions-list {
    grid-template-columns: 1fr;
  }

  .session-card {
    display: grid;
    grid-template-columns: 1fr auto;
  }

  .card-header {
    grid-column: 1 / -1;
  }

  .card-body {
    padding: 0.75rem;
  }

  .card-footer {
    padding: 0;
  }

  .btn-connect {
    padding: 0.75rem;
    font-size: 0.85rem;
  }

  .refresh-controls {
    flex-direction: column;
    gap: 0.75rem;
  }
}

@media (max-width: 480px) {
  .ongoing-page {
    min-height: calc(100vh - 45px);
    padding: 0.5rem;
  }

  .page-header {
    margin-bottom: 0.75rem;
  }

  .page-header h1 {
    font-size: 1.1rem;
  }

  .sessions-list {
    gap: 0.75rem;
  }

  .session-card {
    flex-direction: column;
  }

  .card-header {
    padding: 0.75rem;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .session-id {
    font-size: 0.75rem;
  }

  .card-body {
    padding: 0.6rem;
    gap: 0.5rem;
  }

  .query-preview p {
    font-size: 0.85rem;
  }

  .session-info {
    gap: 0.75rem;
  }

  .info-item {
    font-size: 0.8rem;
  }

  .card-footer {
    padding: 0.5rem;
  }

  .btn-connect {
    padding: 0.4rem;
    font-size: 0.8rem;
  }

  .refresh-controls {
    padding: 0.75rem;
    gap: 0.5rem;
  }

  .auto-refresh {
    font-size: 0.9rem;
  }

  .btn-refresh {
    padding: 0.4rem 0.75rem;
    font-size: 0.85rem;
  }
}
</style>
