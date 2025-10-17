<template>
  <div class="page-container">
    <div class="page-content">
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

<!-- 공통 스타일은 styles/layout/_page-base.css로 이동 -->
