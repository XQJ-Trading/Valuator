<template>
  <div class="messages-container">
    <div v-if="messages.length === 0" class="empty-state">
      <div class="empty-icon">💭</div>
      <h3>AI Agent와 대화해보세요</h3>
      <p>복잡한 계산, 정보 검색, 코드 실행 등 다양한 작업을 요청할 수 있습니다.</p>
    </div>
    
    <div v-for="(message, index) in messages" :key="index" class="message-group">
      <MessageCard :message="message" />
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Message } from '../types/Message'
import MessageCard from './MessageCard.vue'

interface Props {
  messages: Message[]
}

defineProps<Props>()
</script>

<style scoped>
/* 메시지 컨테이너 */
.messages-container {
  width: 100%;
  padding: 0 0 1.5rem 0;
}

.empty-state {
  text-align: center;
  padding: 2.5rem 2rem;
  color: var(--text-secondary);
}

.empty-icon {
  font-size: 4rem;
  margin-bottom: 1rem;
  opacity: 0.5;
}

.empty-state h3 {
  margin: 0 0 0.5rem 0;
  color: var(--text-primary);
}

.empty-state p {
  margin: 0;
  max-width: 500px;
  margin: 0 auto;
  line-height: 1.6;
}

.message-group {
  margin-bottom: 1.25rem;
  position: relative;
}

.message-group::after {
  content: '';
  position: absolute;
  bottom: -0.625rem;
  left: 50%;
  transform: translateX(-50%);
  width: 40px;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--border-color), transparent);
  opacity: 0.3;
}

.message-group:last-child::after {
  display: none;
}

/* 반응형 디자인 */
@media (max-width: 768px) {
  .messages-container {
    padding: 0 1rem 2rem;
  }
}
</style>
