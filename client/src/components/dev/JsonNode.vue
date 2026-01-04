<template>
  <div class="json-node">
    <div
      v-if="isObject || isArray"
      class="json-container"
    >
      <div class="json-line" @click="toggleExpand">
        <span class="json-key" v-if="keyName">{{ keyName }}:</span>
        <span class="json-bracket">{{ isArray ? '[' : '{' }}</span>
        <span class="json-count">
          {{ isArray ? `${data.length} items` : `${Object.keys(data).length} keys` }}
        </span>
        <span class="json-toggle">{{ isExpanded ? '▼' : '▶' }}</span>
      </div>
      
      <div v-if="isExpanded" class="json-children">
        <JsonNode
          v-for="(value, index) in items"
          :key="index"
          :data="value"
          :key-name="isArray ? '' : String(index)"
          :depth="depth + 1"
          :expanded="expanded"
        />
        <div class="json-line">
          <span class="json-bracket">{{ isArray ? ']' : '}' }}</span>
        </div>
      </div>
    </div>
    
    <div v-else class="json-value-line">
      <span class="json-key" v-if="keyName">{{ keyName }}:</span>
      <span :class="['json-value', valueType]">{{ formattedValue }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

interface Props {
  data: any
  keyName: string
  depth: number
  expanded: boolean
}

const props = defineProps<Props>()

const localExpanded = ref(props.expanded || props.depth < 2)

const isObject = computed(() => {
  return typeof props.data === 'object' && props.data !== null && !Array.isArray(props.data)
})

const isArray = computed(() => {
  return Array.isArray(props.data)
})

const isExpanded = computed(() => {
  return localExpanded.value
})

const items = computed(() => {
  if (isArray.value) {
    return props.data
  } else if (isObject.value) {
    return Object.entries(props.data)
  }
  return []
})

const valueType = computed(() => {
  if (props.data === null) return 'null'
  if (typeof props.data === 'string') return 'string'
  if (typeof props.data === 'number') return 'number'
  if (typeof props.data === 'boolean') return 'boolean'
  return 'other'
})

const formattedValue = computed(() => {
  if (props.data === null) return 'null'
  if (typeof props.data === 'string') {
    // 긴 문자열은 줄바꿈 처리
    if (props.data.length > 200) {
      return `"${props.data.substring(0, 200)}... (${props.data.length} chars)"`
    }
    return `"${props.data}"`
  }
  if (typeof props.data === 'number') return String(props.data)
  if (typeof props.data === 'boolean') return String(props.data)
  return String(props.data)
})

function toggleExpand() {
  localExpanded.value = !localExpanded.value
}
</script>

<style scoped>
.json-node {
  margin-left: calc(var(--depth, 0) * 1.5rem);
}

.json-container {
  margin: 0.25rem 0;
}

.json-line {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
}

.json-line:hover {
  background: var(--bg-tertiary);
  border-radius: 4px;
}

.json-key {
  color: #7c3aed;
  font-weight: 600;
}

.json-bracket {
  color: #64748b;
  font-weight: 600;
}

.json-count {
  color: var(--text-secondary);
  font-size: 0.85em;
  font-style: italic;
}

.json-toggle {
  color: var(--text-secondary);
  font-size: 0.8em;
  margin-left: auto;
}

.json-children {
  margin-left: 1.5rem;
  border-left: 1px solid var(--border-color);
  padding-left: 0.5rem;
}

.json-value-line {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.25rem 0;
  word-break: break-word;
}

.json-value {
  flex: 1;
}

.json-value.string {
  color: #059669;
  white-space: pre-wrap;
  word-break: break-word;
}

.json-value.number {
  color: #0284c7;
}

.json-value.boolean {
  color: #dc2626;
}

.json-value.null {
  color: #9ca3af;
  font-style: italic;
}

.json-value.other {
  color: var(--text-primary);
}
</style>

