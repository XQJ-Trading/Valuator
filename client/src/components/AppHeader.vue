<template>
  <header class="app-header">
    <div class="header-content">
      <router-link to="/" class="app-title-link">
        <h1 class="app-title">
          <span class="title-icon">🤖</span>
          Qualitative Research Agent
        </h1>
      </router-link>
      
      <nav class="nav-menu">
        <router-link to="/ongoing" class="nav-btn">
          <span class="nav-icon">🔄</span>
          Ongoing
        </router-link>
        <router-link to="/history" class="nav-btn">
          <span class="nav-icon">📚</span>
          History
        </router-link>
        <div 
          class="nav-dropdown"
          @mouseenter="showRewriteMenu = true"
          @mouseleave="showRewriteMenu = false"
        >
          <button class="nav-btn nav-btn-dropdown">
            <span class="nav-icon">✏️</span>
            Rewrite
            <span class="dropdown-arrow">▼</span>
          </button>
          <div v-if="showRewriteMenu" class="dropdown-menu">
            <router-link to="/rewrite" class="dropdown-item" @click="showRewriteMenu = false">
              <span class="dropdown-icon">✨</span>
              Rewrite
            </router-link>
            <router-link to="/rewrite/history" class="dropdown-item" @click="showRewriteMenu = false">
              <span class="dropdown-icon">📋</span>
              History
            </router-link>
          </div>
        </div>
        <button @click="handleNewSession" class="nav-btn">
          <span class="nav-icon">✨</span>
          New Session
        </button>
      </nav>
    </div>
  </header>
</template>

<script setup lang="ts">
import { ref } from 'vue'

interface Emits {
  (e: 'newSession'): void
}

const emit = defineEmits<Emits>()

const showRewriteMenu = ref(false)

function handleNewSession() {
  emit('newSession')
}
</script>

<style scoped>
/* 헤더 */
.app-header {
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  padding: 0.75rem 0;
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(10px);
}

.header-content {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 1rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.app-title-link {
  text-decoration: none;
  color: inherit;
}

.app-title {
  margin: 0;
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--primary-color);
  display: flex;
  align-items: center;
  gap: 0.5rem;
  transition: var(--transition);
}

.app-title-link:hover .app-title {
  opacity: 0.8;
}

.title-icon {
  font-size: 1.5rem;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

/* 내비게이션 메뉴 */
.nav-menu {
  display: flex;
  gap: 1rem;
  align-items: center;
}

.nav-btn {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.5rem 1rem;
  background: linear-gradient(135deg, var(--primary-color) 0%, #1d4ed8 100%);
  color: white;
  border: none;
  border-radius: var(--border-radius);
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
  font-size: 0.85rem;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
  text-decoration: none; /* router-link 기본 스타일 제거 */
  font-family: inherit; /* 폰트 통일 */
}

.nav-btn:hover {
  background: linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4);
}

.nav-btn:active {
  transform: translateY(0);
  box-shadow: 0 2px 4px rgba(37, 99, 235, 0.3);
}

.nav-icon {
  font-size: 0.9rem;
}

/* 드롭다운 메뉴 */
.nav-dropdown {
  position: relative;
}

.nav-btn-dropdown {
  position: relative;
}

.dropdown-arrow {
  font-size: 0.7rem;
  margin-left: 0.25rem;
  transition: transform 0.2s;
}

.nav-dropdown:hover .dropdown-arrow {
  transform: rotate(180deg);
}

.dropdown-menu {
  position: absolute;
  top: calc(100% + 0.5rem);
  right: 0;
  background: white;
  border-radius: var(--border-radius);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  min-width: 160px;
  overflow: hidden;
  z-index: 1000;
  animation: slideDown 0.2s ease-out;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  color: var(--text-primary);
  text-decoration: none;
  transition: var(--transition);
  border-bottom: 1px solid #f0f0f0;
}

.dropdown-item:last-child {
  border-bottom: none;
}

.dropdown-item:hover {
  background: var(--bg-tertiary);
  color: var(--primary-color);
}

.dropdown-icon {
  font-size: 0.9rem;
}

/* 모달 스타일 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
  animation: fadeIn 0.3s ease-out;
}

.modal-content {
  background: var(--bg-primary);
  border-radius: var(--border-radius);
  box-shadow: var(--shadow-lg);
  max-width: 400px;
  width: 90%;
  animation: slideIn 0.3s ease-out;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem 1.5rem 1rem;
  border-bottom: 1px solid var(--border-color);
}

.modal-header h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 1.25rem;
}

.modal-close {
  background: none;
  border: none;
  font-size: 1.25rem;
  cursor: pointer;
  color: var(--text-secondary);
  padding: 0.25rem;
  border-radius: 4px;
  transition: var(--transition);
}

.modal-close:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.modal-body {
  padding: 1.5rem;
}

.modal-body p {
  margin: 0 0 0.75rem;
  color: var(--text-secondary);
  line-height: 1.6;
}

.modal-body p:last-child {
  margin-bottom: 0;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideIn {
  from { 
    opacity: 0;
    transform: translateY(-20px) scale(0.95);
  }
  to { 
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

/* 반응형 디자인 */
@media (max-width: 768px) {
  .app-header {
    padding: 0.5rem 0;
  }
  
  .header-content {
    padding: 0 0.75rem;
    flex-wrap: wrap;
    gap: 0.75rem;
  }
  
  .app-title {
    font-size: 1.25rem;
  }
  
  .title-icon {
    font-size: 1.3rem;
  }
  
  .nav-menu {
    gap: 0.5rem;
  }
  
  .nav-btn {
    padding: 0.4rem 0.85rem;
    font-size: 0.8rem;
  }
  
  .nav-icon {
    font-size: 0.85rem;
  }
}

@media (max-width: 480px) {
  .header-content {
    padding: 0 0.5rem;
  }
  
  .app-title {
    font-size: 1.1rem;
  }
  
  .title-icon {
    font-size: 1.2rem;
  }
  
  .nav-menu {
    width: 100%;
    justify-content: center;
    gap: 0.4rem;
  }
  
  .nav-btn {
    flex: 1;
    justify-content: center;
    padding: 0.35rem 0.75rem;
    font-size: 0.75rem;
  }
  
  .nav-icon {
    font-size: 0.8rem;
  }
}
</style>
