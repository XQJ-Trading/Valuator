<template>
  <div class="json-viewer">
    <div class="json-viewer-header">
      <div class="viewer-tabs">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          :class="['tab-btn', { active: activeTab === tab.key }]"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </div>
      <div class="viewer-actions">
        <button @click="handleCopy" class="btn-action" title="복사">
          📋 복사
        </button>
        <button @click="toggleExpandAll" class="btn-action" title="전체 펼치기/접기">
          {{ expanded ? '🔽 접기' : '▶️ 펼치기' }}
        </button>
      </div>
    </div>
    
    <div class="json-viewer-content">
      <div v-if="activeTab === 'request'" class="tab-content">
        <FormattedRequestViewer :data="requestData" />
      </div>
      <div v-else-if="activeTab === 'response'" class="tab-content">
        <FormattedJsonViewer :data="responseData" :expanded="expanded" />
      </div>
      <div v-else class="tab-content">
        <FormattedJsonViewer :data="rawData" :expanded="expanded" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import FormattedJsonViewer from './FormattedJsonViewer.vue'
import FormattedRequestViewer from './FormattedRequestViewer.vue'

interface Props {
  data: any
}

const props = defineProps<Props>()

const activeTab = ref<'request' | 'response' | 'raw'>('request')
const expanded = ref(true)

const tabs = [
  { key: 'request' as const, label: 'Request' },
  { key: 'response' as const, label: 'Response' },
  { key: 'raw' as const, label: 'Raw JSON' },
]

const requestData = computed(() => props.data?.request || {})
const responseData = computed(() => props.data?.response || {})
const rawData = computed(() => props.data || {})

function toggleExpandAll() {
  expanded.value = !expanded.value
}

async function handleCopy() {
  let textToCopy = ''
  
  if (activeTab.value === 'request') {
    textToCopy = JSON.stringify(requestData.value, null, 2)
  } else if (activeTab.value === 'response') {
    textToCopy = JSON.stringify(responseData.value, null, 2)
  } else {
    textToCopy = JSON.stringify(rawData.value, null, 2)
  }
  
  try {
    await navigator.clipboard.writeText(textToCopy)
    alert('복사되었습니다!')
  } catch (err) {
    console.error('Failed to copy:', err)
    alert('복사에 실패했습니다.')
  }
}
</script>

<style scoped>
.json-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  border-radius: var(--border-radius);
  overflow: hidden;
  border: 1px solid var(--border-color);
}

.json-viewer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  flex-wrap: wrap;
  gap: 1rem;
}

.viewer-tabs {
  display: flex;
  gap: 0.5rem;
}

.tab-btn {
  padding: 0.5rem 1rem;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  color: var(--text-secondary);
  cursor: pointer;
  transition: var(--transition);
  font-weight: 500;
}

.tab-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.tab-btn.active {
  background: var(--primary-color);
  color: white;
  border-color: var(--primary-color);
}

.viewer-actions {
  display: flex;
  gap: 0.5rem;
}

.btn-action {
  padding: 0.5rem 1rem;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  color: var(--text-primary);
  cursor: pointer;
  transition: var(--transition);
  font-size: 0.9rem;
  font-weight: 500;
}

.btn-action:hover {
  background: var(--bg-tertiary);
  border-color: var(--primary-color);
}

.json-viewer-content {
  flex: 1;
  overflow: auto;
  padding: 1rem;
}

.tab-content {
  height: 100%;
}
</style>

