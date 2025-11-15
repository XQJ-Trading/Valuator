<template>
  <div class="comparison-view">
    <div class="comparison-container">
      <!-- Original Panel -->
      <div class="panel original-panel">
        <div class="panel-header">
          <h3 class="panel-title">
            <span class="title-icon">📝</span>
            Original Task
          </h3>
          <button @click="copyOriginal" class="btn-copy" title="복사">
            <span class="copy-icon">📋</span>
            복사
          </button>
        </div>
        <div class="panel-content">
          <pre class="panel-text">{{ original }}</pre>
        </div>
      </div>

      <!-- Divider -->
      <div class="divider">
        <div class="divider-line"></div>
        <div class="divider-icon">↔️</div>
        <div class="divider-line"></div>
      </div>

      <!-- Rewritten Panel -->
      <div class="panel rewritten-panel">
        <div class="panel-header">
          <h3 class="panel-title">
            <span class="title-icon">✨</span>
            Rewritten Task
          </h3>
          <button @click="copyRewritten" class="btn-copy" title="복사">
            <span class="copy-icon">📋</span>
            복사
          </button>
        </div>
        <div class="panel-content">
          <pre class="panel-text">{{ rewritten }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
interface Props {
  original: string
  rewritten: string
}

defineProps<Props>()

const emit = defineEmits<{
  (e: 'copyOriginal'): void
  (e: 'copyRewritten'): void
}>()

function copyOriginal() {
  emit('copyOriginal')
}

function copyRewritten() {
  emit('copyRewritten')
}
</script>

<style scoped>
.comparison-view {
  width: 100%;
}

.comparison-container {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 1rem;
  align-items: start;
}

.panel {
  background: white;
  border: 2px solid var(--border-color);
  border-radius: var(--border-radius);
  display: flex;
  flex-direction: column;
  height: 600px;
  overflow: hidden;
}

.original-panel {
  border-color: #e5e7eb;
}

.rewritten-panel {
  border-color: #dbeafe;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.25rem;
  border-bottom: 2px solid var(--border-color);
  background: var(--bg-tertiary);
}

.original-panel .panel-header {
  background: #f9fafb;
  border-bottom-color: #e5e7eb;
}

.rewritten-panel .panel-header {
  background: #eff6ff;
  border-bottom-color: #dbeafe;
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  font-size: 1.1rem;
  color: var(--text-primary);
  font-weight: 600;
}

.title-icon {
  font-size: 1.2rem;
}

.btn-copy {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.75rem;
  background: white;
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  color: var(--text-primary);
  font-size: 0.85rem;
  cursor: pointer;
  transition: var(--transition);
}

.btn-copy:hover {
  background: var(--bg-secondary);
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.copy-icon {
  font-size: 0.9rem;
}

.panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
}

.panel-text {
  margin: 0;
  white-space: pre-wrap;
  word-wrap: break-word;
  font-family: inherit;
  font-size: 0.95rem;
  line-height: 1.7;
  color: var(--text-primary);
}

.divider {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 1rem 0;
  gap: 0.5rem;
}

.divider-line {
  flex: 1;
  width: 2px;
  background: var(--border-color);
  min-height: 50px;
}

.divider-icon {
  font-size: 1.5rem;
  padding: 0.5rem;
  background: var(--bg-tertiary);
  border-radius: 50%;
}

/* 스크롤바 스타일링 */
.panel-content::-webkit-scrollbar {
  width: 8px;
}

.panel-content::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 4px;
}

.panel-content::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 4px;
}

.panel-content::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}

@media (max-width: 1024px) {
  .comparison-container {
    grid-template-columns: 1fr;
    gap: 1.5rem;
  }

  .divider {
    flex-direction: row;
    padding: 0 1rem;
  }

  .divider-line {
    width: 100%;
    height: 2px;
    min-height: 0;
  }

  .divider-icon {
    transform: rotate(90deg);
  }

  .panel {
    height: 400px;
  }
}

@media (max-width: 768px) {
  .panel {
    height: 350px;
  }

  .panel-header {
    padding: 0.75rem 1rem;
  }

  .panel-content {
    padding: 1rem;
  }

  .panel-title {
    font-size: 1rem;
  }

  .btn-copy {
    padding: 0.35rem 0.6rem;
    font-size: 0.8rem;
  }
}
</style>

