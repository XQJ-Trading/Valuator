<template>
  <div class="session-card" :class="{ 'session-success': session.success, 'session-failed': !session.success }" @click="handleCardClick">
    <div class="session-header">
      <div class="session-meta">
        <span class="session-status">
          {{ session.success ? '✅' : '❌' }}
        </span>
        <span class="session-time">{{ formatTime(session.timestamp) }}</span>
        <span class="session-duration">⏱️ {{ session.duration }}s</span>
      </div>
      <div class="session-actions">
        <button @click="handleDeleteClick" class="btn-delete" title="삭제">
          🗑️
        </button>
      </div>
    </div>
    
    <div class="session-body">
      <div class="session-query">
        <strong>Q:</strong> {{ truncate(session.query, 100) }}
      </div>
      <div class="session-answer">
        <strong>A:</strong> {{ truncate(session.final_answer, 150) }}
      </div>
    </div>
    
    <div class="session-footer">
      <div class="session-stats">
        <span class="stat-item">📊 {{ session.step_count }} steps</span>
        <span v-if="session.tools_used.length > 0" class="stat-item">
          🛠️ {{ session.tools_used.join(', ') }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { SessionSummary } from '../../composables/useHistory'

interface Props {
  session: SessionSummary
}

interface Emits {
  (e: 'replay', sessionId: string): void
  (e: 'delete', sessionId: string): void
}

const props = defineProps<Props>()
const $emit = defineEmits<Emits>()

function formatTime(timestamp: string): string {
  try {
    const date = new Date(timestamp)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    
    // 시간 차이에 따라 다른 포맷
    if (diff < 60000) { // 1분 미만
      return '방금 전'
    } else if (diff < 3600000) { // 1시간 미만
      const minutes = Math.floor(diff / 60000)
      return `${minutes}분 전`
    } else if (diff < 86400000) { // 24시간 미만
      const hours = Math.floor(diff / 3600000)
      return `${hours}시간 전`
    } else {
      // 날짜 표시
      return date.toLocaleDateString('ko-KR', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      })
    }
  } catch {
    return timestamp
  }
}

function truncate(text: string, maxLength: number): string {
  if (!text) return '-'
  if (text.length <= maxLength) return text
  return text.substring(0, maxLength) + '...'
}

function handleCardClick() {
  $emit('replay', props.session.session_id)
}

function handleDeleteClick(event: Event) {
  event.stopPropagation() // 카드 클릭 이벤트 전파 중지
  $emit('delete', props.session.session_id)
}

</script>

<style scoped>
.session-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  padding: 1rem;
  margin-bottom: 0.75rem;
  transition: var(--transition);
  cursor: pointer;
}

.session-card:hover {
  border-color: var(--primary-color);
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.2);
  transform: translateY(-1px);
}

.session-success {
  border-left: 3px solid #10b981;
}

.session-failed {
  border-left: 3px solid #ef4444;
}

/* 헤더 */
.session-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.session-meta {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.session-status {
  font-size: 1.1rem;
}

.session-actions {
  display: flex;
  gap: 0.5rem;
}

.btn-delete {
  background: none;
  border: none;
  font-size: 1.1rem;
  cursor: pointer;
  padding: 0.25rem;
  border-radius: 4px;
  transition: var(--transition);
  opacity: 0.7;
}

.btn-delete:hover {
  opacity: 1;
  background: rgba(239, 68, 68, 0.1);
}

/* 본문 */
.session-body {
  margin-bottom: 0.75rem;
}

.session-query,
.session-answer {
  margin-bottom: 0.5rem;
  font-size: 0.9rem;
  line-height: 1.5;
}

.session-query {
  color: var(--text-primary);
}

.session-answer {
  color: var(--text-secondary);
}

.session-query strong,
.session-answer strong {
  color: var(--primary-color);
  margin-right: 0.25rem;
}

/* 푸터 */
.session-footer {
  padding-top: 0.5rem;
  border-top: 1px solid var(--border-color);
}

.session-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

/* 반응형 */
@media (max-width: 768px) {
  .session-card {
    padding: 0.75rem;
  }
  
  .session-meta {
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  
  .session-query,
  .session-answer {
    font-size: 0.85rem;
  }
}
</style>
