<template>
  <div class="app-container">
    <!-- Header -->
    <AppHeader @newSession="handleNewSession" />

    <!-- Router View -->
    <router-view></router-view>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import AppHeader from './components/AppHeader.vue'

const router = useRouter()

function handleNewSession() {
  // 채팅 페이지로 이동하고 상태 초기화는 ChatPage에서 처리
  router.push('/')
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
