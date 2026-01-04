<template>
  <div class="formatted-request-viewer">
    <div
      v-for="(content, index) in contents"
      :key="index"
      class="content-block"
    >
      <div class="content-header">
        <span class="role-badge" :class="`role-${content.role}`">
          {{ content.role }}
        </span>
        <span class="content-index">#{{ index + 1 }}</span>
      </div>
      
      <div class="content-parts">
        <div
          v-for="(part, partIndex) in content.parts"
          :key="partIndex"
          class="part-block"
        >
          <div v-if="typeof part === 'string'" class="text-part">
            <FormattedTextViewer :text="part" />
          </div>
          <div v-else class="object-part">
            <FormattedJsonViewer :data="part" :expanded="true" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import FormattedTextViewer from './FormattedTextViewer.vue'
import FormattedJsonViewer from './FormattedJsonViewer.vue'

interface Props {
  data: any
}

const props = defineProps<Props>()

const contents = computed(() => {
  if (!props.data || !props.data.contents) {
    return []
  }
  return props.data.contents || []
})
</script>

<style scoped>
.formatted-request-viewer {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.content-block {
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  overflow: hidden;
  background: var(--bg-secondary);
}

.content-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border-color);
}

.role-badge {
  padding: 0.25rem 0.75rem;
  border-radius: 12px;
  font-size: 0.85rem;
  font-weight: 600;
  text-transform: uppercase;
}

.role-user {
  background: #dbeafe;
  color: #1e40af;
}

.role-model {
  background: #dcfce7;
  color: #166534;
}

.role-assistant {
  background: #fef3c7;
  color: #92400e;
}

.content-index {
  font-size: 0.8rem;
  color: var(--text-secondary);
  font-weight: 500;
}

.content-parts {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1rem;
}

.part-block {
  border-left: 3px solid var(--primary-color);
  padding-left: 1rem;
}

.text-part {
  background: var(--bg-primary);
  padding: 1rem;
  border-radius: var(--border-radius);
  word-wrap: break-word;
  white-space: pre-wrap;
}

.object-part {
  background: var(--bg-primary);
  padding: 1rem;
  border-radius: var(--border-radius);
}
</style>

