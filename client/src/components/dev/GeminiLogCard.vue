<template>
  <div class="log-card" @click="handleCardClick">
    <div class="log-header">
      <div class="log-meta">
        <span class="log-icon">📄</span>
        <span class="log-filename">{{ log.filename }}</span>
      </div>
      <div class="log-actions">
        <button @click="handleDownloadClick" class="btn-download" title="다운로드">
          ⬇️
        </button>
      </div>
    </div>
    
    <div class="log-body">
      <div class="log-info">
        <span class="info-item">
          <span class="info-label">📅</span>
          {{ log.date }} {{ log.time }}
        </span>
        <span v-if="log.model" class="info-item">
          <span class="info-label">🤖</span>
          {{ log.model }}
        </span>
        <span class="info-item">
          <span class="info-label">📦</span>
          {{ log.size_formatted }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { GeminiLogFile } from '../../composables/useGeminiLogs'
import { useRouter } from 'vue-router'

interface Props {
  log: GeminiLogFile
}

interface Emits {
  (e: 'download', filename: string): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()
const router = useRouter()

function handleCardClick() {
  router.push(`/dev/gemini-logs/${encodeURIComponent(props.log.filename)}`)
}

function handleDownloadClick(event: Event) {
  event.stopPropagation()
  emit('download', props.log.filename)
}
</script>

<style scoped>
.log-card {
  border-radius: var(--border-radius);
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  transition: var(--transition);
  border: 2px solid #e5e7eb;
  margin-bottom: 1rem;
  cursor: pointer;
  background: #ffffff;
}

.log-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  border-color: #6366f1;
}

.log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  background: #f8fafc;
  border-bottom: 1px solid #e5e7eb;
}

.log-meta {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex: 1;
  min-width: 0;
}

.log-icon {
  font-size: 1.25rem;
  flex-shrink: 0;
}

.log-filename {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.log-actions {
  display: flex;
  gap: 0.5rem;
  flex-shrink: 0;
}

.btn-download {
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

.btn-download:hover {
  background: #6366f1;
  border-color: #4f46e5;
  color: white;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.btn-download:active {
  background: #4f46e5;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
}

.log-body {
  padding: 1rem 1.25rem;
}

.log-info {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  font-size: 0.85rem;
}

.info-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--text-secondary);
}

.info-label {
  font-size: 0.9rem;
}

@media (max-width: 768px) {
  .log-header {
    padding: 0.75rem 1rem;
    flex-wrap: wrap;
  }
  
  .log-body {
    padding: 0.75rem 1rem;
  }
  
  .log-info {
    gap: 0.75rem;
    font-size: 0.8rem;
  }
  
  .log-filename {
    font-size: 0.85rem;
  }
}
</style>

