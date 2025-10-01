<template>
  <div class="status-bar" :class="statusClass">
    <div class="status-content">
      <span class="status-icon">{{ statusIcon }}</span>
      <span class="status-text">{{ status }}</span>
      <div v-if="loading" class="progress-bar">
        <div class="progress-fill"></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  status: string
  loading: boolean
}

const props = defineProps<Props>()

const statusClass = computed(() => {
  if (props.loading) return 'status-loading'
  if (props.status.includes('Error') || props.status.includes('오류')) return 'status-error'
  if (props.status === '완료' || props.status === 'Done') return 'status-success'
  return 'status-idle'
})

const statusIcon = computed(() => {
  if (props.loading) return '⏳'
  if (props.status.includes('Error') || props.status.includes('오류')) return '❌'
  if (props.status === '완료' || props.status === 'Done') return '✅'
  return '💤'
})
</script>

<style scoped>
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
</style>
