<template>
  <div class="formatted-json-viewer">
    <JsonNode
      :data="data"
      :key-name="''"
      :depth="0"
      :expanded="expanded"
    />
  </div>
</template>

<script setup lang="ts">
import JsonNode from './JsonNode.vue'

interface Props {
  data: any
  expanded?: boolean
}

defineProps<Props>()
</script>

<style scoped>
.formatted-json-viewer {
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 0.9rem;
  line-height: 1.6;
  color: var(--text-primary);
}
</style>

