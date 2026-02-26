<template>
  <div class="valuator-page valuator-final-page">
    <div class="valuator-page-header">
      <router-link :to="`/sessions/${sessionId}`" class="valuator-link-back">
        ← Back to Session
      </router-link>
      <h1>Final Report</h1>
    </div>

    <div v-if="loading" class="valuator-state">Loading final report...</div>
    <div v-else-if="error" class="valuator-state valuator-state-error">{{ error }}</div>
    <div v-else-if="!finalDocument" class="valuator-state">Final report not found.</div>
    <div v-else class="valuator-final-container">
      <div class="valuator-markdown" v-html="finalHtml"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { renderMarkdown } from '../utils/markdownUtils'
import { useValuatorSession } from '../composables/useValuatorSession'

interface Props {
  sessionId: string
}

const props = defineProps<Props>()
const { finalDocument, loading, error, fetchFinalDocument } = useValuatorSession()

const sessionId = computed(() => props.sessionId)
const finalHtml = computed(() => renderMarkdown(finalDocument.value?.markdown || ''))

watch(
  () => props.sessionId,
  (nextSessionId) => {
    void fetchFinalDocument(nextSessionId)
  },
  { immediate: true }
)
</script>

<style scoped>
.valuator-page {
  min-height: calc(100vh - 60px);
  max-width: 1100px;
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

.valuator-final-container {
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  background: var(--bg-secondary);
  padding: 0.9rem;
}

.valuator-markdown {
  border: 1px solid var(--border-color);
  background: white;
  border-radius: 10px;
  padding: 1rem;
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
</style>
