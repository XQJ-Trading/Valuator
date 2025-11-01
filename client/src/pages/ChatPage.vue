<template>
  <div class="chat-page">
    <!-- Input Section -->
    <InputSection 
      v-model:query="query"
      v-model:rule="rule"
      v-model:selectedModel="selectedModel"
      :loading="loading"
      :availableModels="availableModels"
      @send="handleCreateSession"
      @stream="handleCreateSession"
      @clear="clearAll"
    />

    <!-- Status Bar -->
    <StatusBar :status="status" :loading="loading" />

    <!-- Messages Container -->
    <MessagesContainer :messages="messages" />
  </div>
</template>

<script setup lang="ts">
import InputSection from '../components/InputSection.vue'
import StatusBar from '../components/StatusBar.vue'
import MessagesContainer from '../components/MessagesContainer.vue'
import { useSession } from '../composables/useSession'
import { useRouter } from 'vue-router'

// Session mode only
const {
  query,
  rule,
  status,
  loading,
  messages,
  selectedModel,
  availableModels,
  clearAll,
  createSession
} = useSession()

const router = useRouter()

// Session mode handlers
const handleCreateSession = async () => {
  const sessionId = await createSession()
  if (sessionId) {
    router.push(`/session/${sessionId}`)
  }
}

</script>

<style scoped>
.chat-page {
  min-height: calc(100vh - 60px);
  max-width: 1200px;
  margin: 0 auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
}

.mode-toggle {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 1.5rem;
  padding: 1rem;
  background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
  border-radius: 8px;
}

.toggle-label {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  cursor: pointer;
  user-select: none;
  font-weight: 600;
  color: #333;
}

.toggle-input {
  width: 24px;
  height: 24px;
  cursor: pointer;
  accent-color: #667eea;
}

.toggle-text {
  font-size: 0.95rem;
  transition: color 0.2s;
}

.toggle-label:hover .toggle-text {
  color: #667eea;
}

@media (max-width: 768px) {
  .chat-page {
    min-height: calc(100vh - 50px);
    padding: 0 0.75rem;
  }

  .mode-toggle {
    margin-bottom: 1rem;
    padding: 0.75rem;
  }

  .toggle-text {
    font-size: 0.9rem;
  }
}

@media (max-width: 480px) {
  .chat-page {
    min-height: calc(100vh - 45px);
    padding: 0 0.5rem;
  }

  .mode-toggle {
    margin-bottom: 0.75rem;
    padding: 0.5rem;
  }

  .toggle-label {
    flex-direction: column;
    gap: 0.5rem;
  }

  .toggle-text {
    font-size: 0.85rem;
  }
}
</style>
