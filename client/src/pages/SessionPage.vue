<template>
  <div class="session-page">
    <!-- 헤더 -->
    <div class="page-header">
      <router-link to="/ongoing" class="btn-back">← 돌아가기</router-link>
      <h1>🔄 Session</h1>
    </div>

    <!-- Session Control -->
    <SessionControl
      :currentSessionId="currentSessionId"
      :connectionState="connectionState"
      :activeSession="activeSession"
      :isSessionActive="isSessionActive"
      :sessionProgress="sessionProgress"
      :loading="loading"
      @reconnect="handleReconnect"
      @terminate="handleTerminate"
    />

    <!-- Status Bar -->
    <StatusBar :status="status" :loading="loading" />

    <!-- Messages Container -->
    <MessagesContainer :messages="messages" />

    <!-- 완료 후 액션 -->
    <div v-if="sessionCompleted" class="session-complete">
      <p>✅ 세션이 완료되었습니다</p>
      <div class="action-buttons">
        <router-link to="/" class="btn-new">새 세션 시작</router-link>
        <router-link to="/ongoing" class="btn-ongoing">활성 세션 확인</router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import SessionControl from '../components/SessionControl.vue'
import StatusBar from '../components/StatusBar.vue'
import MessagesContainer from '../components/MessagesContainer.vue'
import { useSession } from '../composables/useSession'

interface Props {
  sessionId: string
}

const props = defineProps<Props>()
const router = useRouter()

const {
  status,
  loading,
  messages,
  currentSessionId,
  activeSession,
  connectionState,
  isSessionActive,
  sessionProgress,
  reconnectToSession,
  reconnect,
  terminateSession,
  closeStream
} = useSession()

const sessionCompleted = ref(false)

onMounted(() => {
  // sessionId를 받아서 해당 세션에 재연결
  if (props.sessionId) {
    reconnectToSession(props.sessionId)
  }
})

// 세션 완료 감지
watch(() => status.value, (newStatus) => {
  if (newStatus === '완료') {
    sessionCompleted.value = true
  }
})

function handleReconnect() {
  reconnect()
}

async function handleTerminate() {
  if (confirm('정말로 세션을 종료하시겠습니까?')) {
    closeStream()
    await terminateSession()
    router.push('/ongoing')
  }
}
</script>

<style scoped>
.session-page {
  min-height: calc(100vh - 60px);
  max-width: 1200px;
  margin: 0 auto;
  padding: 16px 1rem 0 1rem;
  display: flex;
  flex-direction: column;
}

/* 헤더 */
.page-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.5rem;
  padding-bottom: 1rem;
  border-bottom: 2px solid var(--border-color);
}

.page-header h1 {
  margin: 0;
  font-size: 1.5rem;
  color: var(--text-primary);
  flex: 1;
}

.btn-back {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.5rem 1rem;
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  text-decoration: none;
  font-size: 0.9rem;
}

.btn-back:hover {
  background: var(--primary-color);
  color: white;
  border-color: var(--primary-color);
}

/* 완료 메시지 */
.session-complete {
  margin-top: 2rem;
  padding: 2rem;
  background: linear-gradient(135deg, rgba(74, 222, 128, 0.1) 0%, rgba(34, 197, 94, 0.05) 100%);
  border: 2px solid #4ade80;
  border-radius: var(--border-radius);
  text-align: center;
}

.session-complete p {
  margin: 0 0 1.5rem;
  font-size: 1.2rem;
  font-weight: 600;
  color: #16a34a;
}

.action-buttons {
  display: flex;
  gap: 1rem;
  justify-content: center;
}

.btn-new,
.btn-ongoing {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.6rem 1.2rem;
  background: var(--primary-color);
  color: white;
  border: none;
  border-radius: var(--border-radius);
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  text-decoration: none;
  font-size: 0.95rem;
}

.btn-new:hover,
.btn-ongoing:hover {
  background: #1d4ed8;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
}

/* 반응형 */
@media (max-width: 768px) {
  .session-page {
    min-height: calc(100vh - 50px);
    padding: 0 0.75rem;
  }

  .page-header {
    margin-bottom: 1rem;
    padding-bottom: 0.75rem;
    flex-wrap: wrap;
    gap: 0.75rem;
  }

  .page-header h1 {
    font-size: 1.3rem;
    flex-basis: 100%;
  }

  .btn-back {
    padding: 0.4rem 0.85rem;
    font-size: 0.85rem;
  }

  .session-complete {
    margin-top: 1.5rem;
    padding: 1.5rem;
  }

  .session-complete p {
    font-size: 1.1rem;
    margin-bottom: 1rem;
  }

  .action-buttons {
    flex-direction: column;
    gap: 0.75rem;
  }

  .btn-new,
  .btn-ongoing {
    width: 100%;
    justify-content: center;
  }
}

@media (max-width: 480px) {
  .session-page {
    min-height: calc(100vh - 45px);
    padding: 0 0.5rem;
  }

  .page-header {
    margin-bottom: 0.75rem;
    padding-bottom: 0.5rem;
    gap: 0.5rem;
  }

  .page-header h1 {
    font-size: 1.1rem;
  }

  .btn-back {
    padding: 0.35rem 0.75rem;
    font-size: 0.8rem;
  }

  .session-complete {
    margin-top: 1rem;
    padding: 1rem;
  }

  .session-complete p {
    font-size: 1rem;
    margin-bottom: 0.75rem;
  }

  .action-buttons {
    gap: 0.5rem;
  }

  .btn-new,
  .btn-ongoing {
    padding: 0.5rem 1rem;
    font-size: 0.85rem;
  }
}
</style>
