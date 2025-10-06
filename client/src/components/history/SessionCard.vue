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
  border-radius: var(--border-radius);
  overflow: hidden;
  box-shadow: var(--shadow-md);
  transition: var(--transition);
  border: 2px solid;
  margin-bottom: 1rem;
  cursor: pointer;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(59, 130, 246, 0.05) 100%);
  border-color: var(--primary-color);
}

.session-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lg);
}

.session-success {
  background: linear-gradient(135deg, rgba(34, 197, 94, 0.1) 0%, rgba(34, 197, 94, 0.05) 100%);
  border-color: #22c55e;
  box-shadow: 0 4px 12px rgba(34, 197, 94, 0.2);
}

.session-success:hover {
  box-shadow: 0 8px 25px rgba(34, 197, 94, 0.3);
}

.session-failed {
  background: linear-gradient(135deg, rgba(220, 38, 38, 0.1) 0%, rgba(220, 38, 38, 0.05) 100%);
  border-color: var(--error-color);
  box-shadow: 0 4px 12px rgba(220, 38, 38, 0.2);
}

.session-failed:hover {
  box-shadow: 0 8px 25px rgba(220, 38, 38, 0.3);
}

/* 헤더 */
.session-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  font-weight: 500;
  border-bottom: 1px solid var(--border-color);
}

.session-success .session-header {
  background: rgba(34, 197, 94, 0.1);
  color: #059669;
}

.session-failed .session-header {
  background: rgba(220, 38, 38, 0.1);
  color: var(--error-color);
}

.session-meta {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.85rem;
  flex: 1;
}

.session-status {
  font-size: 1.25rem;
}

.session-time {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.session-duration {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.session-actions {
  display: flex;
  gap: 0.5rem;
}

.btn-delete {
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

.btn-delete::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.3), transparent);
  transition: left 0.3s ease;
}

.btn-delete:hover {
  transform: scale(1.05) translateY(-1px);
  background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%);
  border-color: #dc2626;
  box-shadow: 0 4px 12px rgba(220, 38, 38, 0.3);
}

.btn-delete:hover::before {
  left: 100%;
}

.btn-delete:active {
  transform: scale(0.98);
  box-shadow: 0 1px 3px rgba(220, 38, 38, 0.2);
}

/* 본문 */
.session-body {
  padding: 1.25rem;
}

.session-query,
.session-answer {
  margin-bottom: 0.75rem;
  font-size: 1rem;
  line-height: 1.6;
}

.session-query {
  color: var(--text-primary);
  font-weight: 500;
}

.session-answer {
  color: var(--text-secondary);
  line-height: 1.7;
}

.session-query strong,
.session-answer strong {
  color: var(--primary-color);
  margin-right: 0.5rem;
  font-weight: 600;
}

.session-success .session-query strong,
.session-success .session-answer strong {
  color: #059669;
}

.session-failed .session-query strong,
.session-failed .session-answer strong {
  color: var(--error-color);
}

/* 푸터 */
.session-footer {
  padding: 0.75rem 1.25rem;
  border-top: 1px solid var(--border-color);
  background: rgba(0, 0, 0, 0.02);
}

.session-success .session-footer {
  background: rgba(34, 197, 94, 0.05);
}

.session-failed .session-footer {
  background: rgba(220, 38, 38, 0.05);
}

.session-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 500;
  padding: 0.25rem 0.5rem;
  background: rgba(0, 0, 0, 0.05);
  border-radius: 12px;
}

.session-success .stat-item {
  background: rgba(34, 197, 94, 0.1);
  color: #059669;
}

.session-failed .stat-item {
  background: rgba(220, 38, 38, 0.1);
  color: var(--error-color);
}

/* 반응형 */
@media (max-width: 768px) {
  .session-header {
    padding: 0.75rem 1rem;
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  
  .session-body {
    padding: 1rem;
  }
  
  .session-footer {
    padding: 0.75rem 1rem;
  }
  
  .session-meta {
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  
  .session-query,
  .session-answer {
    font-size: 0.9rem;
  }
  
  .session-stats {
    gap: 0.5rem;
  }
  
  .stat-item {
    font-size: 0.8rem;
  }
}
</style>
