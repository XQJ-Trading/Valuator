<template>
  <div class="valuator-page valuator-task-page">
    <div class="valuator-page-header">
      <router-link :to="`/sessions/${sessionId}`" class="valuator-link-back">
        ← Back to Session
      </router-link>
      <h1>Task {{ taskId }}</h1>
    </div>

    <div v-if="loading" class="valuator-state">Loading task detail...</div>
    <div v-else-if="error" class="valuator-state valuator-state-error">{{ error }}</div>
    <div v-else-if="!taskDetail" class="valuator-state">Task detail not found.</div>

    <div v-else class="valuator-task-detail-grid">
      <section class="valuator-task-panel">
        <h2>Execution</h2>
        <div class="valuator-markdown" v-html="executionHtml"></div>
      </section>

      <section class="valuator-task-panel">
        <h2>Aggregation</h2>
        <div class="valuator-markdown" v-html="aggregationHtml"></div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { renderMarkdown } from '../utils/markdownUtils'
import { useValuatorSession } from '../composables/useValuatorSession'

interface Props {
  sessionId: string
  taskId: string
}

const props = defineProps<Props>()
const { taskDetail, loading, error, fetchTaskDetail } = useValuatorSession()

const sessionId = computed(() => props.sessionId)
const taskId = computed(() => props.taskId)

const executionHtml = computed(() => renderMarkdown(taskDetail.value?.execution_markdown || ''))
const aggregationHtml = computed(() => renderMarkdown(taskDetail.value?.aggregation_markdown || ''))

watch(
  () => [props.sessionId, props.taskId],
  ([nextSessionId, nextTaskId]) => {
    void fetchTaskDetail(nextSessionId, nextTaskId)
  },
  { immediate: true }
)
</script>

<style scoped>
.valuator-page {
  min-height: calc(100vh - 60px);
  max-width: 1200px;
  margin: 0 auto;
  padding: 1rem;
}

.valuator-page-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.valuator-page-header h1 {
  margin: 0;
  font-size: 1.3rem;
}

.valuator-link-back {
  text-decoration: none;
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
  padding: 0.4rem 0.65rem;
  font-size: 0.85rem;
  font-weight: 600;
}

.valuator-task-detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.valuator-task-panel {
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  background: var(--bg-secondary);
  padding: 0.9rem;
  min-width: 0;
}

.valuator-task-panel h2 {
  margin: 0 0 0.7rem;
  font-size: 1rem;
}

.valuator-markdown {
  background: white;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 0.85rem;
  overflow-x: auto;
}

.valuator-state {
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  background: var(--bg-secondary);
  padding: 1rem;
}

.valuator-state-error {
  color: var(--error-color);
}

@media (max-width: 980px) {
  .valuator-task-detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>
