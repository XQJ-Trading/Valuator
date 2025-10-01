<template>
  <header class="app-header">
    <div class="header-content">
      <h1 class="app-title">
        <span class="title-icon">🤖</span>
        AI Agent
      </h1>
    </div>
  </header>
</template>

<style scoped>
/* 헤더 */
.app-header {
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  padding: 1rem 0;
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(10px);
}

.header-content {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 1.5rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.app-title {
  margin: 0;
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--primary-color);
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.title-icon {
  font-size: 2rem;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

/* 반응형 디자인 */
@media (max-width: 768px) {
  .header-content {
    padding: 0 1rem;
  }
  
  .app-title {
    font-size: 1.5rem;
  }
}
</style>
