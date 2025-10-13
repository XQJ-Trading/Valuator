<template>
  <div class="session-card" :class="{ 'session-completed': session.success, 'session-error': !session.success }" @click="handleCardClick">
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
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  transition: var(--transition);
  border: 2px solid #e5e7eb;
  margin-bottom: 1rem;
  cursor: pointer;
  background: #ffffff;
}

.session-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  border-color: #d1d5db;
}

.session-completed {
  background: #ffffff;
  border-color: #6b7280;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
}

.session-completed:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
  border-color: #374151;
  background: #f8fafc;
}

.session-error {
  background: #f3f4f6;
  border-color: #9ca3af;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.session-error:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.14);
  border-color: #6b7280;
  background: #e5e7eb;
}

/* 헤더 */
.session-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  font-weight: 500;
  border-bottom: 1px solid #e5e7eb;
}

.session-completed .session-header {
  background: #f1f5f9;
  color: #1e293b;
  border-bottom-color: #0ea5e9;
}

.session-error .session-header {
  background: #f8f9fa;
  color: #422006;
  border-bottom-color: #f59e0b;
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
  background: #f3f4f6;
  color: #374151;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  padding: 0.4rem 0.75rem;
  cursor: pointer;
  transition: var(--transition);
  font-size: 0.85rem;
  font-weight: 500;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.btn-delete:hover {
  background: #e5e7eb;
  border-color: #9ca3af;
  color: #1f2937;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.btn-delete:active {
  background: #d1d5db;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
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
  color: #374151;
  margin-right: 0.5rem;
  font-weight: 600;
}

.session-completed .session-query strong,
.session-completed .session-answer strong {
  color: #059669;
}

.session-error .session-query strong,
.session-error .session-answer strong {
  color: #dc2626;
}

/* 푸터 */
.session-footer {
  padding: 0.75rem 1.25rem;
  border-top: 1px solid #d1d5db;
  background: #fafbfc;
}

.session-completed .session-footer {
  background: #f0f9ff;
  border-top-color: #0ea5e9;
}

.session-error .session-footer {
  background: #fef7f0;
  border-top-color: #f59e0b;
}

.session-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  font-size: 0.85rem;
  color: #4b5563;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 500;
  padding: 0.25rem 0.5rem;
  background: #e5e7eb;
  border-radius: 12px;
  color: #374151;
}

.session-completed .stat-item {
  background: #dbeafe;
  color: #1e40af;
  border: 1px solid #3b82f6;
}

.session-error .stat-item {
  background: #fed7aa;
  color: #9a3412;
  border: 1px solid #f59e0b;
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
