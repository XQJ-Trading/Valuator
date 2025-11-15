<template>
  <div class="rewrite-card" @click="handleCardClick">
    <div class="card-header">
      <div class="card-meta">
        <span class="card-time">{{ formatTime(rewrite.created_at) }}</span>
        <span class="card-model">🤖 {{ rewrite.model }}</span>
      </div>
      <div class="card-actions">
        <button @click="handleDeleteClick" class="btn-delete" title="삭제">
          🗑️
        </button>
      </div>
    </div>

    <div class="card-body">
      <div class="card-original">
        <strong>Original:</strong> {{ truncate(rewrite.original_task, 120) }}
      </div>
      <div class="card-rewritten">
        <strong>Rewritten:</strong> {{ truncate(rewrite.rewritten_task, 150) }}
      </div>
    </div>

    <div class="card-footer">
      <span class="card-id">ID: {{ rewrite.rewrite_id.substring(0, 8) }}...</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { TaskRewriteHistory } from '../../types/TaskRewrite'

interface Props {
  rewrite: TaskRewriteHistory
}

interface Emits {
  (e: 'click', rewriteId: string): void
  (e: 'delete', rewriteId: string): void
}

const props = defineProps<Props>()
const $emit = defineEmits<Emits>()

function formatTime(timestamp: string): string {
  try {
    const date = new Date(timestamp)
    const now = new Date()
    const diff = now.getTime() - date.getTime()

    if (diff < 60000) {
      return '방금 전'
    } else if (diff < 3600000) {
      const minutes = Math.floor(diff / 60000)
      return `${minutes}분 전`
    } else if (diff < 86400000) {
      const hours = Math.floor(diff / 3600000)
      return `${hours}시간 전`
    } else {
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
  $emit('click', props.rewrite.rewrite_id)
}

function handleDeleteClick(event: Event) {
  event.stopPropagation()
  $emit('delete', props.rewrite.rewrite_id)
}
</script>

<style scoped>
.rewrite-card {
  border-radius: var(--border-radius);
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  transition: var(--transition);
  border: 2px solid #e5e7eb;
  margin-bottom: 1rem;
  cursor: pointer;
  background: #ffffff;
}

.rewrite-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  border-color: #d1d5db;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  background: #f1f5f9;
  border-bottom: 1px solid #e5e7eb;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 1rem;
  font-size: 0.85rem;
  flex: 1;
}

.card-time {
  color: var(--text-secondary);
  font-weight: 500;
}

.card-model {
  color: var(--primary-color);
  font-weight: 600;
  font-size: 0.8rem;
}

.card-actions {
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
}

.btn-delete:hover {
  background: #fee2e2;
  border-color: #fca5a5;
  color: #dc2626;
}

.card-body {
  padding: 1.25rem;
}

.card-original,
.card-rewritten {
  margin-bottom: 0.75rem;
  font-size: 0.95rem;
  line-height: 1.6;
}

.card-original {
  color: var(--text-primary);
  font-weight: 500;
}

.card-rewritten {
  color: var(--text-secondary);
  line-height: 1.7;
}

.card-original strong,
.card-rewritten strong {
  color: #374151;
  margin-right: 0.5rem;
  font-weight: 600;
}

.card-footer {
  padding: 0.75rem 1.25rem;
  border-top: 1px solid #e5e7eb;
  background: #fafbfc;
}

.card-id {
  font-size: 0.75rem;
  color: #9ca3af;
  font-family: monospace;
}

@media (max-width: 768px) {
  .card-header {
    padding: 0.75rem 1rem;
    flex-wrap: wrap;
  }

  .card-body {
    padding: 1rem;
  }

  .card-footer {
    padding: 0.75rem 1rem;
  }

  .card-meta {
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .card-original,
  .card-rewritten {
    font-size: 0.9rem;
  }
}
</style>

