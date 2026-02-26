<template>
  <aside class="valuator-sidebar">
    <section class="valuator-sidebar-section">
      <h3 class="valuator-sidebar-title">Query</h3>
      <p class="valuator-sidebar-query">{{ query }}</p>
    </section>

    <section class="valuator-sidebar-section">
      <h3 class="valuator-sidebar-title">Output</h3>
      <router-link :to="finalRoute" class="valuator-sidebar-link">
        Open final markdown
      </router-link>
    </section>

    <section class="valuator-sidebar-section">
      <h3 class="valuator-sidebar-title">Panels</h3>
      <label class="valuator-sidebar-toggle">
        <input
          type="checkbox"
          :checked="showExecution"
          @change="onExecutionChange"
        />
        <span>Execution</span>
      </label>
      <label class="valuator-sidebar-toggle">
        <input
          type="checkbox"
          :checked="showAggregation"
          @change="onAggregationChange"
        />
        <span>Aggregation</span>
      </label>
    </section>
  </aside>
</template>

<script setup lang="ts">
interface Props {
  query: string
  finalRoute: string
  showExecution: boolean
  showAggregation: boolean
}

interface Emits {
  (e: 'update:showExecution', value: boolean): void
  (e: 'update:showAggregation', value: boolean): void
}

defineProps<Props>()
const emit = defineEmits<Emits>()

function onExecutionChange(event: Event) {
  const target = event.target as HTMLInputElement
  emit('update:showExecution', target.checked)
}

function onAggregationChange(event: Event) {
  const target = event.target as HTMLInputElement
  emit('update:showAggregation', target.checked)
}
</script>

<style scoped>
.valuator-sidebar {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
}

.valuator-sidebar-section {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.valuator-sidebar-title {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--text-primary);
}

.valuator-sidebar-query {
  margin: 0;
  color: var(--text-secondary);
  white-space: pre-wrap;
  line-height: 1.4;
  font-size: 0.9rem;
}

.valuator-sidebar-link {
  display: inline-flex;
  width: fit-content;
  text-decoration: none;
  color: white;
  background: var(--primary-color);
  border-radius: 8px;
  padding: 0.45rem 0.7rem;
  font-size: 0.85rem;
  font-weight: 600;
}

.valuator-sidebar-link:hover {
  opacity: 0.9;
}

.valuator-sidebar-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  color: var(--text-primary);
  font-size: 0.9rem;
}
</style>
