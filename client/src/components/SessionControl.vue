<template>
  <div class="session-control">
    <div class="control-container">
      <!-- Session ID 표시 -->
      <div v-if="currentSessionId" class="session-info">
        <span class="label">세션 ID:</span>
        <span class="session-id">{{ currentSessionId }}</span>
        <button 
          class="btn-copy" 
          @click="copySessionId"
          :title="copied ? '복사됨!' : '복사하기'"
        >
          📋
        </button>
      </div>

      <!-- Connection Status -->
      <div class="connection-status">
        <div :class="['status-indicator', connectionState.connected ? 'connected' : 'disconnected']">
          <span class="dot"></span>
          <span class="text">
            {{ connectionState.connected ? '연결됨' : '연결 끊김' }}
          </span>
        </div>

        <!-- Reconnection Status -->
        <div v-if="connectionState.reconnecting" class="reconnect-status">
          <span class="spinner"></span>
          {{ connectionState.reconnectAttempts }}/{{ MAX_RECONNECT_ATTEMPTS }}회 재연결 중...
        </div>

        <!-- Error Message -->
        <div v-if="connectionState.lastError && !connectionState.reconnecting" class="error-message">
          ⚠️ {{ connectionState.lastError }}
        </div>
      </div>

      <!-- Control Buttons -->
      <div class="button-group">
        <button 
          v-if="!isSessionActive"
          class="btn btn-primary"
          @click="handleCreateSession"
          :disabled="loading"
        >
          {{ loading ? '생성 중...' : '세션 생성' }}
        </button>

        <button 
          v-if="isSessionActive && !connectionState.connected"
          class="btn btn-warning"
          @click="handleReconnect"
        >
          🔄 재연결
        </button>

        <button 
          v-if="isSessionActive"
          class="btn btn-danger"
          @click="handleTerminate"
        >
          세션 종료
        </button>
      </div>

      <!-- Progress Info -->
      <div v-if="isSessionActive" class="progress-info">
        <div class="info-item">
          <span class="label">이벤트:</span>
          <span class="value">{{ sessionProgress }}</span>
        </div>
        <div class="info-item">
          <span class="label">상태:</span>
          <span :class="['status-badge', activeSession?.status]">
            {{ activeSession?.status === 'running' ? '실행중' : activeSession?.status === 'completed' ? '완료' : '실패' }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, toRefs } from 'vue'
import type { ConnectionState } from '../types/Session'

interface Props {
  currentSessionId: string | null
  connectionState: ConnectionState
  activeSession: any
  isSessionActive: boolean
  sessionProgress: number
  loading: boolean
}

interface Emits {
  (e: 'create-session'): void
  (e: 'reconnect'): void
  (e: 'terminate'): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const { currentSessionId, connectionState, activeSession, isSessionActive, sessionProgress, loading } = toRefs(props)

const copied = ref(false)
const MAX_RECONNECT_ATTEMPTS = 3

function copySessionId() {
  if (!currentSessionId.value) return
  
  navigator.clipboard.writeText(currentSessionId.value).then(() => {
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
  })
}

function handleCreateSession() {
  emit('create-session')
}

function handleReconnect() {
  emit('reconnect')
}

function handleTerminate() {
  if (confirm('정말로 세션을 종료하시겠습니까?')) {
    emit('terminate')
  }
}
</script>

<style scoped>
.session-control {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 1.5rem;
  color: white;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.15);
}

.control-container {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.session-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  font-size: 0.9rem;
}

.label {
  font-weight: 600;
  opacity: 0.9;
}

.session-id {
  font-family: 'Courier New', monospace;
  font-size: 0.85rem;
  word-break: break-all;
  flex: 1;
}

.btn-copy {
  background: rgba(255, 255, 255, 0.2);
  border: none;
  color: white;
  padding: 0.4rem 0.6rem;
  border-radius: 4px;
  cursor: pointer;
  font-size: 1rem;
  transition: background 0.2s;
}

.btn-copy:hover {
  background: rgba(255, 255, 255, 0.3);
}

.connection-status {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem;
  font-weight: 500;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.status-indicator.connected .dot {
  background-color: #4ade80;
  box-shadow: 0 0 8px rgba(74, 222, 128, 0.6);
}

.status-indicator.disconnected .dot {
  background-color: #ef4444;
  box-shadow: 0 0 8px rgba(239, 68, 68, 0.6);
}

.reconnect-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.9rem;
  opacity: 0.95;
}

.spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.error-message {
  padding: 0.75rem;
  background: rgba(239, 68, 68, 0.2);
  border-left: 3px solid #ef4444;
  border-radius: 4px;
  font-size: 0.9rem;
}

.button-group {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.btn {
  padding: 0.7rem 1.2rem;
  border: none;
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 0.95rem;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-primary {
  background-color: #4ade80;
  color: #16a34a;
}

.btn-primary:hover:not(:disabled) {
  background-color: #22c55e;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(74, 222, 128, 0.4);
}

.btn-warning {
  background-color: #facc15;
  color: #92400e;
}

.btn-warning:hover:not(:disabled) {
  background-color: #fbbf24;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(250, 204, 21, 0.4);
}

.btn-danger {
  background-color: #ef4444;
  color: #7f1d1d;
}

.btn-danger:hover:not(:disabled) {
  background-color: #f87171;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.4);
}

.progress-info {
  display: flex;
  gap: 1.5rem;
  padding: 0.75rem;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 8px;
}

.info-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.9rem;
}

.value {
  font-weight: 600;
  font-family: 'Courier New', monospace;
}

.status-badge {
  padding: 0.3rem 0.6rem;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: 600;
}

.status-badge.running {
  background-color: rgba(74, 222, 128, 0.3);
  color: #4ade80;
}

.status-badge.completed {
  background-color: rgba(59, 130, 246, 0.3);
  color: #3b82f6;
}

.status-badge.failed {
  background-color: rgba(239, 68, 68, 0.3);
  color: #ef4444;
}

@media (max-width: 768px) {
  .session-control {
    padding: 1rem;
  }

  .button-group {
    flex-direction: column;
  }

  .btn {
    width: 100%;
  }

  .progress-info {
    flex-direction: column;
    gap: 0.75rem;
  }
}
</style>
