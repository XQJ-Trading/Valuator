<template>
  <div class="app-container">
    <!-- Header -->
    <AppHeader @history="handleHistory" @newSession="handleNewSession" />

    <!-- Input Section -->
    <InputSection 
      v-model:query="query"
      v-model:rule="rule"
      :loading="loading"
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
import AppHeader from './components/AppHeader.vue'
import InputSection from './components/InputSection.vue'
import StatusBar from './components/StatusBar.vue'
import MessagesContainer from './components/MessagesContainer.vue'
import { useChat } from './composables/useChat'

const {
  query,
  rule,
  status,
  loading,
  messages,
  clearAll,
  send,
  stream
} = useChat()

function handleHistory() {
  // History 기능은 AppHeader에서 처리됨 (Coming Soon 모달)
  console.log('History clicked')
}

function handleNewSession() {
  clearAll()
  console.log('New session started')
}
</script>

<style>
/* CSS 변수 import */
@import './styles/variables.css';

/* 메인 컨테이너 */
.app-container {
  min-height: 100vh;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif;
  transition: var(--transition);
}
</style>
