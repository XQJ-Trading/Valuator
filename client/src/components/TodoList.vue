<template>
  <div class="todo-list-panel" v-if="todo">
    <div class="todo-header">
      <h3>📋 작업 목록</h3>
      <button @click="isExpanded = !isExpanded" class="toggle-btn">
        {{ isExpanded ? '▼' : '▶' }}
      </button>
    </div>
    <div v-if="isExpanded" class="todo-content markdown-body" v-html="renderMarkdown(todo)"></div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { renderMarkdown } from '../utils/markdownUtils'

interface Props {
  todo: string | null
}

const props = defineProps<Props>()
const isExpanded = ref(true)
</script>

<style scoped>
.todo-list-panel {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(59, 130, 246, 0.05) 100%);
  border: 2px solid #3b82f6;
  border-radius: var(--border-radius);
  padding: 1rem;
  margin-bottom: 1.5rem;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
}

.todo-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}

.todo-header h3 {
  margin: 0;
  color: #3b82f6;
  font-size: 1.1rem;
}

.toggle-btn {
  background: none;
  border: none;
  color: #3b82f6;
  font-size: 1rem;
  cursor: pointer;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  transition: background 0.2s;
}

.toggle-btn:hover {
  background: rgba(59, 130, 246, 0.1);
}

.todo-content {
  padding: 0.75rem;
  background: rgba(59, 130, 246, 0.03);
  border-radius: 8px;
  border: 1px solid rgba(59, 130, 246, 0.15);
  max-height: 400px;
  overflow-y: auto;
}

.todo-content :deep(ul) {
  list-style: none;
  padding-left: 0;
}

.todo-content :deep(li) {
  padding: 0.5rem 0;
  border-bottom: 1px solid rgba(59, 130, 246, 0.1);
}

.todo-content :deep(li:last-child) {
  border-bottom: none;
}

.todo-content :deep(input[type="checkbox"]) {
  margin-right: 0.5rem;
  width: 1.1rem;
  height: 1.1rem;
  cursor: pointer;
}

.todo-content :deep(input[type="checkbox"]:checked + label) {
  text-decoration: line-through;
  opacity: 0.6;
  color: var(--text-secondary);
}

/* 반응형 디자인 */
@media (max-width: 768px) {
  .todo-list-panel {
    padding: 0.85rem;
    margin-bottom: 1rem;
  }

  .todo-header h3 {
    font-size: 1rem;
  }

  .todo-content {
    padding: 0.6rem;
    max-height: 300px;
  }
}

@media (max-width: 480px) {
  .todo-list-panel {
    padding: 0.75rem;
    margin-bottom: 0.85rem;
  }

  .todo-header h3 {
    font-size: 0.95rem;
  }

  .todo-content {
    padding: 0.5rem;
    max-height: 250px;
  }
}
</style>

