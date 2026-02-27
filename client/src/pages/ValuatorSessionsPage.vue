<template>
  <div class="valuator-page valuator-sessions-page">
    <div class="valuator-page-header">
      <h1>Valuator Sessions</h1>
      <button class="valuator-refresh-btn" @click="refreshSessions" :disabled="loading">
        {{ loading ? 'Loading...' : 'Refresh' }}
      </button>
    </div>

    <div v-if="loading" class="valuator-state">Loading sessions...</div>
    <div v-else-if="error" class="valuator-state valuator-state-error">{{ error }}</div>
    <div v-else-if="sessions.length === 0" class="valuator-state">No sessions found.</div>

    <div v-else class="valuator-session-grid">
      <router-link
        v-for="session in sessions"
        :key="session.session_id"
        :to="`/sessions/${session.session_id}`"
        class="valuator-session-card"
      >
        <div class="valuator-session-card-header">
          <span class="valuator-session-id">{{ session.session_id }}</span>
          <span class="valuator-session-status">{{ toStatusText(session.status) }}</span>
        </div>
        <p class="valuator-session-query">{{ session.query }}</p>
        <p class="valuator-session-time">{{ formatTimestamp(session) }}</p>
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useValuatorSession } from '../composables/useValuatorSession'
import type { ValuatorSessionSummary } from '../types/Valuator'

const { sessions, loading, error, fetchSessions } = useValuatorSession()
const LIST_REFRESH_INTERVAL_MS = 4000
let listTimer: number | null = null

onMounted(() => {
  void fetchSessions()
  listTimer = window.setInterval(() => {
    void fetchSessions()
  }, LIST_REFRESH_INTERVAL_MS)
})

onBeforeUnmount(() => {
  if (listTimer !== null) {
    window.clearInterval(listTimer)
    listTimer = null
  }
})

function refreshSessions() {
  void fetchSessions()
}

function formatTimestamp(session: ValuatorSessionSummary): string {
  const raw = session.created_at || session.timestamp
  if (!raw) {
    return '-'
  }

  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) {
    return raw
  }

  return parsed.toLocaleString('ko-KR')
}

function toStatusText(status: string): string {
  if (status === 'completed') {
    return 'COMPLETED'
  }
  if (status === 'running') {
    return 'RUNNING'
  }
  if (status === 'failed') {
    return 'FAILED'
  }
  return status.toUpperCase()
}
</script>

<style scoped>
.valuator-page {
  min-height: calc(100vh - 60px);
  max-width: 1200px;
  margin: 0 auto;
  padding: 1rem;
}

.valuator-page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.valuator-page-header h1 {
  margin: 0;
  font-size: 1.5rem;
}

.valuator-refresh-btn {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  padding: 0.45rem 0.75rem;
  font-weight: 600;
  cursor: pointer;
}

.valuator-refresh-btn:disabled {
  opacity: 0.6;
  cursor: default;
}

.valuator-state {
  padding: 1rem;
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  background: var(--bg-secondary);
}

.valuator-state-error {
  color: var(--error-color);
}

.valuator-session-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.75rem;
}

.valuator-session-card {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  padding: 0.9rem;
  text-decoration: none;
  color: inherit;
  background: var(--bg-secondary);
}

.valuator-session-card:hover {
  border-color: var(--primary-color);
}

.valuator-session-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.valuator-session-id {
  font-size: 0.8rem;
  color: var(--text-secondary);
  font-family: 'Courier New', monospace;
}

.valuator-session-status {
  font-size: 0.75rem;
  color: var(--text-primary);
  font-weight: 700;
}

.valuator-session-query {
  margin: 0;
  color: var(--text-primary);
  line-height: 1.4;
}

.valuator-session-time {
  margin: 0;
  color: var(--text-secondary);
  font-size: 0.82rem;
}
</style>
