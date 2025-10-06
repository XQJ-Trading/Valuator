<template>
  <div class="chat-page">
    <!-- Input Section -->
    <InputSection 
      v-model:query="query"
      v-model:rule="rule"
      v-model:selectedModel="selectedModel"
      :loading="loading"
      :availableModels="availableModels"
      @send="send"
      @stream="stream"
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
import { useChat } from '../composables/useChat'

const {
  query,
  rule,
  status,
  loading,
  messages,
  selectedModel,
  availableModels,
  clearAll,
  send,
  stream,
  setModel
} = useChat()
</script>

<style scoped>
.chat-page {
  min-height: calc(100vh - 80px);
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 1.5rem;
  display: flex;
  flex-direction: column;
}

@media (max-width: 768px) {
  .chat-page {
    padding: 0 1rem;
  }
}
</style>
